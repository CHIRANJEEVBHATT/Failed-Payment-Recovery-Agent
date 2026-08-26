from app.models import FailedPayment
from app.processor import PaymentProcessor


class FakeRazorpayClient:
    """
    Fake Razorpay client used only for testing.

    It behaves like a successful Payment Link API without
    making any real network request.

    This lets us test the processor's 20-call safety cap
    without consuming real Razorpay Test Mode Payment Links.
    """

    def __init__(self):
        self.calls = []

    def create_payment_link(
        self,
        amount,
        customer_name,
        email,
        phone,
        reference_id,
    ):
        self.calls.append(
            {
                "amount": amount,
                "customer_name": customer_name,
                "email": email,
                "phone": phone,
                "reference_id": reference_id,
            }
        )

        return {
            "success": True,
            "status_code": 200,
            "data": {
                "id": f"fake_plink_{reference_id}",
                "short_url": (
                    f"https://example.com/"
                    f"{reference_id}"
                ),
            },
            "error": None,
            "request": {
                "method": "POST",
                "url": (
                    "https://api.razorpay.com/v1/"
                    "payment_links"
                ),
                "payload": {
                    "amount": int(
                        amount * 100
                    ),
                    "currency": "INR",
                },
            },
        }


class FakeAuditLogger:
    """
    In-memory audit logger.

    This prevents the processor test from modifying the
    real database.
    """

    def __init__(self):
        self.records = []

    def log(self, **kwargs):
        self.records.append(kwargs)


def make_payment(
    payment_id,
    failure_reason="card_expired",
):
    """
    Create a payment that should receive SEND_NEW_LINK.
    """

    return FailedPayment(
        payment_id=payment_id,
        customer_name="Test Customer",
        email=f"{payment_id}@example.com",
        phone="9876543210",
        amount=1000.00,
        failure_reason=failure_reason,
        attempt_count=1,
        payment_type="one-time",
        last_attempt_at=(
            "2026-08-26T20:00:00"
        ),
    )


# ---------------------------------------------------------
# Payment Link API cap
# ---------------------------------------------------------

def test_payment_link_api_cap():
    """
    Verify that:

    - The first 20 SEND_NEW_LINK records make real API calls.
    - Records after 20 do NOT make API calls.
    - Records after 20 are explicitly marked as simulated.
    - The processor never exceeds the configured cap.
    """

    fake_razorpay = FakeRazorpayClient()

    fake_audit = FakeAuditLogger()

    processor = PaymentProcessor(
        razorpay_client=fake_razorpay,
        audit_logger=fake_audit,
    )

    payments = [
        make_payment(
            f"cap_test_{index:03d}"
        )
        for index in range(1, 26)
    ]

    results = processor.process_batch(
        payments
    )

    # Exactly 20 real API requests.
    assert len(
        fake_razorpay.calls
    ) == 20

    assert processor.real_api_calls == 20

    # First 20 are real recoveries.
    real_results = [
        result
        for result in results
        if result.get("recovery_type")
        == "real"
    ]

    assert len(real_results) == 20

    # Remaining 5 are explicitly simulated.
    simulated_results = [
        result
        for result in results
        if result.get("simulated") is True
    ]

    assert len(simulated_results) == 5

    # Every simulated record must have the exact required
    # action marker.
    for result in simulated_results:
        assert (
            result["action_taken"]
            == "simulated_due_to_test_mode_cap"
        )

        assert result["real_api_call"] is False

        assert result["outcome"] == "still_failed"

    # No record after the cap can be marked as a real
    # recovery.
    for result in results[20:]:
        assert (
            result["recovery_type"]
            == "simulated"
        )


# ---------------------------------------------------------
# No API call for escalation
# ---------------------------------------------------------

def test_fraud_block_never_calls_razorpay():
    """
    Fraud-blocked payments must be escalated and must never
    reach the Razorpay client.
    """

    fake_razorpay = FakeRazorpayClient()

    fake_audit = FakeAuditLogger()

    processor = PaymentProcessor(
        razorpay_client=fake_razorpay,
        audit_logger=fake_audit,
    )

    payment = make_payment(
        "fraud_test_001",
        failure_reason="fraud_block",
    )

    result = processor.process_payment(
        payment
    )

    assert result["decision"] == "ESCALATE_HUMAN"

    assert result["outcome"] == "escalated"

    assert len(
        fake_razorpay.calls
    ) == 0


# ---------------------------------------------------------
# No API call for OTP failure
# ---------------------------------------------------------

def test_otp_failure_sends_reminder():
    """
    OTP failure must send a reminder and must not silently
    call the Payment Link API.
    """

    fake_razorpay = FakeRazorpayClient()

    fake_audit = FakeAuditLogger()

    processor = PaymentProcessor(
        razorpay_client=fake_razorpay,
        audit_logger=fake_audit,
    )

    payment = make_payment(
        "otp_test_001",
        failure_reason="otp_failed",
    )

    result = processor.process_payment(
        payment
    )

    assert result["decision"] == "SEND_REMINDER"

    assert result["action_taken"] == "SEND_REMINDER"

    assert len(
        fake_razorpay.calls
    ) == 0


# ---------------------------------------------------------
# Successful Payment Link
# ---------------------------------------------------------

def test_successful_payment_link_is_real_recovery():
    """
    A successful Payment Link API response should be
    recorded as a real API recovery operation.
    """

    fake_razorpay = FakeRazorpayClient()

    fake_audit = FakeAuditLogger()

    processor = PaymentProcessor(
        razorpay_client=fake_razorpay,
        audit_logger=fake_audit,
    )

    payment = make_payment(
        "real_recovery_001",
        failure_reason="card_expired",
    )

    result = processor.process_payment(
        payment
    )

    assert result["decision"] == "SEND_NEW_LINK"

    assert result["outcome"] == "recovered"

    assert result["recovery_type"] == "real"

    assert result["real_api_call"] is True

    assert result["simulated"] is False

    assert (
        result["payment_link"]
        == "https://example.com/"
        "real_recovery_001"
    )

    assert len(
        fake_razorpay.calls
    ) == 1


# ---------------------------------------------------------
# Audit records
# ---------------------------------------------------------

def test_every_processed_payment_creates_audit_record():
    """
    Every processed payment must produce exactly one audit
    record.
    """

    fake_razorpay = FakeRazorpayClient()

    fake_audit = FakeAuditLogger()

    processor = PaymentProcessor(
        razorpay_client=fake_razorpay,
        audit_logger=fake_audit,
    )

    payments = [
        make_payment(
            "audit_test_001",
            "card_expired",
        ),
        make_payment(
            "audit_test_002",
            "fraud_block",
        ),
        make_payment(
            "audit_test_003",
            "otp_failed",
        ),
    ]

    processor.process_batch(
        payments
    )

    assert len(
        fake_audit.records
    ) == len(payments)

    payment_ids = {
        record["payment_id"]
        for record in fake_audit.records
    }

    assert payment_ids == {
        "audit_test_001",
        "audit_test_002",
        "audit_test_003",
    }