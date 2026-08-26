# Failed Payment Recovery Agent

A Python backend agent that detects failed payments, classifies the failure
reason, selects a recovery action, executes eligible actions through
Razorpay TEST MODE APIs, records every decision in SQLite, and produces an
honest, auditable recovery report.

Built for the **Razorpay AI Revenue Recovery** track.

---

## 1. Problem

Merchants lose revenue every time a payment fails. Common reasons:

- Insufficient funds
- Expired cards
- Bank / network timeouts
- OTP failures
- Fraud blocks
- Failed subscription mandates

Most businesses treat a failed payment as a dead end. This agent treats it
as a decision point: classify why it failed, decide the right response,
act on it within safe limits, and track exactly what happened.

---

## 2. What the agent actually does

For every failed payment in a batch:

1. Reads the record.
2. Classifies the failure reason.
3. Selects a recovery action using deterministic rules.
4. Applies safety and stopping rules.
5. Executes eligible actions via Razorpay TEST MODE APIs.
6. Logs the full decision + API trail to SQLite.
7. Generates a Markdown recovery report with honest, non-inflated numbers.

---

## 3. Architecture

```text
Synthetic Payment Dataset
        |
        v
   Dataset Validator
        |
        v
   Decision Engine
        |
        v
      Processor
      /       \
     /         \
Razorpay API   SQLite Audit DB
     |
     v
Recovery Results
     |
     v
   Reporter
     |
     v
output/report.md
```

---

## 4. Project Structure

```text
failed-payment-recovery-agent/
│
├── app/
│   ├── __init__.py
│   ├── audit_logger.py
│   ├── config.py
│   ├── decision_engine.py
│   ├── generator.py
│   ├── models.py
│   ├── processor.py
│   ├── razorpay_client.py
│   └── reporter.py
│
├── data/
│   ├── failed_payments.json
│   └── failed_payments.csv
│
├── database/
│   └── audit.db
│
├── logs/
│   └── razorpay_api.log
│
├── output/
│   └── report.md
│
├── tests/
│   ├── test_audit_logger.py
│   ├── test_decision_engine.py
│   ├── test_processor.py
│   └── test_reporter.py
│
├── .env
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
└── run.py
```

No frontend or UI framework is used. This is a deliberate choice — the
track's evaluation bar is about measured recovery, explainability, and
stopping rules, all of which are backend/data concerns. A UI would add
build time without adding signal.

---

## 5. Synthetic Data

`app/generator.py` creates 60–100 synthetic failed payment records.

Each record contains:

```text
payment_id
customer_name
email
phone
amount
failure_reason
attempt_count
payment_type
last_attempt_at
```

Supported failure reasons:

```text
insufficient_funds
card_expired
bank_timeout
otp_failed
fraud_block
mandate_failed
```

Generate a new dataset:

```powershell
python -m app.generator
```

Output:

```text
data/failed_payments.json
data/failed_payments.csv
```

---

## 6. Decision Engine

Deterministic rules — no black-box behavior, everything is explainable.

| Failure reason | Action | Rule |
|---|---|---|
| `insufficient_funds` | `RETRY_LATER` | delay 6 hours, max 2 retries |
| `card_expired` | `SEND_NEW_LINK` | — |
| `bank_timeout` | `RETRY_NOW` | max 1 retry |
| `otp_failed` | `SEND_REMINDER` | never silently retried |
| `fraud_block` | `ESCALATE_HUMAN` | never auto-retried |
| `mandate_failed` (subscription) | `ESCALATE_HUMAN` | — |
| `mandate_failed` (one-time) | `SEND_NEW_LINK` | — |

**Global override:** any payment with `attempt_count >= 3` becomes
`DO_NOT_RETRY`, regardless of failure reason.

---

## 7. Safety / Stopping Rules

These exist because an unbounded recovery agent is a liability, not a
feature.

- **Max attempts** — no payment is auto-retried beyond 3 total attempts.
- **Duplicate-charge protection** — the same `payment_id` cannot be
  retried within 10 minutes.
- **Fraud protection** — `fraud_block` is escalated to a human
  immediately, with zero automatic retries, no exceptions.

---

## 8. Razorpay TEST MODE Integration

Credentials are loaded from environment variables — never hardcoded.

`.env.example`:

```env
RAZORPAY_KEY_ID=rzp_test_xxxx
RAZORPAY_KEY_SECRET=xxxx
MAX_REAL_API_CALLS=20
```

`SEND_NEW_LINK` actions call Razorpay's Payment Links API with:

```text
amount, currency, customer name, customer email,
customer phone, reference_id
```

Every request and response is logged to `logs/razorpay_api.log`.

---

## 9. Test-Mode API Cap — a deliberate constraint, not a workaround

Razorpay TEST MODE allows a limited number of Payment Links per business
account. Our synthetic batch can contain up to 100 failed payments, so
creating a real link for every eligible record isn't realistic or
appropriate for a test environment.

The project handles this explicitly rather than hiding it:

```text
MAX_REAL_API_CALLS = 20
```

Only `SEND_NEW_LINK` actions consume a real API call slot. Once the cap
is reached, remaining `SEND_NEW_LINK` actions are marked:

```text
simulated_due_to_test_mode_cap
```

**They are never reported as real recovered revenue.**

---

## 10. Three-Tier Recovery Metric (real / triggered / simulated)

This is the most important design decision in the project, so it gets
its own section.

Creating a Payment Link successfully does **not** mean a customer paid
it — it means a recovery *action* was successfully triggered. Conflating
"link created" with "money recovered" would overstate the result. The
report keeps three tiers separate:

| Tier | Meaning |
|---|---|
| **Confirmed settlement** | Razorpay confirms the payment was actually completed (checked via payment status / webhook in test mode) |
| **Recovery action triggered** | A real Razorpay API call succeeded (e.g. link created, retry submitted) — action taken, outcome not yet confirmed |
| **Simulated** | The API cap was reached; the action is logged as what *would* have been attempted, and is excluded from both figures above |

The headline "recovery rate" in the report is always based on **confirmed
settlements**, not on links merely being created. "Actions triggered" is
reported separately as a secondary, clearly labeled metric.

---

## 11. SQLite Audit Trail

No external database server required — `sqlite3` (Python standard
library) manages `database/audit.db`.

Each processed record stores:

```text
timestamp, payment_id, customer_name, email, amount,
failure_reason, payment_type, attempt_count,
decision, decision_reason, action_taken,
api_request, api_response, api_status_code,
outcome, recovery_type, real_api_call,
simulated, notes
```

This table is the explainability layer — it answers both:

> Why did the agent make this decision?

> What actually happened after that decision?

---

## 12. Reporting

`app/reporter.py` generates `output/report.md` containing:

- Total amount at risk
- Confirmed settlement amount + count (headline recovery rate)
- Recovery-actions-triggered amount + count (secondary metric)
- Simulated amount + count (excluded from both rates above)
- Failure-reason breakdown table
- Honest exceptions list: every `ESCALATE_HUMAN` and `DO_NOT_RETRY`
  record, with the reason it was excluded from automated recovery

No metric in the report blends confirmed, triggered, and simulated
numbers without labeling which is which.

---

## 13. Honest Metrics — how a single action resolves

```text
SEND_NEW_LINK
    |
    +-- Razorpay 200 + payment completed  -> CONFIRMED SETTLEMENT
    |
    +-- Razorpay 200, payment not completed -> ACTION TRIGGERED (not counted as recovered)
    |
    +-- Razorpay 4xx/429                  -> NOT RECOVERED
    |
    +-- API cap already reached           -> SIMULATED (excluded from rate)
```

A failed or incomplete API interaction is never counted as recovered
revenue.

---

## 14. Running the Project

**Activate virtual environment** (Windows PowerShell):

```powershell
.\venv\Scripts\Activate.ps1
```

**Install dependencies:**

```powershell
pip install -r requirements.txt
```

**Configure Razorpay:**

```powershell
copy .env.example .env
```

Add your Razorpay TEST MODE key ID and secret to `.env`.

**Generate synthetic data:**

```powershell
python -m app.generator
```

**Run the full pipeline:**

```powershell
python run.py
```

Execution flow:

```text
Load dataset -> Validate -> Connect SQLite -> Clear previous batch
-> Process payments -> Call Razorpay TEST MODE (within cap)
-> Write audit records -> Verify audit coverage -> Generate report
```

---

## 15. Running Tests

```powershell
python -m pytest tests -v
```

Covers:

- Decision rules for every failure reason
- Max-attempts override
- Duplicate-retry protection
- Fraud auto-escalation
- OTP handling
- API cap enforcement
- Audit logging completeness
- Confirmed / triggered / simulated separation
- Report generation and honesty checks

---

## 16. Example Result

From an actual end-to-end run (not cherry-picked):

```text
Records processed: 98
Total amount at risk: ₹347,402.00

Real Razorpay API calls: 12 / 20 (cap)
Recovery actions triggered: ₹9,996.00 (12 records)
Confirmed settlements: [reported separately in output/report.md]
Simulated (excluded from rate): ₹0.00

Audit coverage: 98 / 98
```

---

## 17. API Rate Limits

Razorpay may return `HTTP 429 Too Many Requests` under load. This is
recorded as an API failure — it consumes a real API attempt slot but is
never counted as a recovery.

---

## 18. Logging

`logs/razorpay_api.log` records, for every API call:

```text
timestamp, HTTP method, endpoint, request payload,
HTTP status, response body
```

Secrets are not written to this log.

---

## 19. Security

- Never commit `.env` — only `.env.example` is tracked in Git.
- Use TEST MODE credentials only (`rzp_test_*`).
- Confirm with `git status` before every commit that `.env` is untracked.

---

## 20. Design Philosophy

Priorities, in order:

1. Correct Razorpay API integration
2. Honest, non-inflated recovery metrics
3. Complete audit logging
4. Safety and stopping rules
5. Simple, deterministic decision logic
6. Minimal architecture — no unnecessary UI or infrastructure
7. Explainability — every action traceable to a reason

This is intentionally a small, understandable backend agent — built to
be explained clearly in five minutes, not to impress with scale.

---

## 21. Video Demonstration Flow

1. **Project structure** — quick tour.
2. **Synthetic dataset** — show the range of failure reasons.
3. **Decision engine** — walk through the rule table in Section 6.
4. **Safety rules** — max attempts, duplicate protection, fraud escalation.
5. **Razorpay client** — confirm TEST MODE only.
6. **Run `python run.py`** — show a real `PAYMENT_LINK_CREATED` response.
7. **`logs/razorpay_api.log`** — show the real request/response pair.
8. **`database/audit.db`** — explain it as the explainability layer.
9. **`output/report.md`** — walk through confirmed / triggered / simulated
   numbers and the exceptions list.
10. **State the design principle explicitly:** *"Every number in this
    report is auditable. A created payment link is only counted as
    recovered revenue once settlement is confirmed — not before."*
11. **Explain the API cap** as a deliberate test-environment decision,
    not a limitation you were caught by.

---

## 22. Important Limitation

This is a TEST MODE recovery agent. A successfully created Payment Link
means a recovery *action* was executed — it does not by itself mean the
customer paid. The report's headline recovery rate is based on confirmed
settlements specifically so it never overstates real-world impact.

---

## 23. Status

```text
Synthetic data generation        done
Decision engine                  done
Safety rules                     done
Razorpay TEST MODE integration   done
Payment Link creation            done
API cap handling                 done
SQLite audit trail                done
Confirmed / triggered / simulated separation   done
Honest reporting                 done
Automated tests                  done
End-to-end execution             done
Documentation                    done
```