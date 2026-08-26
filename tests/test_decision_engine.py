from datetime import datetime, timedelta

from app.decision_engine import (
    DO_NOT_RETRY,
    ESCALATE_HUMAN,
    RETRY_LATER,
    RETRY_NOW,
    SEND_NEW_LINK,
    SEND_REMINDER,
    decide,
)
from app.models import FailedPayment


def make_payment(
    failure_reason: str,
    attempt_count: int = 1,
    payment_type: str = "one-time",
    last_attempt_at: str | None = None,
) -> FailedPayment:
    """
    Create a small synthetic payment specifically for testing
    the decision engine.
    """

    if last_attempt_at is None:
        last_attempt_at = (
            datetime.now()
            - timedelta(minutes=30)
        ).isoformat(timespec="seconds")

    return FailedPayment(
        payment_id="test_payment_001",
        customer_name="Test Customer",
        email="test@example.com",
        phone="9876543210",
        amount=1000.00,
        failure_reason=failure_reason,
        attempt_count=attempt_count,
        payment_type=payment_type,
        last_attempt_at=last_attempt_at,
    )


# ---------------------------------------------------------
# insufficient_funds
# ---------------------------------------------------------

def test_insufficient_funds_returns_retry_later():
    payment = make_payment(
        failure_reason="insufficient_funds",
        attempt_count=1,
    )

    result = decide(payment)

    assert result.action == RETRY_LATER
    assert result.delay_hours == 6


def test_insufficient_funds_after_two_retries_stops():
    payment = make_payment(
        failure_reason="insufficient_funds",
        attempt_count=3,
    )

    result = decide(payment)

    assert result.action == DO_NOT_RETRY


# ---------------------------------------------------------
# card_expired
# ---------------------------------------------------------

def test_card_expired_sends_new_link():
    payment = make_payment(
        failure_reason="card_expired",
        attempt_count=1,
    )

    result = decide(payment)

    assert result.action == SEND_NEW_LINK


# ---------------------------------------------------------
# bank_timeout
# ---------------------------------------------------------

def test_bank_timeout_retries_now():
    payment = make_payment(
        failure_reason="bank_timeout",
        attempt_count=1,
    )

    result = decide(payment)

    assert result.action == RETRY_NOW


def test_bank_timeout_after_max_attempts_stops():
    payment = make_payment(
        failure_reason="bank_timeout",
        attempt_count=3,
    )

    result = decide(payment)

    assert result.action == DO_NOT_RETRY


# ---------------------------------------------------------
# OTP failure
# ---------------------------------------------------------

def test_otp_failed_sends_reminder():
    payment = make_payment(
        failure_reason="otp_failed",
        attempt_count=1,
    )

    result = decide(payment)

    assert result.action == SEND_REMINDER


# ---------------------------------------------------------
# Fraud block
# ---------------------------------------------------------

def test_fraud_block_escalates():
    payment = make_payment(
        failure_reason="fraud_block",
        attempt_count=1,
    )

    result = decide(payment)

    assert result.action == ESCALATE_HUMAN


def test_fraud_block_never_retries():
    payment = make_payment(
        failure_reason="fraud_block",
        attempt_count=2,
    )

    result = decide(payment)

    assert result.action == ESCALATE_HUMAN


# ---------------------------------------------------------
# Mandate failure
# ---------------------------------------------------------

def test_subscription_mandate_failure_escalates():
    payment = make_payment(
        failure_reason="mandate_failed",
        payment_type="subscription",
        attempt_count=1,
    )

    result = decide(payment)

    assert result.action == ESCALATE_HUMAN


def test_one_time_mandate_failure_sends_new_link():
    payment = make_payment(
        failure_reason="mandate_failed",
        payment_type="one-time",
        attempt_count=1,
    )

    result = decide(payment)

    assert result.action == SEND_NEW_LINK


# ---------------------------------------------------------
# Hard attempt cap
# ---------------------------------------------------------

def test_any_payment_with_three_attempts_cannot_retry():
    reasons = [
        "insufficient_funds",
        "card_expired",
        "bank_timeout",
        "otp_failed",
        "mandate_failed",
    ]

    for reason in reasons:
        payment = make_payment(
            failure_reason=reason,
            attempt_count=3,
        )

        result = decide(payment)

        assert result.action == DO_NOT_RETRY


# ---------------------------------------------------------
# Ten-minute cooldown
# ---------------------------------------------------------

def test_recent_retry_is_blocked():
    recent_timestamp = (
        datetime.now()
        - timedelta(minutes=5)
    ).isoformat(timespec="seconds")

    payment = make_payment(
        failure_reason="bank_timeout",
        attempt_count=1,
        last_attempt_at=recent_timestamp,
    )

    result = decide(payment)

    assert result.action == DO_NOT_RETRY


def test_retry_after_ten_minutes_is_allowed():
    old_timestamp = (
        datetime.now()
        - timedelta(minutes=20)
    ).isoformat(timespec="seconds")

    payment = make_payment(
        failure_reason="bank_timeout",
        attempt_count=1,
        last_attempt_at=old_timestamp,
    )

    result = decide(payment)

    assert result.action == RETRY_NOW