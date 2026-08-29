# Failed Payment Recovery Agent

A Python-based revenue recovery agent that detects failed payments, determines the safest recovery action, executes eligible actions through Razorpay TEST MODE, verifies whether payments were actually completed, maintains a complete SQLite audit trail, and presents the results through a local dashboard.

The project is designed around one principle:

> **A recovery action is not the same thing as recovered revenue.**

Creating a Payment Link does not mean the customer paid. Revenue is counted as recovered only after Razorpay confirms a completed payment.

---

## Overview

Payment failures can have very different causes:

* Insufficient funds
* Expired cards
* Bank/network timeouts
* OTP failures
* Fraud blocks
* Failed payment mandates

Each failure requires a different response.

For example:

* Insufficient funds → retry later
* Expired card → create a new Payment Link
* Bank timeout → controlled retry
* OTP failure → customer reminder
* Fraud block → human escalation
* Subscription mandate failure → human escalation
* One-time mandate failure → new Payment Link

The agent automates this workflow using deterministic, explainable rules while keeping safety controls and financial reporting explicit.

For each failed payment, the system:

1. Loads the payment record
2. Validates the dataset
3. Classifies the failure reason
4. Selects a recovery action
5. Applies safety and stopping rules
6. Executes eligible actions through Razorpay TEST MODE
7. Checks Payment Link settlement status
8. Distinguishes confirmed recovery from triggered actions
9. Stores the complete audit record in SQLite
10. Generates recovery metrics and a report
11. Displays the batch through a local dashboard

---

# Architecture

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
       /      \
      /        \
     v          v
Razorpay API   SQLite Audit DB
     |              |
     |              v
     |        Audit / Metrics
     |
     v
Payment Link
     |
     v
Settlement Check
     |
     v
+---------------------------+
| Payment actually paid?    |
+---------------------------+
       |              |
      YES             NO
       |              |
       v              v
Confirmed         Awaiting
Settlement        Payment
       |
       v
    Reporter
       |
       v
 output/report.md
```

### Dashboard architecture

```text
SQLite Audit DB
       |
       v
dashboard/server.py
       |
       v
GET /api/dashboard
       |
       v
dashboard/index.html
       |
       v
    Browser
```

The dashboard is a read-only visualization layer. It contains no recovery business logic and cannot influence recovery decisions.

---

# Project Structure

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

Runtime files such as `.env`, `audit.db`, generated datasets, reports, logs, and the virtual environment should not be committed to GitHub.

---

# Synthetic Dataset

`app/generator.py` generates a synthetic batch of failed-payment records.

The data does **not** represent real customers.

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

Generate a fresh dataset:

```bash
python -m app.generator
```

This creates:

```text
data/failed_payments.json
data/failed_payments.csv
```

---

# Decision Engine

The decision engine is deterministic.

The LLM is intentionally **not** responsible for deciding financial recovery actions.

This makes the system predictable, testable, and explainable.

| Failure Reason                  | Action           | Rule                            |
| ------------------------------- | ---------------- | ------------------------------- |
| `insufficient_funds`            | `RETRY_LATER`    | 6-hour delay, maximum 2 retries |
| `card_expired`                  | `SEND_NEW_LINK`  | Create a new Payment Link       |
| `bank_timeout`                  | `RETRY_NOW`      | Maximum 1 retry                 |
| `otp_failed`                    | `SEND_REMINDER`  | Never silently retried          |
| `fraud_block`                   | `ESCALATE_HUMAN` | Never automatically retried     |
| `mandate_failed` — subscription | `ESCALATE_HUMAN` | Human intervention              |
| `mandate_failed` — one-time     | `SEND_NEW_LINK`  | Create a new Payment Link       |

### Global stopping rule

Any payment with:

```text
attempt_count >= 3
```

is converted to:

```text
DO_NOT_RETRY
```

regardless of the failure reason.

---

# Safety and Stopping Rules

The agent is intentionally bounded.

### Maximum attempts

No payment is automatically retried beyond three total attempts.

### Duplicate retry protection

The same payment cannot be automatically retried within ten minutes.

This reduces duplicate-charge risk.

### Fraud protection

`fraud_block` always results in:

```text
ESCALATE_HUMAN
```

There are no automatic retries for fraud-blocked payments.

### API safety cap

Razorpay TEST MODE Payment Link creation is limited by:

```env
MAX_REAL_API_CALLS=20
```

Once the limit is reached, additional eligible Payment Link actions are explicitly marked as simulated.

They are:

* not sent to Razorpay
* recorded in the audit trail
* not counted as real recovery

---

# Razorpay TEST MODE Integration

The project uses Razorpay TEST MODE APIs.

Credentials are loaded from environment variables and are never hardcoded.

`.env.example`:

```env
RAZORPAY_KEY_ID=rzp_test_xxxx
RAZORPAY_KEY_SECRET=xxxx
MAX_REAL_API_CALLS=20
```

Eligible `SEND_NEW_LINK` actions create a Payment Link using:

```text
amount
currency
customer name
customer email
customer phone
reference_id
```

Every Razorpay request and response is logged to:

```text
logs/razorpay_api.log
```

Credentials are excluded from the API logs.

---

# Confirmed Settlement Tracking

This is one of the core features of the project.

A successful Payment Link creation is **not** treated as recovered revenue.

The workflow is:

```text
POST /payment_links
        |
        v
Payment Link created
        |
        v
GET /payment_links/{id}
        |
        v
Check settlement status
```

A recovery is confirmed only when:

```text
status == "paid"
```

and:

```text
amount_paid > 0
```

### Example

```text
Payment Link created
        |
        v
status = created
amount_paid = ₹0
        |
        v
AWAITING_PAYMENT
        |
        v
₹0 confirmed revenue
```

Compared with:

```text
Payment Link created
        |
        v
status = paid
amount_paid = ₹999
        |
        v
CONFIRMED_SETTLEMENT
        |
        v
₹999 confirmed recovered revenue
```

This prevents the system from inflating recovery numbers by treating API activity as financial recovery.

---

# Recovery Metrics

The project separates recovery into three categories.

| Metric                        | Meaning                                                                      |
| ----------------------------- | ---------------------------------------------------------------------------- |
| **Confirmed settlement**      | Razorpay confirms the customer actually paid                                 |
| **Recovery action triggered** | A real recovery API action succeeded, but payment has not yet been confirmed |
| **Simulated**                 | Action could not be executed because the TEST MODE API cap was reached       |

The headline recovery metric is based on **confirmed settlements only**.

The system never combines:

```text
Payment Link created
```

with:

```text
Payment actually completed
```

as if they were the same event.

---

# SQLite Audit Trail

The project uses Python's built-in `sqlite3` module.

No external database server is required.

The database is stored at:

```text
database/audit.db
```

The audit trail records:

```text
timestamp
payment_id
customer_name
email
amount
failure_reason
payment_type
attempt_count

decision
decision_reason
action_taken

api_request
api_response
api_status_code

outcome
recovery_type
real_api_call
simulated
notes

payment_link_id
settlement_status
settlement_confirmed
settlement_amount
settlement_amount_paid
settlement_payment_id
settlement_api_status_code
settlement_error
settlement_checked_at
```

The database schema supports automatic migration so newly introduced settlement columns can be added to an existing development database without manually recreating it.

The audit trail provides the explainability layer for the system:

```text
Why did the agent make this decision?
What action did it take?
Did Razorpay accept the action?
Was the payment actually completed?
How much money was actually recovered?
```

---

# Reporting

`app/reporter.py` generates:

```text
output/report.md
```

The report includes:

* Total amount at risk
* Confirmed settlement amount
* Confirmed settlement count
* Confirmed recovery rate
* Recovery actions triggered
* Simulated actions
* Failure-reason breakdown
* Escalated payments
* Payments blocked by stopping rules
* Recovery exceptions

Confirmed recovery and triggered actions are reported separately.

---

# Dashboard

The project includes a lightweight local dashboard:

```text
dashboard/index.html
dashboard/server.py
```

The dashboard reads current data from the SQLite audit database through:

```text
GET /api/dashboard
```

It can display:

* Total amount at risk
* Confirmed recovered amount
* Confirmed recovery rate
* Payments processed
* Audit coverage
* Real Razorpay API calls
* Payment Links created
* Awaiting-payment amount
* Simulated actions
* Still-failed payments
* Escalated payments
* Failure-reason breakdown
* Exceptions

The dashboard is intentionally kept separate from the recovery engine.

It is a visualization layer, not the agent itself.

---

# Getting Started

## 1. Clone the repository

```bash
git clone <your-repository-url>
cd failed-payment-recovery-agent
```

## 2. Create a virtual environment

```bash
python -m venv venv
```

Windows:

```powershell
venv\Scripts\activate
```

Linux/macOS:

```bash
source venv/bin/activate
```

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

Current dependencies:

```text
requests
python-dotenv
pytest
```

## 4. Configure Razorpay

Copy:

```text
.env.example
```

to:

```text
.env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Add your Razorpay TEST MODE credentials:

```env
RAZORPAY_KEY_ID=rzp_test_xxxx
RAZORPAY_KEY_SECRET=xxxx
MAX_REAL_API_CALLS=20
```

Never commit `.env`.

## 5. Generate synthetic payments

```bash
python -m app.generator
```

## 6. Run the recovery agent

```bash
python run.py
```

The pipeline is:

```text
Load dataset
    ↓
Validate dataset
    ↓
Initialize SQLite
    ↓
Process payments
    ↓
Apply decision rules
    ↓
Execute eligible Razorpay TEST MODE actions
    ↓
Check Payment Link settlement status
    ↓
Write audit records
    ↓
Verify audit coverage
    ↓
Generate report
```

---

# Running the Dashboard

After processing a batch:

```bash
python dashboard/server.py
```

Open:

```text
http://127.0.0.1:5000
```

Do **not** open `dashboard/index.html` directly using `file://`.

The HTML dashboard fetches live data from:

```text
/api/dashboard
```

which requires the dashboard server.

---

# Testing

Run the complete test suite:

```bash
python -m pytest tests -v
```

The test suite covers:

* Decision rules
* Retry limits
* Fraud escalation
* OTP handling
* Mandate handling
* Maximum-attempt stopping rule
* Duplicate-retry protection
* Payment Link API cap
* Razorpay API error handling
* Confirmed settlement tracking
* Unpaid Payment Links
* Confirmed paid Payment Links
* Audit logging
* Real/simulated separation
* Recovery reporting
* Dashboard-independent backend behavior

The current project test suite contains **34 automated tests**.

---

# Example Recovery Flow

Consider this failed payment:

```text
Payment ID: pay_test_0003
Failure: mandate_failed
Type: one-time
Amount: ₹3,999
```

The decision engine determines:

```text
SEND_NEW_LINK
```

The processor creates a Razorpay TEST MODE Payment Link.

The system then checks the Payment Link:

```text
status = created
amount_paid = ₹0
```

Therefore:

```text
Action:
PAYMENT_LINK_CREATED

Outcome:
awaiting_payment

Recovery:
NOT CONFIRMED
```

If the customer subsequently completes the Payment Link and Razorpay reports:

```text
status = paid
amount_paid = ₹3,999
```

the record becomes:

```text
Outcome:
confirmed_settlement

Recovery type:
real

Confirmed recovered:
₹3,999
```

---

# Design Principles

### 1. Deterministic recovery decisions

Financial recovery decisions are made through explicit rules rather than an LLM.

This makes decisions:

* Predictable
* Testable
* Explainable
* Auditable

### 2. Confirm before counting revenue

The system does not claim money was recovered merely because an API request succeeded.

```text
API success ≠ Payment success
```

### 3. Bounded automation

The agent operates under explicit:

* Retry limits
* Duplicate protections
* Fraud protections
* API limits
* Human escalation rules

### 4. Honest reporting

Real, simulated, triggered, and confirmed outcomes are kept separate.

### 5. Auditability

Every processed payment produces an audit record containing the decision, reason, action, API result, outcome, and settlement information where applicable.

### 6. Dashboard independence

The dashboard cannot influence the recovery engine.

The backend works independently and can be tested without the dashboard.

---

# Limitations

* Razorpay integration uses TEST MODE only.
* No real customer payments are processed.
* Creating a Payment Link does not guarantee payment.
* Confirmed recovery requires a successful Razorpay settlement status check.
* The synthetic dataset does not represent real customer data.
* `RETRY_LATER` currently represents a scheduled recovery decision; a production-grade external scheduler would be required for persistent background execution.
* The dashboard currently focuses on the current audit dataset rather than long-term historical analytics.

---

# Future Improvements

Potential extensions include:

* Persistent retry scheduler
* CSV upload through the dashboard
* Historical batch tracking
* Recovery trend analytics
* Production payment-provider abstraction
* Customer notification integrations
* Multi-provider payment support
* Production database such as PostgreSQL
* Authentication and role-based dashboard access

These are intentionally separate from the current core recovery engine.

---

# Security

* Never commit `.env`
* Use Razorpay TEST MODE credentials
* Never hardcode API credentials
* Do not expose API secrets in logs
* Check `git status` before committing
* Keep `venv/` out of version control
* Keep generated runtime databases and logs out of version control

---

# License

MIT

