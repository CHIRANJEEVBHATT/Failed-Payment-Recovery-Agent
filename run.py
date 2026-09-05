import json
from pathlib import Path

from app.audit_logger import AuditLogger
from app.config import (
    DATA_DIR,
    MAX_REAL_API_CALLS,
)
from app.models import (
    B2BReceivable,
    CheckoutSession,
    FailedPayment,
    PromiseToPay,
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



def load_generated_b2b() -> list[B2BReceivable]:
    """Generate the current synthetic B2B receivables batch."""
    from app.generator import generate_b2b_receivables
    return generate_b2b_receivables(count=20)


def validate_b2b_dataset(receivables: list[B2BReceivable]) -> None:
    """Validate B2B receivables before processing."""
    if not receivables:
        raise ValueError("The B2B receivables dataset is empty.")
    invoice_ids = set()
    for receivable in receivables:
        if receivable.invoice_id in invoice_ids:
            raise ValueError(f"Duplicate invoice_id detected: {receivable.invoice_id}")
        invoice_ids.add(receivable.invoice_id)
        if not receivable.company_name:
            raise ValueError(f"Missing company_name for {receivable.invoice_id}")
        if not receivable.customer_id:
            raise ValueError(f"Missing customer_id for {receivable.invoice_id}")
        if receivable.amount <= 0:
            raise ValueError(f"Invalid B2B amount for {receivable.invoice_id}")
        if not receivable.currency:
            raise ValueError(f"Missing currency for {receivable.invoice_id}")
        if receivable.days_overdue < 0:
            raise ValueError(f"Invalid days_overdue for {receivable.invoice_id}")


def verify_b2b_audit_coverage(audit_logger: AuditLogger, receivables: list[B2BReceivable]) -> None:
    """Verify that every B2B invoice has exactly one audit record."""
    invoice_ids = {r.invoice_id for r in receivables}
    b2b_records = [r for r in audit_logger.get_all_logs() if r.get("record_type") == "b2b"]
    if len(b2b_records) != len(receivables):
        raise RuntimeError(f"B2B AUDIT COVERAGE FAILURE: expected {len(receivables)} B2B audit records but found {len(b2b_records)}.")
    if {r["invoice_id"] for r in b2b_records} != invoice_ids:
        raise RuntimeError("B2B AUDIT COVERAGE FAILURE: audit records do not match the current batch.")
    print(f"B2B audit coverage verified: {len(b2b_records)}/{len(receivables)}")


def print_b2b_summary(receivables: list[B2BReceivable], b2b_results: list[dict]) -> None:
    """Print a summary of B2B recovery actions."""
    total = sum(r.amount for r in receivables if r.payment_status.lower() != "paid")
    counts = {
        "SEND_REMINDER": sum(x["decision"] == "SEND_REMINDER" for x in b2b_results),
        "SEND_STRONGER_REMINDER": sum(x["decision"] == "SEND_STRONGER_REMINDER" for x in b2b_results),
        "ESCALATE_ACCOUNT": sum(x["decision"] == "ESCALATE_ACCOUNT" for x in b2b_results),
        "ESCALATE_HUMAN": sum(x["decision"] == "ESCALATE_HUMAN" for x in b2b_results),
        "NO_ACTION": sum(x["decision"] == "NO_ACTION" for x in b2b_results),
        "WAIT": sum(x["decision"] == "WAIT" for x in b2b_results),
    }
    print(); print("=" * 70); print("B2B RECEIVABLES SUMMARY"); print("=" * 70)
    print(f"B2B invoices: {len(receivables)}")
    print(f"Outstanding value observed: ₹{total:,.2f}")
    print(f"Standard reminders: {counts['SEND_REMINDER']}")
    print(f"Stronger reminders: {counts['SEND_STRONGER_REMINDER']}")
    print(f"Account escalations: {counts['ESCALATE_ACCOUNT']}")
    print(f"Human escalations: {counts['ESCALATE_HUMAN']}")
    print(f"Already paid / no action: {counts['NO_ACTION']}")
    print(f"Waiting: {counts['WAIT']}")
    print("Confirmed B2B revenue recovered: ₹0.00")
    print("Note: reminders and escalations are recovery actions, not confirmed money recovered.")
    print("=" * 70)



def load_generated_promises() -> list[PromiseToPay]:
    """Generate the current synthetic Promise-to-Pay batch."""
    from app.generator import generate_promise_to_pay
    return generate_promise_to_pay(count=20)


def validate_promise_to_pay_dataset(promises: list[PromiseToPay]) -> None:
    """Validate Promise-to-Pay records before processing."""
    if not promises:
        raise ValueError("The Promise-to-Pay dataset is empty.")

    promise_ids = set()
    for promise in promises:
        if promise.promise_id in promise_ids:
            raise ValueError(f"Duplicate promise_id detected: {promise.promise_id}")
        promise_ids.add(promise.promise_id)
        if not promise.customer_id:
            raise ValueError(f"Missing customer_id for {promise.promise_id}")
        if not promise.customer_name:
            raise ValueError(f"Missing customer_name for {promise.promise_id}")
        if promise.amount <= 0:
            raise ValueError(f"Invalid Promise-to-Pay amount for {promise.promise_id}")
        if not promise.currency:
            raise ValueError(f"Missing currency for {promise.promise_id}")
        if not promise.promised_date:
            raise ValueError(f"Missing promised_date for {promise.promise_id}")
        if not promise.created_at:
            raise ValueError(f"Missing created_at for {promise.promise_id}")


def verify_promise_to_pay_audit_coverage(
    audit_logger: AuditLogger,
    promises: list[PromiseToPay],
) -> None:
    """Verify that every Promise-to-Pay record has exactly one audit record."""
    promise_ids = {p.promise_id for p in promises}
    all_logs = audit_logger.get_all_logs()
    records = [r for r in all_logs if r.get("record_type") == "promise_to_pay"]

    if len(records) != len(promises):
        raise RuntimeError(
            "PTP AUDIT COVERAGE FAILURE: "
            f"expected {len(promises)} Promise-to-Pay audit records "
            f"but found {len(records)}."
        )

    audit_ids = {r.get("promise_id") for r in records}
    if audit_ids != promise_ids:
        raise RuntimeError(
            "PTP AUDIT COVERAGE FAILURE: audit records do not match "
            "the current Promise-to-Pay batch."
        )

    print(f"Promise-to-Pay audit coverage verified: {len(records)}/{len(promises)}")


def print_promise_to_pay_summary(
    promises: list[PromiseToPay],
    results: list[dict],
) -> None:
    """Print a summary of Promise-to-Pay recovery actions."""
    counts = {
        "SEND_PAYMENT_REMINDER": sum(x["decision"] == "SEND_PAYMENT_REMINDER" for x in results),
        "SEND_STRONGER_REMINDER": sum(x["decision"] == "SEND_STRONGER_REMINDER" for x in results),
        "ESCALATE_ACCOUNT": sum(x["decision"] == "ESCALATE_ACCOUNT" for x in results),
        "ESCALATE_HUMAN": sum(x["decision"] == "ESCALATE_HUMAN" for x in results),
        "WAIT": sum(x["decision"] == "WAIT" for x in results),
        "NO_ACTION": sum(x["decision"] == "NO_ACTION" for x in results),
    }
    outstanding = sum(
        p.amount for p in promises if p.status.lower() != "paid"
    )

    print()
    print("=" * 70)
    print("PROMISE-TO-PAY SUMMARY")
    print("=" * 70)
    print(f"Promises observed: {len(promises)}")
    print(f"Promise amount at risk: ₹{outstanding:,.2f}")
    print(f"Payment reminders: {counts['SEND_PAYMENT_REMINDER']}")
    print(f"Stronger reminders: {counts['SEND_STRONGER_REMINDER']}")
    print(f"Account escalations: {counts['ESCALATE_ACCOUNT']}")
    print(f"Human escalations: {counts['ESCALATE_HUMAN']}")
    print(f"Waiting: {counts['WAIT']}")
    print(f"Already paid / no action: {counts['NO_ACTION']}")
    print("Confirmed Promise-to-Pay revenue recovered: ₹0.00")
    print("Note: a promise or reminder is not confirmed payment revenue.")
    print("=" * 70)

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

    b2b_receivables = load_generated_b2b()

    validate_b2b_dataset(
        b2b_receivables
    )

    print(
        "B2B receivables dataset validation passed."
    )

    promises = load_generated_promises()
    validate_promise_to_pay_dataset(promises)
    print("Promise-to-Pay dataset validation passed.")

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

    b2b_results = processor.process_b2b_batch(
        b2b_receivables
    )

    promise_results = processor.process_promise_to_pay_batch(promises)

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

    verify_b2b_audit_coverage(
        audit_logger=audit_logger,
        receivables=b2b_receivables,
    )

    print_b2b_summary(
        receivables=b2b_receivables,
        b2b_results=b2b_results,
    )

    verify_promise_to_pay_audit_coverage(
        audit_logger=audit_logger,
        promises=promises,
    )

    print_promise_to_pay_summary(
        promises=promises,
        results=promise_results,
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
        f"B2B receivables processed: "
        f"{len(b2b_receivables)}"
    )

    print(
        f"Promise-to-Pay records processed: "
        f"{len(promises)}"
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