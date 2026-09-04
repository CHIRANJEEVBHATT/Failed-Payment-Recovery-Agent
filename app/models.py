from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------
# Failed Payment Model
# ---------------------------------------------------------

@dataclass
class FailedPayment:
    """
    Represents one failed payment record.
    """

    payment_id: str
    customer_name: str
    email: str
    phone: str
    amount: float
    failure_reason: str
    attempt_count: int
    payment_type: str
    last_attempt_at: str


# ---------------------------------------------------------
# Checkout Session Model
# ---------------------------------------------------------

@dataclass
class CheckoutSession:
    """
    Represents a customer checkout session.

    A checkout that was started but not completed can
    represent revenue at risk.
    """

    checkout_id: str
    customer_id: str
    amount: float
    currency: str
    started_at: datetime

    completed: bool = False
    completed_at: Optional[datetime] = None