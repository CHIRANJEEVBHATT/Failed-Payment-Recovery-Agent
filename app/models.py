from dataclasses import dataclass
from typing import Optional


@dataclass
class FailedPayment:
    """
    Represents one failed payment that enters the recovery
    agent.

    The model intentionally contains only the information
    required by the current project requirements.
    """

    payment_id: str
    customer_name: str
    email: str
    phone: str
    amount: float
    failure_reason: str
    attempt_count: int
    payment_type: str
    last_attempt_at: Optional[str] = None