from dataclasses import dataclass
from datetime import datetime

from app.models import (
    B2BReceivable,
    CheckoutSession,
    FailedPayment,
    PromiseToPay,
)


# ============================================================
# PAYMENT RECOVERY CONSTANTS
# ============================================================

RETRY_NOW = "RETRY_NOW"
RETRY_LATER = "RETRY_LATER"
SEND_NEW_LINK = "SEND_NEW_LINK"
SEND_REMINDER = "SEND_REMINDER"
ESCALATE_HUMAN = "ESCALATE_HUMAN"
DO_NOT_RETRY = "DO_NOT_RETRY"


# ============================================================
# CHECKOUT RECOVERY CONSTANTS
# ============================================================

NO_ACTION = "NO_ACTION"
WAIT = "WAIT"
SEND_CHECKOUT_REMINDER = "SEND_CHECKOUT_REMINDER"


# ============================================================
# B2B RECOVERY CONSTANTS
# ============================================================

SEND_B2B_REMINDER = "SEND_REMINDER"
SEND_B2B_STRONGER_REMINDER = "SEND_STRONGER_REMINDER"
ESCALATE_ACCOUNT = "ESCALATE_ACCOUNT"
ESCALATE_B2B_HUMAN = "ESCALATE_HUMAN"


# ============================================================
# PROMISE-TO-PAY CONSTANTS
# ============================================================

PTP_WAIT = "WAIT"
PTP_NO_ACTION = "NO_ACTION"
PTP_PAYMENT_REMINDER = "SEND_PAYMENT_REMINDER"
PTP_STRONGER_REMINDER = "SEND_STRONGER_REMINDER"
PTP_ESCALATE_ACCOUNT = "ESCALATE_ACCOUNT"
PTP_ESCALATE_HUMAN = "ESCALATE_HUMAN"


# ============================================================
# PAYMENT DECISION
# ============================================================

@dataclass
class RecoveryDecision:
    action: str
    reason: str
    delay_hours: int = 0


def decide(payment: FailedPayment) -> RecoveryDecision:
    """
    Decide the safest recovery action for a failed payment.

    Rules:
    - 3 or more attempts -> never retry
    - Retry within 10 minutes -> stop
    - Fraud block -> human escalation
    - Insufficient funds -> retry later
    - Expired card -> send new payment link
    - Bank timeout -> retry now
    - OTP failure -> send reminder
    - Mandate failure:
        subscription -> human escalation
        one-time -> new payment link
    """

    # --------------------------------------------------------
    # GLOBAL HARD STOP
    # --------------------------------------------------------

    if payment.attempt_count >= 3:
        return RecoveryDecision(
            action=DO_NOT_RETRY,
            reason="MAX_RETRY_ATTEMPTS_REACHED",
        )

    # --------------------------------------------------------
    # COOLDOWN SAFETY RULE
    # --------------------------------------------------------

    if payment.last_attempt_at is not None:

        last_attempt = payment.last_attempt_at

        # JSON data / tests may provide timestamp as a string
        if isinstance(last_attempt, str):
            last_attempt = datetime.fromisoformat(last_attempt)

        elapsed_minutes = (
            datetime.now() - last_attempt
        ).total_seconds() / 60

        if elapsed_minutes < 10:
            return RecoveryDecision(
                action=DO_NOT_RETRY,
                reason="RETRY_COOLDOWN_ACTIVE",
            )

    # --------------------------------------------------------
    # FRAUD
    # --------------------------------------------------------

    if payment.failure_reason == "fraud_block":
        return RecoveryDecision(
            action=ESCALATE_HUMAN,
            reason="FRAUD_BLOCK_REQUIRES_HUMAN_REVIEW",
        )

    # --------------------------------------------------------
    # INSUFFICIENT FUNDS
    # --------------------------------------------------------

    if payment.failure_reason == "insufficient_funds":

        if payment.attempt_count >= 2:
            return RecoveryDecision(
                action=DO_NOT_RETRY,
                reason="INSUFFICIENT_FUNDS_RETRY_LIMIT_REACHED",
            )

        return RecoveryDecision(
            action=RETRY_LATER,
            reason="INSUFFICIENT_FUNDS_TEMPORARY_FAILURE",
            delay_hours=6,
        )

    # --------------------------------------------------------
    # EXPIRED CARD
    # --------------------------------------------------------

    if payment.failure_reason == "card_expired":
        return RecoveryDecision(
            action=SEND_NEW_LINK,
            reason="CARD_EXPIRED_REQUIRES_UPDATED_PAYMENT_METHOD",
        )

    # --------------------------------------------------------
    # BANK TIMEOUT
    # --------------------------------------------------------

    if payment.failure_reason == "bank_timeout":

        if payment.attempt_count >= 2:
            return RecoveryDecision(
                action=DO_NOT_RETRY,
                reason="BANK_TIMEOUT_RETRY_LIMIT_REACHED",
            )

        return RecoveryDecision(
            action=RETRY_NOW,
            reason="BANK_TIMEOUT_MAY_BE_TRANSIENT",
        )

    # --------------------------------------------------------
    # OTP FAILURE
    # --------------------------------------------------------

    if payment.failure_reason == "otp_failed":
        return RecoveryDecision(
            action=SEND_REMINDER,
            reason="OTP_FAILURE_REQUIRES_CUSTOMER_REATTEMPT",
        )

    # --------------------------------------------------------
    # MANDATE FAILURE
    # --------------------------------------------------------

    if payment.failure_reason == "mandate_failed":

        if payment.payment_type == "subscription":
            return RecoveryDecision(
                action=ESCALATE_HUMAN,
                reason="SUBSCRIPTION_MANDATE_FAILURE_REQUIRES_REVIEW",
            )

        return RecoveryDecision(
            action=SEND_NEW_LINK,
            reason="ONE_TIME_MANDATE_FAILURE_REQUIRES_NEW_PAYMENT_FLOW",
        )

    # --------------------------------------------------------
    # UNKNOWN FAILURE
    # --------------------------------------------------------

    return RecoveryDecision(
        action=ESCALATE_HUMAN,
        reason="UNKNOWN_FAILURE_REASON_REQUIRES_REVIEW",
    )


# ============================================================
# CHECKOUT DROP-OFF DECISION
# ============================================================

@dataclass
class CheckoutRecoveryDecision:
    action: str
    reason: str

    def __getitem__(self, key):
        if key == "action":
            return self.action
        if key == "reason":
            return self.reason
        raise KeyError(key)


def decide_checkout_recovery(
    session: CheckoutSession,
) -> CheckoutRecoveryDecision:
    """
    Decide what to do with an abandoned checkout.

    Rules:
    - Completed checkout -> no action
    - Less than 30 minutes old -> wait
    - Older abandoned checkout -> send reminder
    """

    # --------------------------------------------------------
    # ALREADY COMPLETED
    # --------------------------------------------------------

    if session.completed:
        return CheckoutRecoveryDecision(
            action=NO_ACTION,
            reason="CHECKOUT_COMPLETED",
        )

    # --------------------------------------------------------
    # CALCULATE CHECKOUT AGE
    # --------------------------------------------------------

    started_at = session.started_at

    # Support JSON/test data where datetime may be a string
    if isinstance(started_at, str):
        started_at = datetime.fromisoformat(started_at)

    age_minutes = (
        datetime.now() - started_at
    ).total_seconds() / 60

    # --------------------------------------------------------
    # TOO RECENT
    # --------------------------------------------------------

    if age_minutes < 30:
        return CheckoutRecoveryDecision(
            action=WAIT,
            reason="CHECKOUT_TOO_RECENT",
        )

    # --------------------------------------------------------
    # ABANDONED CHECKOUT
    # --------------------------------------------------------

    return CheckoutRecoveryDecision(
        action=SEND_CHECKOUT_REMINDER,
        reason="CHECKOUT_DROPPED_OFF",
    )


# ============================================================
# B2B RECEIVABLES DECISION
# ============================================================

@dataclass
class B2BRecoveryDecision:
    action: str
    reason: str


def decide_b2b_recovery(
    receivable: B2BReceivable,
) -> B2BRecoveryDecision:
    """
    Decide recovery action for an overdue B2B invoice.

    Rules:
    - Paid -> no action
    - Not overdue -> wait
    - 1-7 days -> standard reminder
    - 8-15 days -> stronger reminder
    - 16-30 days -> account escalation
    - >30 days -> human escalation
    """

    # --------------------------------------------------------
    # ALREADY PAID
    # --------------------------------------------------------

    if receivable.payment_status == "paid":
        return B2BRecoveryDecision(
            action=NO_ACTION,
            reason="B2B_INVOICE_ALREADY_PAID",
        )

    # --------------------------------------------------------
    # NOT OVERDUE
    # --------------------------------------------------------

    if receivable.days_overdue <= 0:
        return B2BRecoveryDecision(
            action=WAIT,
            reason="B2B_INVOICE_NOT_OVERDUE",
        )

    # --------------------------------------------------------
    # 1-7 DAYS OVERDUE
    # --------------------------------------------------------

    if receivable.days_overdue <= 7:
        return B2BRecoveryDecision(
            action=SEND_B2B_REMINDER,
            reason="B2B_INVOICE_1_TO_7_DAYS_OVERDUE",
        )

    # --------------------------------------------------------
    # 8-15 DAYS OVERDUE
    # --------------------------------------------------------

    if receivable.days_overdue <= 15:
        return B2BRecoveryDecision(
            action=SEND_B2B_STRONGER_REMINDER,
            reason="B2B_INVOICE_8_TO_15_DAYS_OVERDUE",
        )

    # --------------------------------------------------------
    # 16-30 DAYS OVERDUE
    # --------------------------------------------------------

    if receivable.days_overdue <= 30:
        return B2BRecoveryDecision(
            action=ESCALATE_ACCOUNT,
            reason="B2B_INVOICE_16_TO_30_DAYS_OVERDUE",
        )

    # --------------------------------------------------------
    # MORE THAN 30 DAYS
    # --------------------------------------------------------

    return B2BRecoveryDecision(
        action=ESCALATE_B2B_HUMAN,
        reason="B2B_INVOICE_MORE_THAN_30_DAYS_OVERDUE",
    )


# ============================================================
# PROMISE-TO-PAY DECISION
# ============================================================

@dataclass
class PromiseToPayDecision:
    action: str
    reason: str


def decide_promise_to_pay(
    promise: PromiseToPay,
) -> PromiseToPayDecision:
    """
    Decide the next action for a Promise-to-Pay record.

    Rules:

    Promise already paid
        -> NO_ACTION

    Promise date is upcoming
        -> WAIT

    Promise due today
        -> SEND_PAYMENT_REMINDER

    Promise 1-3 days overdue
        -> SEND_STRONGER_REMINDER

    Promise 4-7 days overdue
        -> ESCALATE_ACCOUNT

    Promise more than 7 days overdue
        -> ESCALATE_HUMAN

    Important:
    A promise itself is NOT considered recovered revenue.
    Only an actual confirmed payment can be counted as recovery.
    """

    # --------------------------------------------------------
    # ALREADY PAID
    # --------------------------------------------------------

    if promise.status == "paid":
        return PromiseToPayDecision(
            action=PTP_NO_ACTION,
            reason="PROMISE_ALREADY_PAID",
        )

    # --------------------------------------------------------
    # CALCULATE DAYS OVERDUE
    # --------------------------------------------------------

    promised_date = promise.promised_date

    # Support JSON/test data where datetime may be a string
    if isinstance(promised_date, str):
        promised_date = datetime.fromisoformat(promised_date)

    today = datetime.now().date()
    promised_date = promised_date.date()

    days_overdue = (today - promised_date).days

    # --------------------------------------------------------
    # UPCOMING PROMISE
    # --------------------------------------------------------

    if days_overdue < 0:
        return PromiseToPayDecision(
            action=PTP_WAIT,
            reason="PROMISE_NOT_DUE",
        )

    # --------------------------------------------------------
    # DUE TODAY
    # --------------------------------------------------------

    if days_overdue == 0:
        return PromiseToPayDecision(
            action=PTP_PAYMENT_REMINDER,
            reason="PROMISE_DUE_TODAY",
        )

    # --------------------------------------------------------
    # 1-3 DAYS OVERDUE
    # --------------------------------------------------------

    if 1 <= days_overdue <= 3:
        return PromiseToPayDecision(
            action=PTP_STRONGER_REMINDER,
            reason="PROMISE_1_TO_3_DAYS_OVERDUE",
        )

    # --------------------------------------------------------
    # 4-7 DAYS OVERDUE
    # --------------------------------------------------------

    if 4 <= days_overdue <= 7:
        return PromiseToPayDecision(
            action=PTP_ESCALATE_ACCOUNT,
            reason="PROMISE_4_TO_7_DAYS_OVERDUE",
        )

    # --------------------------------------------------------
    # MORE THAN 7 DAYS OVERDUE
    # --------------------------------------------------------

    return PromiseToPayDecision(
        action=PTP_ESCALATE_HUMAN,
        reason="PROMISE_MORE_THAN_7_DAYS_OVERDUE",
    )