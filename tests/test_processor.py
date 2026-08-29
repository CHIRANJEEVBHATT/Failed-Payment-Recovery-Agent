from app.models import FailedPayment
from app.processor import PaymentProcessor


class FakeRazorpayClient:
    """
    Fake Razorpay client used only for testing.

    It behaves like a successful Payment Link API without
    making any real network request.

    Settlement status can be configured per instance so
    tests can verify both:

        - Payment Link created but unpaid.
        - Payment Link actually paid.

    This lets us test the processor's recovery logic and
    20-call safety cap without consuming real Razorpay
    Test Mode Payment Links.
    """

    def __init__(
        self,
        settlement_confirmed=False,
    ):
        self.calls = []

        self.settlement_confirmed = (
            settlement_confirmed
        )

        self.settlement_checks = []

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

        payment_link_id = (
            f"fake_plink_{reference_id}"
        )

        return {
            "success": True,
            "status_code": 200,
            "data": {
                "id": payment_link_id,
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

    def check_payment_link_settlement(
        self,
        payment_link_id,
    ):
        """
        Fake the Razorpay Payment Link status check.

        By default the fake link is unpaid.

        Tests can create:

            FakeRazorpayClient(
                settlement_confirmed=True
            )

        to simulate an actually paid Payment Link.
        """

        self.settlement_checks.append(
            payment_link_id
        )

        if self.settlement_confirmed:
            return {
                "success": True,
                "confirmed": True,
                "status": "paid",
                "amount": 1000.00,
                "amount_paid": 1000.00,
                "payment_link_id": (
                    payment_link_id
                ),
                "payment_id": (
                    f"pay_{payment_link_id}"
                ),
                "error": None,
                "api_status_code": 200,
                "api_response": {
                    "status": "paid",
                    "amount": 100000,
                    "amount_paid": 100000,
                },
            }

        return {
            "success": True,
            "confirmed": False,
            "status": "created",
            "amount": 1000.00,
            "amount_paid": 0.00,
            "payment_link_id": (
                payment_link_id
            ),
            "payment_id": None,
            "error": None,
            "api_status_code": 200,
            "api_response": {
                "status": "created",
                "amount": 100000,
                "amount_paid": 0,
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
    - Payment Link creation is NOT counted as confirmed
      recovery unless settlement is confirmed.
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

    # Exactly 20 real Payment Link creation calls.
    assert len(
        fake_razorpay.calls
    ) == 20

    assert processor.real_api_calls == 20

    # All first 20 links were created by the real API,
    # but none are confirmed because the fake settlement
    # state is "created".
    real_api_results = [
        result
        for result in results
        if result.get("real_api_call") is True
    ]

    assert len(
        real_api_results
    ) == 20

    for result in real_api_results:
        assert (
            result["action_taken"]
            == "PAYMENT_LINK_CREATED"
        )

        assert (
            result["outcome"]
            == "awaiting_payment"
        )

        assert (
            result["recovery_type"]
            == "none"
        )

        assert (
            result["settlement_confirmed"]
            is False
        )

    # Remaining 5 are explicitly simulated.
    simulated_results = [
        result
        for result in results
        if result.get("simulated") is True
    ]

    assert len(
        simulated_results
    ) == 5

    for result in simulated_results:
        assert (
            result["action_taken"]
            == "simulated_due_to_test_mode_cap"
        )

        assert result["real_api_call"] is False

        assert result["outcome"] == "still_failed"

        assert (
            result["recovery_type"]
            == "simulated"
        )

    # Exactly 20 settlement checks should have been made
    # because exactly 20 real Payment Links were created.
    assert len(
        fake_razorpay.settlement_checks
    ) == 20


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

    assert len(
        fake_razorpay.settlement_checks
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

    assert len(
        fake_razorpay.settlement_checks
    ) == 0


# ---------------------------------------------------------
# Payment Link created but unpaid
# ---------------------------------------------------------

def test_payment_link_creation_is_not_recovery():
    """
    Creating a Payment Link successfully must NOT be counted
    as recovered revenue.

    The fake Razorpay status is:

        created
        amount_paid = 0

    Therefore the result must remain:

        awaiting_payment
        recovery_type = none
    """

    fake_razorpay = FakeRazorpayClient(
        settlement_confirmed=False
    )

    fake_audit = FakeAuditLogger()

    processor = PaymentProcessor(
        razorpay_client=fake_razorpay,
        audit_logger=fake_audit,
    )

    payment = make_payment(
        "unpaid_recovery_001",
        failure_reason="card_expired",
    )

    result = processor.process_payment(
        payment
    )

    assert result["decision"] == "SEND_NEW_LINK"

    assert (
        result["action_taken"]
        == "PAYMENT_LINK_CREATED"
    )

    assert (
        result["outcome"]
        == "awaiting_payment"
    )

    assert (
        result["recovery_type"]
        == "none"
    )

    assert result["real_api_call"] is True

    assert result["simulated"] is False

    assert (
        result["settlement_status"]
        == "created"
    )

    assert (
        result["settlement_confirmed"]
        is False
    )

    assert (
        result["settlement_amount_paid"]
        == 0.00
    )

    assert (
        result["settlement_payment_id"]
        is None
    )

    assert (
        result["payment_link"]
        == "https://example.com/"
        "unpaid_recovery_001"
    )

    assert len(
        fake_razorpay.calls
    ) == 1

    assert len(
        fake_razorpay.settlement_checks
    ) == 1


# ---------------------------------------------------------
# Confirmed settlement
# ---------------------------------------------------------

def test_confirmed_payment_link_is_real_recovery():
    """
    A Payment Link is counted as real recovered revenue
    only when the settlement check confirms:

        status == paid
        amount_paid > 0
    """

    fake_razorpay = FakeRazorpayClient(
        settlement_confirmed=True
    )

    fake_audit = FakeAuditLogger()

    processor = PaymentProcessor(
        razorpay_client=fake_razorpay,
        audit_logger=fake_audit,
    )

    payment = make_payment(
        "confirmed_recovery_001",
        failure_reason="card_expired",
    )

    result = processor.process_payment(
        payment
    )

    assert result["decision"] == "SEND_NEW_LINK"

    assert (
        result["action_taken"]
        == "PAYMENT_LINK_CREATED"
    )

    assert (
        result["outcome"]
        == "confirmed_settlement"
    )

    assert (
        result["recovery_type"]
        == "real"
    )

    assert result["real_api_call"] is True

    assert result["simulated"] is False

    assert (
        result["settlement_status"]
        == "paid"
    )

    assert (
        result["settlement_confirmed"]
        is True
    )

    assert (
        result["settlement_amount_paid"]
        == 1000.00
    )

    assert (
        result["settlement_payment_id"]
        == "pay_fake_plink_confirmed_recovery_001"
    )

    assert (
        result["payment_link"]
        == "https://example.com/"
        "confirmed_recovery_001"
    )

    assert len(
        fake_razorpay.calls
    ) == 1

    assert len(
        fake_razorpay.settlement_checks
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
