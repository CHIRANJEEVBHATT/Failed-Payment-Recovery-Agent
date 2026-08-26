import json
from pathlib import Path

from app.audit_logger import AuditLogger
from app.config import (
    DATA_DIR,
    MAX_REAL_API_CALLS,
)
from app.models import FailedPayment
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


def print_batch_information(
    payments: list[FailedPayment],
) -> None:
    """
    Print information about the current batch.
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
        f"Audit coverage verified: "
        f"{len(audit_records)}/"
        f"{len(payments)}"
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


def main():
    """
    Run the complete Failed Payment Recovery Agent.
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
        "Dataset validation passed."
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