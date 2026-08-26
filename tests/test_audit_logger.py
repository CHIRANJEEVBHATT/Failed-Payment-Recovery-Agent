from app.audit_logger import AuditLogger


def test_audit_logger_creates_database(tmp_path):
    """
    Verify that AuditLogger creates the SQLite database
    and audit_logs table.
    """

    database_path = (
        tmp_path / "test_audit.db"
    )

    logger = AuditLogger(
        database_path=str(database_path)
    )

    assert database_path.exists()

    assert logger.count_logs() == 0


def test_audit_logger_stores_record(tmp_path):
    """
    Verify that one complete audit record can be stored
    and retrieved.
    """

    database_path = (
        tmp_path / "test_audit.db"
    )

    logger = AuditLogger(
        database_path=str(database_path)
    )

    logger.log(
        payment_id="audit_test_001",
        customer_name="Test Customer",
        email="test@example.com",
        amount=1000.00,
        failure_reason="card_expired",
        payment_type="one-time",
        attempt_count=1,
        decision="SEND_NEW_LINK",
        decision_reason=(
            "Card expired; send a new payment link."
        ),
        action_taken="PAYMENT_LINK_CREATED",
        api_request='{"method":"POST"}',
        api_response='{"id":"plink_test_001"}',
        outcome="recovered",
        notes="Test audit record.",
        recovery_type="real",
        real_api_call=True,
        simulated=False,
    )

    assert logger.count_logs() == 1

    records = logger.get_all_logs()

    assert len(records) == 1

    record = records[0]

    assert (
        record["payment_id"]
        == "audit_test_001"
    )

    assert (
        record["failure_reason"]
        == "card_expired"
    )

    assert (
        record["decision"]
        == "SEND_NEW_LINK"
    )

    assert (
        record["action_taken"]
        == "PAYMENT_LINK_CREATED"
    )

    assert (
        record["outcome"]
        == "recovered"
    )

    assert (
        record["recovery_type"]
        == "real"
    )

    assert (
        record["real_api_call"]
        == 1
    )

    assert (
        record["simulated"]
        == 0
    )


def test_simulated_recovery_is_stored_separately(
    tmp_path,
):
    """
    Verify that a simulated recovery is explicitly marked
    as simulated and is not marked as a real API call.
    """

    database_path = (
        tmp_path / "test_audit.db"
    )

    logger = AuditLogger(
        database_path=str(database_path)
    )

    logger.log(
        payment_id="audit_simulated_001",
        customer_name="Test Customer",
        email="test@example.com",
        amount=2500.00,
        failure_reason="card_expired",
        payment_type="one-time",
        attempt_count=1,
        decision="SEND_NEW_LINK",
        decision_reason=(
            "Card expired; send a new payment link."
        ),
        action_taken=(
            "simulated_due_to_test_mode_cap"
        ),
        api_request=None,
        api_response=None,
        outcome="still_failed",
        notes=(
            "Real API cap reached."
        ),
        recovery_type="simulated",
        real_api_call=False,
        simulated=True,
    )

    records = logger.get_all_logs()

    assert len(records) == 1

    record = records[0]

    assert (
        record["action_taken"]
        == "simulated_due_to_test_mode_cap"
    )

    assert (
        record["recovery_type"]
        == "simulated"
    )

    assert (
        record["real_api_call"]
        == 0
    )

    assert (
        record["simulated"]
        == 1
    )

    assert (
        record["outcome"]
        == "still_failed"
    )


def test_get_logs_for_payment_ids_filters_batch(
    tmp_path,
):
    """
    Verify that the audit logger can retrieve only the
    records belonging to the current batch.
    """

    database_path = (
        tmp_path / "test_audit.db"
    )

    logger = AuditLogger(
        database_path=str(database_path)
    )

    for payment_id in [
        "batch_a",
        "batch_b",
        "old_record",
    ]:
        logger.log(
            payment_id=payment_id,
            customer_name="Test Customer",
            email="test@example.com",
            amount=1000.00,
            failure_reason="fraud_block",
            payment_type="one-time",
            attempt_count=1,
            decision="ESCALATE_HUMAN",
            decision_reason="Fraud block.",
            action_taken="ESCALATE_HUMAN",
            api_request=None,
            api_response=None,
            outcome="escalated",
            notes=None,
            recovery_type="none",
            real_api_call=False,
            simulated=False,
        )

    assert logger.count_logs() == 3

    current_batch = (
        logger.get_logs_for_payment_ids(
            [
                "batch_a",
                "batch_b",
            ]
        )
    )

    assert len(current_batch) == 2

    payment_ids = {
        record["payment_id"]
        for record in current_batch
    }

    assert payment_ids == {
        "batch_a",
        "batch_b",
    }

    assert "old_record" not in payment_ids


def test_every_audit_record_has_timestamp(
    tmp_path,
):
    """
    Verify that every audit record receives a timestamp.
    """

    database_path = (
        tmp_path / "test_audit.db"
    )

    logger = AuditLogger(
        database_path=str(database_path)
    )

    logger.log(
        payment_id="timestamp_test",
        customer_name="Test Customer",
        email="test@example.com",
        amount=500.00,
        failure_reason="otp_failed",
        payment_type="one-time",
        attempt_count=1,
        decision="SEND_REMINDER",
        decision_reason="OTP failure.",
        action_taken="SEND_REMINDER",
        api_request=None,
        api_response=None,
        outcome="still_failed",
        notes="Timestamp test.",
        recovery_type="none",
        real_api_call=False,
        simulated=False,
    )

    record = logger.get_all_logs()[0]

    assert record["timestamp"]

    assert isinstance(
        record["timestamp"],
        str,
    )