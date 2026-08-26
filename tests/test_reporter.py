from pathlib import Path

from app.reporter import RecoveryReporter


def make_result(
    payment_id: str,
    amount: float,
    failure_reason: str,
    decision: str,
    outcome: str,
    recovery_type: str,
    action_taken: str,
    real_api_call: bool = False,
    simulated: bool = False,
    reason: str = "Test reason",
) -> dict:
    """
    Create a standard processor result for reporter tests.
    """

    return {
        "payment_id": payment_id,
        "customer_name": "Test Customer",
        "email": f"{payment_id}@example.com",
        "phone": "9876543210",
        "amount": amount,
        "failure_reason": failure_reason,
        "payment_type": "one-time",
        "attempt_count": 1,
        "decision": decision,
        "action_taken": action_taken,
        "outcome": outcome,
        "recovery_type": recovery_type,
        "real_api_call": real_api_call,
        "simulated": simulated,
        "reason": reason,
    }


# ---------------------------------------------------------
# Amount at risk
# ---------------------------------------------------------

def test_total_amount_at_risk():
    reporter = RecoveryReporter()

    results = [
        make_result(
            "risk_001",
            1000,
            "card_expired",
            "SEND_NEW_LINK",
            "recovered",
            "real",
            "PAYMENT_LINK_CREATED",
            real_api_call=True,
        ),
        make_result(
            "risk_002",
            2000,
            "fraud_block",
            "ESCALATE_HUMAN",
            "escalated",
            "none",
            "ESCALATE_HUMAN",
        ),
    ]

    assert (
        reporter.total_amount_at_risk(results)
        == 3000
    )


# ---------------------------------------------------------
# Real recovery amount
# ---------------------------------------------------------

def test_only_real_recoveries_count_as_real():
    reporter = RecoveryReporter()

    results = [
        make_result(
            "real_001",
            1000,
            "card_expired",
            "SEND_NEW_LINK",
            "recovered",
            "real",
            "PAYMENT_LINK_CREATED",
            real_api_call=True,
        ),
        make_result(
            "sim_001",
            2000,
            "card_expired",
            "SEND_NEW_LINK",
            "still_failed",
            "simulated",
            "simulated_due_to_test_mode_cap",
            simulated=True,
        ),
    ]

    assert (
        reporter.real_recovery_amount(results)
        == 1000
    )

    assert (
        reporter.real_recovery_count(results)
        == 1
    )


# ---------------------------------------------------------
# Simulated recovery amount
# ---------------------------------------------------------

def test_simulated_recoveries_are_separate():
    reporter = RecoveryReporter()

    results = [
        make_result(
            "sim_001",
            2000,
            "card_expired",
            "SEND_NEW_LINK",
            "still_failed",
            "simulated",
            "simulated_due_to_test_mode_cap",
            simulated=True,
        ),
        make_result(
            "real_001",
            1000,
            "card_expired",
            "SEND_NEW_LINK",
            "recovered",
            "real",
            "PAYMENT_LINK_CREATED",
            real_api_call=True,
        ),
    ]

    assert (
        reporter.simulated_recovery_amount(
            results
        )
        == 2000
    )

    assert (
        reporter.simulated_recovery_count(
            results
        )
        == 1
    )


# ---------------------------------------------------------
# Recovery percentages
# ---------------------------------------------------------

def test_real_recovery_percentage():
    reporter = RecoveryReporter()

    results = [
        make_result(
            "real_001",
            1000,
            "card_expired",
            "SEND_NEW_LINK",
            "recovered",
            "real",
            "PAYMENT_LINK_CREATED",
            real_api_call=True,
        ),
        make_result(
            "failed_001",
            3000,
            "fraud_block",
            "ESCALATE_HUMAN",
            "escalated",
            "none",
            "ESCALATE_HUMAN",
        ),
    ]

    percentage = (
        reporter.real_recovery_percentage(
            results
        )
    )

    assert percentage == 25.0


def test_combined_percentage_is_labeled_metric():
    reporter = RecoveryReporter()

    results = [
        make_result(
            "real_001",
            1000,
            "card_expired",
            "SEND_NEW_LINK",
            "recovered",
            "real",
            "PAYMENT_LINK_CREATED",
            real_api_call=True,
        ),
        make_result(
            "sim_001",
            2000,
            "card_expired",
            "SEND_NEW_LINK",
            "still_failed",
            "simulated",
            "simulated_due_to_test_mode_cap",
            simulated=True,
        ),
        make_result(
            "failed_001",
            1000,
            "fraud_block",
            "ESCALATE_HUMAN",
            "escalated",
            "none",
            "ESCALATE_HUMAN",
        ),
    ]

    percentage = (
        reporter.combined_recovery_percentage(
            results
        )
    )

    assert percentage == 75.0


# ---------------------------------------------------------
# Failure reason breakdown
# ---------------------------------------------------------

def test_failure_reason_breakdown():
    reporter = RecoveryReporter()

    results = [
        make_result(
            "card_001",
            1000,
            "card_expired",
            "SEND_NEW_LINK",
            "recovered",
            "real",
            "PAYMENT_LINK_CREATED",
            real_api_call=True,
        ),
        make_result(
            "card_002",
            2000,
            "card_expired",
            "SEND_NEW_LINK",
            "still_failed",
            "simulated",
            "simulated_due_to_test_mode_cap",
            simulated=True,
        ),
        make_result(
            "fraud_001",
            3000,
            "fraud_block",
            "ESCALATE_HUMAN",
            "escalated",
            "none",
            "ESCALATE_HUMAN",
        ),
    ]

    breakdown = (
        reporter.failure_reason_breakdown(
            results
        )
    )

    assert (
        breakdown["card_expired"]["count"]
        == 2
    )

    assert (
        breakdown["card_expired"][
            "amount_at_risk"
        ]
        == 3000
    )

    assert (
        breakdown["card_expired"][
            "recovered_count"
        ]
        == 1
    )

    assert (
        breakdown["card_expired"][
            "real_recovered_amount"
        ]
        == 1000
    )

    assert (
        breakdown["fraud_block"]["count"]
        == 1
    )


# ---------------------------------------------------------
# Honest exceptions
# ---------------------------------------------------------

def test_exceptions_contains_only_escalated_or_blocked():
    reporter = RecoveryReporter()

    results = [
        make_result(
            "real_001",
            1000,
            "card_expired",
            "SEND_NEW_LINK",
            "recovered",
            "real",
            "PAYMENT_LINK_CREATED",
            real_api_call=True,
        ),
        make_result(
            "fraud_001",
            2000,
            "fraud_block",
            "ESCALATE_HUMAN",
            "escalated",
            "none",
            "ESCALATE_HUMAN",
        ),
        make_result(
            "blocked_001",
            3000,
            "bank_timeout",
            "DO_NOT_RETRY",
            "still_failed",
            "none",
            "DO_NOT_RETRY",
        ),
    ]

    exceptions = (
        reporter.exceptions(results)
    )

    assert len(exceptions) == 2

    exception_ids = {
        result["payment_id"]
        for result in exceptions
    }

    assert exception_ids == {
        "fraud_001",
        "blocked_001",
    }


# ---------------------------------------------------------
# Markdown report
# ---------------------------------------------------------

def test_markdown_report_contains_required_sections():
    reporter = RecoveryReporter()

    results = [
        make_result(
            "real_001",
            1000,
            "card_expired",
            "SEND_NEW_LINK",
            "recovered",
            "real",
            "PAYMENT_LINK_CREATED",
            real_api_call=True,
        ),
        make_result(
            "sim_001",
            2000,
            "card_expired",
            "SEND_NEW_LINK",
            "still_failed",
            "simulated",
            "simulated_due_to_test_mode_cap",
            simulated=True,
        ),
        make_result(
            "fraud_001",
            3000,
            "fraud_block",
            "ESCALATE_HUMAN",
            "escalated",
            "none",
            "ESCALATE_HUMAN",
        ),
    ]

    report = (
        reporter.generate_markdown(
            results
        )
    )

    required_sections = [
        "# Failed Payment Recovery Agent Report",
        "## 1. Executive Summary",
        "## 2. Recovery Classification",
        "## 3. Breakdown by Failure Reason",
        "## 4. Honest Exceptions",
        "## 5. Processing Outcomes",
        "## 6. Test Mode Limitation",
        "## 7. Stopping Rules",
        "## 8. Audit Trail",
    ]

    for section in required_sections:
        assert section in report


# ---------------------------------------------------------
# Report must distinguish real and simulated
# ---------------------------------------------------------

def test_report_never_blends_real_and_simulated_recovery():
    reporter = RecoveryReporter()

    results = [
        make_result(
            "real_001",
            1000,
            "card_expired",
            "SEND_NEW_LINK",
            "recovered",
            "real",
            "PAYMENT_LINK_CREATED",
            real_api_call=True,
        ),
        make_result(
            "sim_001",
            2000,
            "card_expired",
            "SEND_NEW_LINK",
            "still_failed",
            "simulated",
            "simulated_due_to_test_mode_cap",
            simulated=True,
        ),
    ]

    report = (
        reporter.generate_markdown(
            results
        )
    )

    assert (
        "Amount recovered via REAL API calls"
        in report
    )

    assert (
        "Amount marked as SIMULATED"
        in report
    )

    assert (
        "simulated_due_to_test_mode_cap"
        in report
    )

    assert (
        "NOT actual recovered revenue"
        in report
    )


# ---------------------------------------------------------
# Report file creation
# ---------------------------------------------------------

def test_report_can_be_saved(tmp_path):
    reporter = RecoveryReporter(
        output_directory=str(tmp_path)
    )

    results = [
        make_result(
            "save_001",
            1000,
            "card_expired",
            "SEND_NEW_LINK",
            "recovered",
            "real",
            "PAYMENT_LINK_CREATED",
            real_api_call=True,
        )
    ]

    report_path = reporter.save_report(
        results
    )

    assert isinstance(
        report_path,
        Path
    )

    assert report_path.exists()

    assert report_path.name == "report.md"

    content = report_path.read_text(
        encoding="utf-8"
    )

    assert (
        "# Failed Payment Recovery Agent Report"
        in content
    )