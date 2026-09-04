from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from app.models import FailedPayment


# ---------------------------------------------------------
# Action constants
# ---------------------------------------------------------

RETRY_NOW = "RETRY_NOW"
RETRY_LATER = "RETRY_LATER"
SEND_NEW_LINK = "SEND_NEW_LINK"
SEND_REMINDER = "SEND_REMINDER"
ESCALATE_HUMAN = "ESCALATE_HUMAN"
DO_NOT_RETRY = "DO_NOT_RETRY"


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

RETRY_COOLDOWN_MINUTES = 10


# ---------------------------------------------------------
# Decision result
# ---------------------------------------------------------

@dataclass
class RecoveryDecision:
    action: str
    reason: str
    delay_hours: Optional[int] = None


# ---------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------

def _parse_timestamp(
    timestamp: Optional[str],
) -> Optional[datetime]:
    """
    Convert an ISO timestamp into datetime.
    """

    if not timestamp:
        return None

    try:
        return datetime.fromisoformat(
            timestamp
        )
    except ValueError:
        return None


# ---------------------------------------------------------
# Retry cooldown
# ---------------------------------------------------------

def retry_is_within_cooldown(
    last_attempt_at: Optional[str],
) -> bool:
    """
    Return True if the payment was attempted within
    the last 10 minutes.
    """

    last_attempt = _parse_timestamp(
        last_attempt_at
    )

    if last_attempt is None:
        return False

    elapsed = (
        datetime.now() - last_attempt
    )

    return elapsed < timedelta(
        minutes=RETRY_COOLDOWN_MINUTES
    )


# ---------------------------------------------------------
# Main decision engine
# ---------------------------------------------------------
def decide_checkout_recovery(session):
    """
    Decide whether an abandoned checkout should receive
    a recovery reminder.
    """

    if session.completed:
        return {
            "action": "NO_ACTION",
            "reason": "CHECKOUT_COMPLETED",
        }

    age_minutes = (
        datetime.now() - session.started_at
    ).total_seconds() / 60

    # Ignore extremely recent checkouts.
    if age_minutes < 30:
        return {
            "action": "WAIT",
            "reason": "CHECKOUT_TOO_RECENT",
        }

    # Recovery reminder for abandoned checkout.
    return {
        "action": "SEND_CHECKOUT_REMINDER",
        "reason": "CHECKOUT_DROPPED_OFF",
    }
def decide(
    payment: FailedPayment,
) -> RecoveryDecision:
    """
    Decide the recovery action for one failed payment.

    Safety rules are evaluated before recovery rules.
    """

    # -----------------------------------------------------
    # Rule 1: Hard cap
    # -----------------------------------------------------

    if payment.attempt_count >= 3:
        return RecoveryDecision(
            action=DO_NOT_RETRY,
            reason=(
                "Payment has reached the hard maximum "
                "of 3 attempts. No further automatic "
                "recovery action is allowed."
            ),
        )

    # -----------------------------------------------------
    # Rule 2: Fraud
    # -----------------------------------------------------

    if payment.failure_reason == "fraud_block":
        return RecoveryDecision(
            action=ESCALATE_HUMAN,
            reason=(
                "Payment was blocked for fraud risk. "
                "Fraud-flagged payments are never "
                "automatically retried."
            ),
        )

    # -----------------------------------------------------
    # Rule 3: Ten-minute cooldown
    # -----------------------------------------------------

    if retry_is_within_cooldown(
        payment.last_attempt_at
    ):
        return RecoveryDecision(
            action=DO_NOT_RETRY,
            reason=(
                "The same payment was attempted within "
                "the last 10 minutes. Automatic retry is "
                "blocked to avoid duplicate-charge risk."
            ),
        )

    # -----------------------------------------------------
    # Rule 4: Insufficient funds
    # -----------------------------------------------------

    if payment.failure_reason == "insufficient_funds":
        return RecoveryDecision(
            action=RETRY_LATER,
            reason=(
                "Insufficient funds may be temporary. "
                "Retry after 6 hours, subject to the "
                "maximum attempt limit."
            ),
            delay_hours=6,
        )

    # -----------------------------------------------------
    # Rule 5: Card expired
    # -----------------------------------------------------

    if payment.failure_reason == "card_expired":
        return RecoveryDecision(
            action=SEND_NEW_LINK,
            reason=(
                "The card has expired. A new payment link "
                "should be sent instead of retrying the "
                "same payment method."
            ),
        )

    # -----------------------------------------------------
    # Rule 6: Bank timeout
    # -----------------------------------------------------

    if payment.failure_reason == "bank_timeout":
        return RecoveryDecision(
            action=RETRY_NOW,
            reason=(
                "The bank timed out without indicating a "
                "permanent failure. One immediate retry "
                "is allowed."
            ),
        )

    # -----------------------------------------------------
    # Rule 7: OTP failure
    # -----------------------------------------------------

    if payment.failure_reason == "otp_failed":
        return RecoveryDecision(
            action=SEND_REMINDER,
            reason=(
                "OTP authentication was not completed. "
                "Send a customer reminder instead of "
                "silently retrying."
            ),
        )

    # -----------------------------------------------------
    # Rule 8: Mandate failure
    # -----------------------------------------------------

    if payment.failure_reason == "mandate_failed":

        if payment.payment_type == "subscription":
            return RecoveryDecision(
                action=ESCALATE_HUMAN,
                reason=(
                    "A subscription mandate failed. "
                    "Subscription mandate failures require "
                    "human review."
                ),
            )

        return RecoveryDecision(
            action=SEND_NEW_LINK,
            reason=(
                "A one-time payment mandate failed. "
                "Send a new payment link instead of "
                "automatically retrying."
            ),
        )

    # -----------------------------------------------------
    # Unknown reason
    # -----------------------------------------------------

    return RecoveryDecision(
        action=ESCALATE_HUMAN,
        reason=(
            "The failure reason is not recognized. "
            "Human review is required."
        ),
    )


# ---------------------------------------------------------
# Direct execution test
# ---------------------------------------------------------

if __name__ == "__main__":
    test_payment = FailedPayment(
        payment_id="decision_test_001",
        customer_name="Test Customer",
        email="test@example.com",
        phone="9876543210",
        amount=1000.00,
        failure_reason="insufficient_funds",
        attempt_count=1,

        payment_type="one-time",

        # 30 minutes ago.
        # This is deliberately outside the 10-minute
        # cooldown so the insufficient-funds rule can
        # be demonstrated.
        last_attempt_at=(
            datetime.now()
            - timedelta(minutes=30)
        ).isoformat(
            timespec="seconds"
        ),
    )

    decision = decide(
        test_payment
    )

    print("=" * 60)
    print("DECISION ENGINE TEST")
    print("=" * 60)

    print(
        "Payment:",
        test_payment.payment_id,
    )

    print(
        "Failure:",
        test_payment.failure_reason,
    )

    print(
        "Decision:",
        decision.action,
    )

    print(
        "Reason:",
        decision.reason,
    )

    print(
        "Delay hours:",
        decision.delay_hours,
    )

    print("=" * 60)