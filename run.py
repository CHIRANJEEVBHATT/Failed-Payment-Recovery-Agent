import json
from pathlib import Path

from app.audit_logger import AuditLogger
from app.config import (
    DATA_DIR,
    MAX_REAL_API_CALLS,
)
from app.models import (
    CheckoutSession,
    FailedPayment,
)
from app.processor import PaymentProcessor
from app.reporter import RecoveryReporter


def load_generated_payments() -> list[FailedPayment]:
    """
    Load the current synthetic failed-payment dataset.
    """

    data_file = (
        Path(DATA_DIR)
        / "failed_payments.json"
    )

    if not data_file.exists():
        raise FileNotFoundError(
            f"Payment dataset not found: {data_file}\n\n"
            "Generate the dataset first with:\n"
            "python -m app.generator"
        )

    with data_file.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(
            "failed_payments.json must contain "
            "a JSON list."
        )

    return [
        FailedPayment(**record)
        for record in data
    ]


def validate_dataset(
    payments: list[FailedPayment],
) -> None:
    """
    Validate the complete synthetic batch before processing.
    """

    if not payments:
        raise ValueError(
            "The payment dataset is empty."
        )

    allowed_failure_reasons = {
        "insufficient_funds",
        "card_expired",
        "bank_timeout",
        "otp_failed",
        "fraud_block",
        "mandate_failed",
    }

    allowed_payment_types = {
        "one-time",
        "subscription",
    }

    payment_ids = set()

    for payment in payments:

        if payment.payment_id in payment_ids:
            raise ValueError(
                "Duplicate payment_id detected: "
                f"{payment.payment_id}"
            )

        payment_ids.add(
            payment.payment_id
        )

        if payment.failure_reason not in (
            allowed_failure_reasons
        ):
            raise ValueError(
                f"Invalid failure reason: "
                f"{payment.failure_reason}"
            )

        if payment.payment_type not in (
            allowed_payment_types
        ):
            raise ValueError(
                f"Invalid payment type: "
                f"{payment.payment_type}"
            )

        if payment.amount <= 0:
            raise ValueError(
                f"Invalid amount for "
                f"{payment.payment_id}"
            )

        if payment.attempt_count < 1:
            raise ValueError(
                f"Invalid attempt count for "
                f"{payment.payment_id}"
            )

        if not payment.email:
            raise ValueError(
                f"Missing email for "
                f"{payment.payment_id}"
            )

        if not payment.phone:
            raise ValueError(
                f"Missing phone for "
                f"{payment.payment_id}"
            )

        if not payment.last_attempt_at:
            raise ValueError(
                f"Missing last_attempt_at for "
                f"{payment.payment_id}"
            )


def load_generated_checkouts() -> list[CheckoutSession]:
    """
    Generate synthetic checkout drop-off sessions.

    Checkout data is generated in memory for the current
    demonstration run.
    """

    from app.generator import generate_checkout_dropoffs

    return generate_checkout_dropoffs(
        count=20
    )


def validate_checkout_dataset(
    sessions: list[CheckoutSession],
) -> None:
    """
    Validate checkout sessions before processing.
    """

    if not sessions:
        raise ValueError(
            "The checkout dataset is empty."
        )

    checkout_ids = set()

    for session in sessions:

        if session.checkout_id in checkout_ids:
            raise ValueError(
                "Duplicate checkout_id detected: "
                f"{session.checkout_id}"
            )

        checkout_ids.add(
            session.checkout_id
        )

        if session.amount <= 0:
            raise ValueError(
                f"Invalid checkout amount for "
                f"{session.checkout_id}"
            )

        if not session.customer_id:
            raise ValueError(
                f"Missing customer_id for "
                f"{session.checkout_id}"
            )

        if not session.currency:
            raise ValueError(
                f"Missing currency for "
                f"{session.checkout_id}"
            )


def print_batch_information(
    payments: list[FailedPayment],
) -> None:
    """
    Print information about the current payment batch.
    """

    total_amount = sum(
        payment.amount
        for payment in payments
    )

    print(
        f"Records to process: "
        f"{len(payments)}"
    )

    print(
        f"Total amount at risk: "
        f"₹{total_amount:,.2f}"
    )

    print(
        f"Real Payment Link API cap: "
        f"{MAX_REAL_API_CALLS}"
    )


def verify_audit_coverage(
    audit_logger: AuditLogger,
    payments: list[FailedPayment],
) -> None:
    """
    Verify that every current-batch payment has exactly
    one audit record.
    """

    payment_ids = [
        payment.payment_id
        for payment in payments
    ]

    audit_records = (
        audit_logger.get_logs_for_payment_ids(
            payment_ids
        )
    )

    if len(audit_records) != len(
        payments
    ):
        raise RuntimeError(
            "AUDIT COVERAGE FAILURE: "
            f"expected {len(payments)} audit records "
            f"but found {len(audit_records)}."
        )

    audit_payment_ids = [
        record["payment_id"]
        for record in audit_records
    ]

    if len(audit_payment_ids) != len(
        set(audit_payment_ids)
    ):
        raise RuntimeError(
            "AUDIT COVERAGE FAILURE: "
            "duplicate audit record detected."
        )

    if set(audit_payment_ids) != set(
        payment_ids
    ):
        raise RuntimeError(
            "AUDIT COVERAGE FAILURE: "
            "audit records do not match the "
            "current batch."
        )

    print(
        f"Payment audit coverage verified: "
        f"{len(audit_records)}/"
        f"{len(payments)}"
    )


def verify_checkout_audit_coverage(
    audit_logger: AuditLogger,
    sessions: list[CheckoutSession],
) -> None:
    """
    Verify that every checkout session has exactly
    one checkout audit record.
    """

    checkout_ids = {
        session.checkout_id
        for session in sessions
    }

    all_logs = audit_logger.get_all_logs()

    checkout_records = [
        record
        for record in all_logs
        if record.get("record_type") == "checkout"
    ]

    if len(checkout_records) != len(
        sessions
    ):
        raise RuntimeError(
            "CHECKOUT AUDIT COVERAGE FAILURE: "
            f"expected {len(sessions)} checkout audit "
            f"records but found "
            f"{len(checkout_records)}."
        )

    audit_checkout_ids = {
        record["checkout_id"]
        for record in checkout_records
    }

    if audit_checkout_ids != checkout_ids:
        raise RuntimeError(
            "CHECKOUT AUDIT COVERAGE FAILURE: "
            "audit records do not match the "
            "current checkout batch."
        )

    print(
        f"Checkout audit coverage verified: "
        f"{len(checkout_records)}/"
        f"{len(sessions)}"
    )


def verify_api_cap(
    processor: PaymentProcessor,
) -> None:
    """
    Verify that the configured real API cap
    was never exceeded.
    """

    if (
        processor.real_api_calls
        > MAX_REAL_API_CALLS
    ):
        raise RuntimeError(
            "SAFETY FAILURE: real Razorpay API "
            "call cap was exceeded."
        )


def print_checkout_summary(
    sessions: list[CheckoutSession],
    checkout_results: list[dict],
) -> None:
    """
    Print a summary of checkout drop-off recovery.
    """

    total_checkout_value = sum(
        session.amount
        for session in sessions
    )

    abandoned = [
        result
        for result in checkout_results
        if result["decision"]
        == "SEND_CHECKOUT_REMINDER"
    ]

    completed = [
        result
        for result in checkout_results
        if result["decision"]
        == "NO_ACTION"
    ]

    waiting = [
        result
        for result in checkout_results
        if result["decision"]
        == "WAIT"
    ]

    print()
    print("=" * 70)
    print("CHECKOUT DROP-OFF SUMMARY")
    print("=" * 70)

    print(
        f"Checkout sessions: "
        f"{len(sessions)}"
    )

    print(
        f"Checkout value observed: "
        f"₹{total_checkout_value:,.2f}"
    )

    print(
        f"Completed: "
        f"{len(completed)}"
    )

    print(
        f"Recovery reminders selected: "
        f"{len(abandoned)}"
    )

    print(
        f"Too recent / waiting: "
        f"{len(waiting)}"
    )

    print(
        "Confirmed checkout revenue recovered: "
        "₹0.00"
    )

    print(
        "Note: A reminder is a recovery attempt, "
        "not confirmed recovered revenue."
    )

    print("=" * 70)


def main():
    """
    Run the complete Failed Payment Recovery Agent
    with checkout drop-off recovery.
    """

    print()
    print("=" * 70)
    print(
        "FAILED PAYMENT RECOVERY AGENT"
    )
    print("=" * 70)

    # -----------------------------------------------------
    # Step 1 — Load
    # -----------------------------------------------------

    print()
    print(
        "[1/5] Loading current synthetic batch..."
    )

    payments = load_generated_payments()

    print()
    print_batch_information(
        payments
    )

    # -----------------------------------------------------
    # Step 2 — Validate
    # -----------------------------------------------------

    print()
    print(
        "[2/5] Validating batch..."
    )

    validate_dataset(
        payments
    )

    print(
        "Payment dataset validation passed."
    )

    checkout_sessions = (
        load_generated_checkouts()
    )

    validate_checkout_dataset(
        checkout_sessions
    )

    print(
        "Checkout dataset validation passed."
    )

    # -----------------------------------------------------
    # Step 3 — Initialize database
    # -----------------------------------------------------

    audit_logger = AuditLogger()

    print()
    print(
        "SQLite database connected:"
    )

    print(
        f"    {audit_logger.database_path}"
    )

    # -----------------------------------------------------
    # IMPORTANT:
    # Start a clean audit batch.
    # -----------------------------------------------------

    audit_logger.clear_logs()

    print(
        "Previous audit records cleared."
    )

    print(
        "Starting fresh audit trail for "
        "this batch."
    )

    # -----------------------------------------------------
    # Step 4 — Process
    # -----------------------------------------------------

    print()
    print(
        "[3/5] Processing recovery actions..."
    )

    processor = PaymentProcessor(
        audit_logger=audit_logger,
    )

    results = processor.process_batch(
        payments
    )

    checkout_results = (
        processor.process_checkout_batch(
            checkout_sessions
        )
    )

    # -----------------------------------------------------
    # Safety verification
    # -----------------------------------------------------

    verify_api_cap(
        processor
    )

    # -----------------------------------------------------
    # Step 5 — Audit verification
    # -----------------------------------------------------

    print()
    print(
        "[4/5] Verifying audit trail..."
    )

    verify_audit_coverage(
        audit_logger=audit_logger,
        payments=payments,
    )

    verify_checkout_audit_coverage(
        audit_logger=audit_logger,
        sessions=checkout_sessions,
    )

    # -----------------------------------------------------
    # Checkout summary
    # -----------------------------------------------------

    print_checkout_summary(
        sessions=checkout_sessions,
        checkout_results=checkout_results,
    )

    # -----------------------------------------------------
    # Step 6 — Report
    # -----------------------------------------------------

    print()
    print(
        "[5/5] Generating final report..."
    )

    reporter = RecoveryReporter()

    report_path = reporter.save_report(
        results
    )

    reporter.print_summary(
        results
    )

    # -----------------------------------------------------
    # Final output
    # -----------------------------------------------------

    print()
    print("=" * 70)
    print(
        "PROCESSING COMPLETE"
    )
    print("=" * 70)

    print(
        f"Payments processed: "
        f"{len(payments)}"
    )

    print(
        f"Checkout sessions processed: "
        f"{len(checkout_sessions)}"
    )

    print(
        f"Real Razorpay API calls: "
        f"{processor.real_api_calls}/"
        f"{MAX_REAL_API_CALLS}"
    )

    print(
        f"Audit records created: "
        f"{audit_logger.count_logs()}"
    )

    print(
        f"Report saved to: "
        f"{report_path}"
    )

    print(
        f"Audit database: "
        f"{Path('database') / 'audit.db'}"
    )

    print(
        f"API log: "
        f"{Path('logs') / 'razorpay_api.log'}"
    )

    print("=" * 70)
    print()


if __name__ == "__main__":
    main()