# Failed Payment Recovery Agent

A Python-based **Revenue Recovery Agent** built for **Track 03 --- AI
Revenue Recovery**.

The project identifies revenue at risk, decides the safest recovery
intervention, executes bounded actions where appropriate, verifies
actual payment recovery, records every decision in SQLite, and presents
the results through a local dashboard.

> **Core principle: A recovery action is not the same thing as recovered
> revenue.**

Creating a Payment Link, sending a reminder, escalating an invoice, or
simulating a customer return does not mean money was recovered. Revenue
is counted as recovered only when an actual payment is confirmed.

------------------------------------------------------------------------

## Problem

Revenue can slip away in several ways:

-   Failed payments
-   Checkout drop-offs
-   Overdue B2B invoices
-   Missed Promise-to-Pay commitments
-   Payment cases that require human intervention

A simple `payment failed -> retry` system is not enough. Different
situations require different interventions, and financial automation
needs clear stopping rules.

------------------------------------------------------------------------

## Solution

The project combines four revenue-recovery workflows:

1.  **Failed Payment Recovery**
2.  **Checkout Drop-off Recovery**
3.  **B2B Receivables Recovery**
4.  **Promise-to-Pay Recovery**

The overall flow is:

``` text
Detect revenue risk
        ↓
Validate data
        ↓
Decision Engine
        ↓
Safety / stopping rules
        ↓
Recovery action
        ↓
Verify outcome
        ↓
SQLite audit trail
        ↓
Report + Dashboard
```

The core financial decisions are deterministic and explainable. An LLM
is intentionally not used to decide whether money should be retried or
collected.

------------------------------------------------------------------------

# Architecture

``` text
                 Revenue at Risk
                       |
       +---------------+---------------+
       |               |               |
 Failed Payment   Checkout Drop-off   B2B Invoice
       |               |             Overdue
       +---------------+---------------+
                       |
                 Promise-to-Pay
                       |
                       v
                Decision Engine
                       |
                       v
                    Processor
                  /     |      \
                 v      v       v
            Razorpay  Reminder  Escalation
            TEST MODE
                 |
                 v
          Payment Verification
                 |
                 v
            SQLite Audit DB
                 |
          +------+------+
          |             |
          v             v
       Reporter      Dashboard
          |             |
          v             v
   output/report.md   Browser
```

### Dashboard architecture

``` text
SQLite Audit DB
      ↓
dashboard/server.py
      ↓
GET /api/dashboard
      ↓
dashboard/index.html
      ↓
Browser
```

The dashboard is read-only and contains no recovery business logic.

------------------------------------------------------------------------

# Project Structure

``` text
failed-payment-recovery-agent/
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
├── dashboard/
│   ├── index.html
│   └── server.py
├── data/
│   ├── failed_payments.json
│   └── failed_payments.csv
├── database/
│   └── audit.db
├── logs/
│   └── razorpay_api.log
├── output/
│   └── report.md
├── tests/
│   ├── test_audit_logger.py
│   ├── test_decision_engine.py
│   ├── test_processor.py
│   └── test_reporter.py
├── .env
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
└── run.py
```

Runtime files such as `.env`, `audit.db`, generated data, reports, logs,
and `venv/` should not be committed.

------------------------------------------------------------------------

# Feature 1 --- Failed Payment Recovery

Synthetic failed-payment records contain:

``` text
payment_id
customer_id
customer_name
email
phone
amount
currency
failure_reason
attempt_count
payment_type
last_attempt_at
```

Supported failure reasons:

``` text
insufficient_funds
card_expired
bank_timeout
otp_failed
fraud_block
mandate_failed
```

## Decision Rules

  -----------------------------------------------------------------------
  Failure Reason          Action                  Logic
  ----------------------- ----------------------- -----------------------
  `insufficient_funds`    `RETRY_LATER`           Retry after 6 hours

  `card_expired`          `SEND_NEW_LINK`         Customer needs a new
                                                  payment link

  `bank_timeout`          `RETRY_NOW`             Controlled retry for
                                                  temporary failure

  `otp_failed`            `SEND_REMINDER`         Customer can retry

  `fraud_block`           `ESCALATE_HUMAN`        Never automatically
                                                  retry

  `mandate_failed` +      `ESCALATE_HUMAN`        Human intervention
  subscription                                    

  `mandate_failed` +      `SEND_NEW_LINK`         Create a new payment
  one-time                                        link
  -----------------------------------------------------------------------

### Global stopping rule

``` text
attempt_count >= 3
        ↓
DO_NOT_RETRY
```

The stopping rule overrides the normal failure-reason decision.

------------------------------------------------------------------------

# Safety Controls

## Retry limit

No payment is automatically retried beyond three total attempts.

## Retry cooldown

If the previous attempt happened less than 10 minutes ago:

``` text
DO_NOT_RETRY
```

This prevents repeated attempts too close together.

## Fraud protection

``` text
fraud_block
     ↓
ESCALATE_HUMAN
```

There are no automatic retries for fraud-blocked payments.

## API safety cap

``` env
MAX_REAL_API_CALLS=20
```

The system can analyze the entire batch, but real external API actions
are bounded.

Actions beyond the cap are not sent to Razorpay and are not counted as
real recovery.

------------------------------------------------------------------------

# Feature 2 --- Razorpay TEST MODE Integration

The project integrates with Razorpay TEST MODE for eligible Payment Link
actions.

Credentials are loaded from environment variables:

``` env
RAZORPAY_KEY_ID=rzp_test_xxxx
RAZORPAY_KEY_SECRET=xxxx
MAX_REAL_API_CALLS=20
```

Eligible Payment Link creation uses information such as:

``` text
amount
currency
customer name
customer email
customer phone
reference_id
```

Razorpay requests and responses are logged to:

``` text
logs/razorpay_api.log
```

Secrets are not written into the API logs.

------------------------------------------------------------------------

# Confirmed Revenue Verification

A Payment Link being created is **not** considered recovered revenue.

The workflow is:

``` text
Create Payment Link
        ↓
Payment Link exists
        ↓
Check payment status
        ↓
Customer actually paid?
       /      YES  NO
      |    |
      v    v
 Confirm  Awaiting
 Revenue  Payment
```

Recovery is confirmed only when:

``` text
status == "paid"
```

and:

``` text
amount_paid > 0
```

Therefore:

``` text
API success != Payment success
```

Example:

``` text
status = created
amount_paid = ₹0

→ Payment Link created
→ Revenue NOT recovered
```

If:

``` text
status = paid
amount_paid = ₹999
```

then:

``` text
→ Confirmed recovered revenue = ₹999
```

This prevents inflated recovery metrics.

------------------------------------------------------------------------

# Feature 3 --- Checkout Drop-off Recovery

Revenue can be lost before a payment failure occurs.

Example:

``` text
Customer starts checkout
        ↓
Adds product
        ↓
Leaves checkout
        ↓
No payment
```

The project models these sessions using:

``` text
checkout_id
customer_id
amount
currency
started_at
completed
completed_at
```

## Checkout rules

``` text
Checkout completed
        ↓
NO_ACTION
```

``` text
Checkout age < 30 minutes
        ↓
WAIT
```

``` text
Checkout abandoned and old enough
        ↓
SEND_CHECKOUT_REMINDER
```

Customer-return behavior is simulated because the project does not have
a production checkout event stream.

The dashboard therefore separates:

``` text
Simulated Checkout Recovery
```

from:

``` text
Confirmed Checkout Revenue
```

A simulated return is never treated as real recovered revenue.

------------------------------------------------------------------------

# Feature 4 --- B2B Receivables Recovery

The project also covers overdue B2B invoices.

A receivable contains:

``` text
invoice_id
company_name
customer_id
amount
currency
due_date
days_overdue
payment_status
previous_reminders
promised_payment_date
paid_at
```

## B2B recovery rules

  Days Overdue   Action
  -------------- --------------------------
  `1–7`          `SEND_REMINDER`
  `8–15`         `SEND_STRONGER_REMINDER`
  `16–30`        `ESCALATE_ACCOUNT`
  `>30`          `ESCALATE_HUMAN`

Additional cases:

``` text
Already paid → NO_ACTION
Not overdue → WAIT
```

The B2B workflow is currently simulated and does not automatically move
money.

Important:

``` text
Reminder ≠ Revenue Recovered
Escalation ≠ Revenue Recovered
```

Actual B2B recovery requires payment evidence.

------------------------------------------------------------------------

# Feature 5 --- Promise-to-Pay Recovery

A customer may say:

> "I will pay on Friday."

That is a promise, not a payment.

The project tracks:

``` text
promise_id
customer_id
customer_name
amount
currency
promised_date
created_at
status
previous_missed_promises
contact_channel
paid_at
```

## PTP rules

``` text
Promise upcoming
        ↓
WAIT / NO_ACTION
```

``` text
Promise due today
        ↓
SEND_PAYMENT_REMINDER
```

``` text
1–3 days overdue
        ↓
SEND_STRONGER_REMINDER
```

``` text
4–7 days overdue
        ↓
ESCALATE_ACCOUNT
```

``` text
More than 7 days overdue
        ↓
ESCALATE_HUMAN
```

Already-paid promises result in:

``` text
NO_ACTION
```

The system never treats the promise itself as recovered revenue.

------------------------------------------------------------------------

# Feature 6 --- Hinglish Recovery Messages

The communication layer can use deterministic Hinglish templates without
requiring an external AI API.

Example:

``` text
Aapka payment complete nahi ho paya.
Please ek baar dobara try karein.
Agar issue continue ho, hum aapki help karenge.
```

Another example:

``` text
Aapka bank response nahi de raha tha.
Aap thodi der baad payment dobara try kar sakte hain.
```

The communication flow is:

``` text
Recovery Decision
       ↓
Recovery Action
       ↓
Customer Message
       ↓
Hinglish Template
```

The core financial decision remains deterministic and explainable.

------------------------------------------------------------------------

# SQLite Audit Trail

All recovery workflows write to:

``` text
database/audit.db
```

The audit trail can record:

``` text
timestamp
record_type
payment_id
checkout_id
invoice_id
promise_id
customer_id
customer_name
company_name
amount
currency
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

This makes every decision traceable.

For a record we can answer:

``` text
Why was this action selected?
What action was taken?
Did the external API accept it?
Did the customer actually pay?
How much was actually recovered?
```

------------------------------------------------------------------------

# Reporting

`app/reporter.py` generates:

``` text
output/report.md
```

The report includes:

-   Executive summary
-   Recovery classification
-   Failure-reason breakdown
-   Safety exceptions
-   Processing outcomes
-   Test-mode limitations
-   Stopping rules
-   Audit trail
-   Checkout recovery
-   B2B recovery
-   Promise-to-Pay recovery

Real recovery, simulated recovery, triggered actions, and outstanding
revenue remain separate.

------------------------------------------------------------------------

# Dashboard

The dashboard consists of:

``` text
dashboard/index.html
dashboard/server.py
```

Start it with:

``` bash
python dashboard/server.py
```

Open:

``` text
http://127.0.0.1:5000
```

The dashboard reads live audit data through:

``` text
GET /api/dashboard
```

## Dashboard sections

### Revenue Overview

-   Total Revenue at Risk
-   Confirmed Revenue Recovered
-   Payment Recovery Rate
-   Real API Actions

### System Overview

-   Failed Payments
-   Checkout Sessions
-   B2B Invoices
-   Promises to Pay

### Checkout Drop-off

-   Value Observed
-   Completed
-   Reminders
-   Customers Returned
-   Simulated Recovery
-   Still Abandoned
-   Confirmed Checkout Revenue

### B2B Receivables

-   Invoices
-   Amount at Risk
-   Standard Reminders
-   Stronger Reminders
-   Account Escalations
-   Human Escalations
-   Still Outstanding
-   Confirmed B2B Revenue

### Promise-to-Pay

-   Promises Tracked
-   Amount at Risk
-   Payment Reminders
-   Stronger Reminders
-   Account Escalations
-   Human Escalations
-   Waiting / Upcoming
-   Already Paid
-   Still Outstanding
-   Confirmed PTP Revenue

### Payment Decisions

Shows decisions such as:

``` text
DO_NOT_RETRY
SEND_NEW_LINK
ESCALATE_HUMAN
RETRY_NOW
RETRY_LATER
SEND_REMINDER
```

### Failure Reasons

Shows:

``` text
card_expired
bank_timeout
fraud_block
mandate_failed
insufficient_funds
otp_failed
```

### Safety Exceptions

Shows payments affected by stopping rules and human escalation.

### Audit Trail

Shows recent records across:

``` text
PAYMENT
CHECKOUT
B2B
PTP
```

including decision, action, outcome, recovery type, API status, and
notes.

------------------------------------------------------------------------

# Recovery Metrics

The project deliberately separates outcomes.

  -----------------------------------------------------------------------
  Metric                              Meaning
  ----------------------------------- -----------------------------------
  **Confirmed Revenue**               Actual payment confirmed

  **Recovery Action**                 Recovery action executed but
                                      payment not yet confirmed

  **Simulated Recovery**              Synthetic behavior, not real
                                      revenue

  **Still Outstanding**               Revenue remains unpaid

  **Escalated**                       Human/account intervention required
  -----------------------------------------------------------------------

The headline recovery metric is based on confirmed payment revenue.

The system does not treat:

``` text
Payment Link created = Revenue recovered
Reminder sent = Revenue recovered
Promise made = Revenue recovered
```

------------------------------------------------------------------------

# Complete Pipeline

Run:

``` bash
python run.py
```

The pipeline:

``` text
Generate / load synthetic data
        ↓
Validate datasets
        ↓
Initialize SQLite
        ↓
Process failed payments
        ↓
Process checkout sessions
        ↓
Process B2B receivables
        ↓
Process Promise-to-Pay records
        ↓
Apply decision rules
        ↓
Execute eligible Razorpay TEST MODE actions
        ↓
Verify payment status
        ↓
Write audit records
        ↓
Verify audit coverage
        ↓
Generate report
        ↓
Display metrics
```

------------------------------------------------------------------------

# Getting Started

## 1. Create a virtual environment

``` bash
python -m venv venv
```

Windows:

``` powershell
venv\Scriptsctivate
```

Linux/macOS:

``` bash
source venv/bin/activate
```

## 2. Install dependencies

``` bash
pip install -r requirements.txt
```

Current dependencies:

``` text
requests
python-dotenv
pytest
```

## 3. Configure Razorpay TEST MODE

Copy:

``` text
.env.example
```

to:

``` text
.env
```

Windows PowerShell:

``` powershell
Copy-Item .env.example .env
```

Add:

``` env
RAZORPAY_KEY_ID=rzp_test_xxxx
RAZORPAY_KEY_SECRET=xxxx
MAX_REAL_API_CALLS=20
```

Never commit `.env`.

## 4. Run the complete recovery agent

``` bash
python run.py
```

## 5. Start the dashboard

``` bash
python dashboard/server.py
```

Open:

``` text
http://127.0.0.1:5000
```

Do not open `dashboard/index.html` directly with `file://`.

------------------------------------------------------------------------

# Testing

Run:

``` bash
python -m pytest tests -v
```

The test suite covers:

-   Decision rules
-   Retry limits
-   Fraud escalation
-   OTP handling
-   Mandate handling
-   Maximum-attempt stopping rule
-   Retry cooldown
-   Payment Link API cap
-   Razorpay API error handling
-   Settlement tracking
-   Unpaid Payment Links
-   Paid Payment Links
-   Audit logging
-   Real vs simulated separation
-   Recovery reporting
-   Dashboard-independent backend behavior

Current test suite:

``` text
34 automated tests
```

------------------------------------------------------------------------

# Example End-to-End Payment Flow

Example:

``` text
Payment ID: pay_test_0003
Failure: mandate_failed
Type: one-time
Amount: ₹3,999
```

Decision:

``` text
SEND_NEW_LINK
```

Processor creates a Razorpay TEST MODE Payment Link.

If the response is:

``` text
status = created
amount_paid = ₹0
```

the system records:

``` text
Action:
PAYMENT_LINK_CREATED

Outcome:
awaiting_payment

Recovery:
NOT CONFIRMED
```

If the customer later pays and Razorpay reports:

``` text
status = paid
amount_paid = ₹3,999
```

then:

``` text
Outcome:
confirmed_settlement

Recovery type:
real

Confirmed recovered revenue:
₹3,999
```

------------------------------------------------------------------------

# Example B2B Flow

``` text
Invoice amount: ₹75,000
Days overdue: 20
```

Decision:

``` text
ESCALATE_ACCOUNT
```

The escalation is recorded, but:

``` text
₹75,000 recovered
```

is not claimed until actual payment evidence exists.

------------------------------------------------------------------------

# Example Promise-to-Pay Flow

``` text
Promise amount: ₹25,000
Promised date: 3 days ago
```

Decision:

``` text
SEND_STRONGER_REMINDER
```

The promise is tracked but not counted as recovered revenue.

Actual payment confirmation is required.

------------------------------------------------------------------------

# Design Principles

### 1. Explainable recovery decisions

Financial recovery decisions use explicit rules.

This makes them:

-   Predictable
-   Testable
-   Explainable
-   Auditable

### 2. Confirm before counting revenue

``` text
API success != Payment success
```

### 3. Bounded automation

The agent uses:

-   Retry limits
-   Cooldown protection
-   Fraud protection
-   API caps
-   Human escalation
-   Simulation separation

### 4. Honest reporting

Real, simulated, triggered, outstanding, and confirmed outcomes remain
separate.

### 5. Auditability

Every processed record produces an audit entry.

### 6. Dashboard independence

The backend can run and be tested without the dashboard.

------------------------------------------------------------------------

# Limitations

-   Razorpay integration uses TEST MODE only.
-   No real customer payments are processed.
-   Synthetic data does not represent real customer data.
-   Creating a Payment Link does not guarantee payment.
-   Confirmed recovery requires actual payment confirmation.
-   Checkout customer-return behavior is simulated.
-   B2B actions are currently simulated reminders/escalations.
-   Promise-to-Pay actions are currently simulated.
-   `RETRY_LATER` represents a recovery decision; production scheduling
    would require a persistent scheduler.
-   Dashboard analytics currently focus on the current audit dataset.
-   Hinglish messaging can use deterministic templates; an external LLM
    is not required for the core financial decision engine.

------------------------------------------------------------------------

# Future Improvements

Potential extensions:

-   Persistent retry scheduler
-   Real checkout event integration
-   Customer notification integrations
-   WhatsApp / SMS / email delivery
-   Hinglish message personalization
-   Historical recovery analytics
-   Recovery trend dashboards
-   Production payment-provider abstraction
-   Multi-provider support
-   PostgreSQL
-   Authentication and role-based dashboard access
-   Customer-level recovery prioritization

------------------------------------------------------------------------

# Security

-   Never commit `.env`.
-   Use Razorpay TEST MODE credentials.
-   Never hardcode API secrets.
-   Do not expose secrets in logs.
-   Keep `venv/` out of version control.
-   Keep generated databases, reports, and logs out of Git.
-   Keep real external API actions bounded.

------------------------------------------------------------------------

# Why This Project

The goal is not to perform more recovery actions.

The goal is to **recover more revenue safely while knowing exactly what
happened**.

The system therefore asks:

``` text
What revenue is at risk?
Why is it at risk?
What should we do?
When should we stop?
Did the action work?
Did the customer actually pay?
How much revenue was actually recovered?
Can we prove it afterward?
```

That is the core of the Revenue Recovery Agent.
