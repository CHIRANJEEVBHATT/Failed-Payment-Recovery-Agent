from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# =========================================================
# Failed Payment
# =========================================================

@dataclass
class FailedPayment:
    payment_id: str
    customer_name: str
    email: str
    phone: str
    amount: float
    failure_reason: str
    attempt_count: int
    payment_type: str
    last_attempt_at: Optional[str] = None


# =========================================================
# Checkout Drop-off
# =========================================================

@dataclass
class CheckoutSession:
    checkout_id: str
    customer_id: str
    amount: float
    currency: str
    started_at: datetime
    completed: bool = False
    completed_at: Optional[datetime] = None


# =========================================================
# B2B Receivable
# =========================================================

@dataclass
class B2BReceivable:
    invoice_id: str
    company_name: str
    customer_id: str
    amount: float
    currency: str
    due_date: datetime
    days_overdue: int
    payment_status: str = "overdue"
    previous_reminders: int = 0
    promised_payment_date: Optional[datetime] = None
    paid_at: Optional[datetime] = None


# =========================================================
# Promise-to-Pay
# =========================================================

@dataclass
class PromiseToPay:
    """
    Represents a customer's explicit promise to pay.

    IMPORTANT:
        A promise is NOT a payment.

        This model tracks the promised payment date and
        follow-up state. Actual revenue recovery must only
        be confirmed when a real payment is observed.
    """

    promise_id: str
    customer_id: str
    customer_name: str
    amount: float
    currency: str
    promised_date: datetime
    created_at: datetime
    status: str = "promised"
    previous_missed_promises: int = 0
    contact_channel: str = "email"
    paid_at: Optional[datetime] = None