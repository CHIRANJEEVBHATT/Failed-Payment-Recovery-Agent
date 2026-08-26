# Failed Payment Recovery Agent

A Python backend agent that detects failed payments, classifies the failure
reason, selects a safe recovery action, executes eligible actions through
Razorpay's TEST MODE APIs, records every decision in SQLite, and surfaces
the results through a local browser dashboard.

---

## Overview

Merchants lose revenue whenever a payment fails. Common causes include
insufficient funds, expired cards, bank/network timeouts, OTP failures,
fraud blocks, and failed subscription mandates — and each one warrants a
different response. Insufficient funds may justify a delayed retry; an
expired card needs a new payment method; an OTP failure should prompt the
customer rather than silently retry; a fraud block should go straight to
a human.

This agent automates that decision-making end-to-end while keeping every
action fully auditable and every reported number honest.

For each failed payment in a batch, the agent:

1. Reads the payment record
2. Classifies the failure reason
3. Selects a recovery action using deterministic rules
4. Applies safety and stopping rules
5. Executes eligible actions through Razorpay TEST MODE
6. Records the decision and API result in SQLite
7. Generates a recovery report
8. Surfaces batch statistics through a local dashboard

---

## Architecture

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
       /        \
      v          v
Razorpay API   SQLite Audit DB
      \          /
       v        v
     Recovery Results
          |
          v
        Reporter
          |
          v
    output/report.md
```

```text
SQLite Audit DB
      |
      v
dashboard/server.py  ->  GET /api/dashboard
      |
      v
dashboard/index.html
      |
      v
   Browser
```

The recovery logic is entirely backend-driven. The dashboard is a thin,
read-only visualization layer over the audit database — it contains no
business logic and cannot influence a recovery decision.

---

## Project Structure

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
├── dashboard/
│   ├── index.html
│   └── server.py
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

Runtime artifacts — `.env`, `audit.db`, generated datasets, reports, and
logs — are excluded from version control (see `.gitignore`).

---

## Synthetic Data

`app/generator.py` produces 60–100 synthetic failed-payment records. This
data does not represent real customers.

Each record contains:

```text
payment_id, customer_name, email, phone, amount,
failure_reason, attempt_count, payment_type, last_attempt_at
```

Supported failure reasons:

```text
insufficient_funds, card_expired, bank_timeout,
otp_failed, fraud_block, mandate_failed
```

Generate a fresh dataset:

```bash
python -m app.generator
```

Output: `data/failed_payments.json`, `data/failed_payments.csv`

---

## Decision Engine

The decision engine is fully deterministic — payment-recovery decisions
should be predictable, testable, and explainable, not left to chance.

| Failure reason | Action | Rule |
|---|---|---|
| `insufficient_funds` | `RETRY_LATER` | 6-hour delay, max 2 retries |
| `card_expired` | `SEND_NEW_LINK` | Create a new payment link |
| `bank_timeout` | `RETRY_NOW` | Max 1 retry |
| `otp_failed` | `SEND_REMINDER` | Never silently retried |
| `fraud_block` | `ESCALATE_HUMAN` | Never auto-retried |
| `mandate_failed` (subscription) | `ESCALATE_HUMAN` | Human intervention |
| `mandate_failed` (one-time) | `SEND_NEW_LINK` | New payment link |

**Global override:** any payment with `attempt_count >= 3` becomes
`DO_NOT_RETRY`, regardless of failure reason.

---

## Safety / Stopping Rules

- **Max attempts** — no payment is auto-retried beyond 3 total attempts.
- **Duplicate-retry protection** — the same `payment_id` cannot be
  retried within 10 minutes, reducing duplicate-charge risk.
- **Fraud protection** — `fraud_block` is escalated to a human
  immediately, with zero automatic retries, no exceptions.

---

## Razorpay TEST MODE Integration

Credentials are loaded from environment variables and never hardcoded.

`.env.example`:

```env
RAZORPAY_KEY_ID=rzp_test_xxxx
RAZORPAY_KEY_SECRET=xxxx
MAX_REAL_API_CALLS=20
```

Eligible `SEND_NEW_LINK` actions create a Razorpay Payment Link via the
TEST MODE API, using:

```text
amount, currency, customer name, customer email,
customer phone, reference_id
```

Every request and response is written to `logs/razorpay_api.log`
(credentials excluded).

### Test-mode Payment Link cap

Razorpay TEST MODE limits the number of Payment Links a business can
create. Since a batch can contain up to 100 failed payments, issuing a
real link for every eligible record isn't realistic in a test
environment, so this is handled explicitly via:

```env
MAX_REAL_API_CALLS=20
```

Only `SEND_NEW_LINK` actions consume a real API slot. Once the cap is
reached, remaining eligible actions are marked
`simulated_due_to_test_mode_cap` — logged, never silently skipped, and
never counted as real recovery.

---

## Recovery Metrics

Creating a Payment Link successfully does not mean the customer paid it.
To avoid overstating results, recovery is tracked at three distinct
levels:

| Tier | Meaning |
|---|---|
| **Confirmed settlement** | Razorpay confirms the payment was actually completed |
| **Recovery action triggered** | A real API call succeeded (e.g. link created) — action taken, payment not yet confirmed |
| **Simulated** | The API cap was reached; logged as what would have been attempted, excluded from the metrics above |

The headline recovery rate is based on confirmed settlements only.
"Actions triggered" is reported as a separate, clearly labeled secondary
metric — the two are never blended into one number.

---

## SQLite Audit Trail

Managed entirely through Python's built-in `sqlite3` module — no external
database server required. Stored at `database/audit.db`.

Each record captures:

```text
timestamp, payment_id, customer_name, email, amount,
failure_reason, payment_type, attempt_count,
decision, decision_reason, action_taken,
api_request, api_response, api_status_code,
outcome, recovery_type, real_api_call, simulated, notes
```

This table is the project's explainability layer — it answers both *why*
a decision was made and *what happened* afterward.

---

## Reporting

`app/reporter.py` generates `output/report.md`, containing:

- Total amount at risk
- Confirmed settlement amount and count (headline rate)
- Recovery-actions-triggered amount and count (secondary metric)
- Simulated amount and count (excluded from both rates above)
- Failure-reason breakdown
- Exceptions: every `ESCALATE_HUMAN` and `DO_NOT_RETRY` record, with the
  reason it was excluded from automated recovery

---

## Dashboard

A lightweight, read-only dashboard (`dashboard/index.html` +
`dashboard/server.py`) visualizes the current audit database.

```text
SQLite  ->  server.py (/api/dashboard)  ->  index.html  ->  Browser
```

Displays: total amount at risk, real recovery amount and rate, payments
processed / audit coverage, real API calls used, simulated recovery
amount, still-failed and escalated payments, failure-reason breakdown,
and exceptions.

The dashboard is a visualization convenience — the recovery logic runs
and is fully tested independently of it.

---

## Getting Started

**Clone and set up a virtual environment:**

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Configure Razorpay:**

```bash
cp .env.example .env
```

Add your TEST MODE credentials to `.env`. Never commit this file.

**Generate synthetic data:**

```bash
python -m app.generator
```

**Run the recovery pipeline:**

```bash
python run.py
```

Pipeline flow:

```text
Load dataset -> Validate -> Init SQLite -> Process payments
-> Apply decision rules -> Call Razorpay TEST MODE (within cap)
-> Write audit records -> Verify audit coverage -> Generate report
```

**Start the dashboard** (after a batch has been processed):

```bash
python dashboard/server.py
```

Open `http://127.0.0.1:5000`. Do not open `dashboard/index.html` directly
via `file://` — it fetches live data from `/api/dashboard`, which
requires the server to be running.

---

## Testing

```bash
python -m pytest tests -v
```

Covers: decision rules for every failure reason, retry limits, OTP
handling and fraud escalation, subscription mandate handling, the
max-attempts override, duplicate-retry protection, API cap enforcement
and error handling, audit logging completeness, the confirmed / triggered
/ simulated separation, report generation, and backend behavior
independent of the dashboard.

---

## Example Output

From an actual end-to-end run:

```text
Records processed: 98
Total amount at risk: ₹347,402.00

Real Razorpay API calls: 12 / 20 (cap)
Recovery actions triggered: ₹9,996.00 (12 records)
Audit coverage: 98 / 98
```

Full metrics, including the confirmed-settlement breakdown, are written
to `output/report.md`.

---

## API Failure Handling

Razorpay may return `HTTP 429 Too Many Requests` under load. When this
happens, the response is logged, the API attempt is recorded in the audit
trail, and the action is not counted as recovered — an API error is never
converted into a successful recovery.

---

## Security

- Never commit `.env` — only `.env.example` is tracked.
- Use TEST MODE credentials only (`rzp_test_*`).
- Confirm with `git status` before every commit that `.env` and `venv/`
  are not staged.

---

## Design Notes

- **Deterministic over generative** — the decision engine uses explicit
  rules rather than an LLM, so every action is predictable and testable.
- **No inflated metrics** — a created Payment Link is a triggered action,
  not a confirmed payment; the two are never conflated in reporting.
- **Explicit constraint handling** — the TEST MODE Payment Link cap is
  handled as a first-class case, not worked around silently.
- **Minimal surface area** — the dashboard is a visualization layer, not
  a dependency of the core pipeline.

---

## Limitations

- This project uses Razorpay TEST MODE only; no real payments are
  processed.
- A successfully created Payment Link indicates a recovery action was
  triggered — it does not by itself confirm the customer paid.
- The synthetic dataset is generated locally and does not reflect real
  customer or transaction data.

---

## License

MIT