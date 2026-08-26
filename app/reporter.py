from collections import defaultdict
from pathlib import Path
from typing import Optional

from app.config import OUTPUT_DIR


class RecoveryReporter:
    """
    Generates the final recovery report.

    IMPORTANT:
    Real API recoveries and simulated recoveries are always
    reported separately.

    A simulated recovery is NEVER included in the real
    recovery amount.
    """

    def __init__(
        self,
        output_directory: Optional[str] = None,
    ):
        if output_directory is None:
            self.output_directory = Path(
                OUTPUT_DIR
            )
        else:
            self.output_directory = Path(
                output_directory
            )

        self.output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    # -----------------------------------------------------
    # Basic calculations
    # -----------------------------------------------------

    @staticmethod
    def total_amount_at_risk(
        results: list[dict],
    ) -> float:
        """
        Sum the amount of every failed payment in the batch.
        """

        return sum(
            float(result["amount"])
            for result in results
        )

    @staticmethod
    def real_recovery_amount(
        results: list[dict],
    ) -> float:
        """
        Sum amounts belonging ONLY to successful real
        Razorpay API recovery operations.
        """

        return sum(
            float(result["amount"])
            for result in results
            if (
                result.get("recovery_type")
                == "real"
                and result.get("outcome")
                == "recovered"
            )
        )

    @staticmethod
    def simulated_recovery_amount(
        results: list[dict],
    ) -> float:
        """
        Sum amounts belonging to records that were explicitly
        marked as simulated because the real API cap was hit.

        These are NOT actual recoveries.
        """

        return sum(
            float(result["amount"])
            for result in results
            if (
                result.get("recovery_type")
                == "simulated"
            )
        )

    @staticmethod
    def real_recovery_count(
        results: list[dict],
    ) -> int:
        """
        Count successful real API recovery operations.
        """

        return sum(
            1
            for result in results
            if (
                result.get("recovery_type")
                == "real"
                and result.get("outcome")
                == "recovered"
            )
        )

    @staticmethod
    def simulated_recovery_count(
        results: list[dict],
    ) -> int:
        """
        Count explicitly simulated recovery actions.
        """

        return sum(
            1
            for result in results
            if result.get("recovery_type")
            == "simulated"
        )

    # -----------------------------------------------------
    # Recovery percentages
    # -----------------------------------------------------

    @classmethod
    def real_recovery_percentage(
        cls,
        results: list[dict],
    ) -> float:
        """
        Calculate real recovery percentage.

        Formula:

            real recovered amount
            --------------------- × 100
            total amount at risk
        """

        total_risk = cls.total_amount_at_risk(
            results
        )

        if total_risk == 0:
            return 0.0

        return (
            cls.real_recovery_amount(results)
            / total_risk
        ) * 100

    @classmethod
    def combined_recovery_percentage(
        cls,
        results: list[dict],
    ) -> float:
        """
        Calculate a clearly labeled combined percentage.

        IMPORTANT:
        This is NOT actual recovered revenue.

        It represents:
            real recovery amount
            + simulated amount

        divided by total amount at risk.

        The report explicitly labels this as a simulated/
        hypothetical combined metric.
        """

        total_risk = cls.total_amount_at_risk(
            results
        )

        if total_risk == 0:
            return 0.0

        combined_amount = (
            cls.real_recovery_amount(results)
            + cls.simulated_recovery_amount(results)
        )

        return (
            combined_amount
            / total_risk
        ) * 100

    # -----------------------------------------------------
    # Failure reason breakdown
    # -----------------------------------------------------

    @staticmethod
    def failure_reason_breakdown(
        results: list[dict],
    ) -> dict:
        """
        Build recovery statistics grouped by failure reason.
        """

        breakdown = defaultdict(
            lambda: {
                "count": 0,
                "recovered_count": 0,
                "amount_at_risk": 0.0,
                "real_recovered_amount": 0.0,
            }
        )

        for result in results:
            reason = result[
                "failure_reason"
            ]

            amount = float(
                result["amount"]
            )

            breakdown[reason]["count"] += 1

            breakdown[reason][
                "amount_at_risk"
            ] += amount

            if (
                result.get("recovery_type")
                == "real"
                and result.get("outcome")
                == "recovered"
            ):
                breakdown[reason][
                    "recovered_count"
                ] += 1

                breakdown[reason][
                    "real_recovered_amount"
                ] += amount

        return dict(breakdown)

    # -----------------------------------------------------
    # Exceptions
    # -----------------------------------------------------

    @staticmethod
    def exceptions(
        results: list[dict],
    ) -> list[dict]:
        """
        Return records that require human escalation or
        cannot be retried automatically.
        """

        return [
            result
            for result in results
            if result.get("decision")
            in {
                "ESCALATE_HUMAN",
                "DO_NOT_RETRY",
            }
        ]

    # -----------------------------------------------------
    # Markdown report
    # -----------------------------------------------------

    def generate_markdown(
        self,
        results: list[dict],
    ) -> str:
        """
        Generate the complete Markdown report.
        """

        total_records = len(results)

        total_risk = (
            self.total_amount_at_risk(
                results
            )
        )

        real_amount = (
            self.real_recovery_amount(
                results
            )
        )

        simulated_amount = (
            self.simulated_recovery_amount(
                results
            )
        )

        real_count = (
            self.real_recovery_count(
                results
            )
        )

        simulated_count = (
            self.simulated_recovery_count(
                results
            )
        )

        real_percentage = (
            self.real_recovery_percentage(
                results
            )
        )

        combined_percentage = (
            self.combined_recovery_percentage(
                results
            )
        )

        breakdown = (
            self.failure_reason_breakdown(
                results
            )
        )

        exceptions = (
            self.exceptions(results)
        )

        lines = []

        # -------------------------------------------------
        # Header
        # -------------------------------------------------

        lines.append(
            "# Failed Payment Recovery Agent Report"
        )

        lines.append("")

        lines.append(
            "> **TEST MODE REPORT** — "
            "Real Razorpay API recoveries and simulated "
            "recoveries are reported separately."
        )

        lines.append("")

        # -------------------------------------------------
        # Executive summary
        # -------------------------------------------------

        lines.append(
            "## 1. Executive Summary"
        )

        lines.append("")

        lines.append(
            f"- **Payments processed:** "
            f"{total_records}"
        )

        lines.append(
            f"- **Total amount at risk:** "
            f"₹{total_risk:,.2f}"
        )

        lines.append(
            f"- **Amount recovered via REAL API calls:** "
            f"₹{real_amount:,.2f} "
            f"({real_count} records)"
        )

        lines.append(
            f"- **Amount marked as SIMULATED:** "
            f"₹{simulated_amount:,.2f} "
            f"({simulated_count} records)"
        )

        lines.append(
            f"- **REAL recovery rate:** "
            f"{real_percentage:.2f}%"
        )

        lines.append(
            f"- **Combined real + simulated rate:** "
            f"{combined_percentage:.2f}%"
        )

        lines.append("")

        lines.append(
            "**Important:** The simulated amount is "
            "NOT actual recovered revenue. It represents "
            "SEND_NEW_LINK actions that could not make a "
            "real Razorpay API call because the configured "
            "Test Mode API cap was reached."
        )

        lines.append("")

        # -------------------------------------------------
        # Recovery definitions
        # -------------------------------------------------

        lines.append(
            "## 2. Recovery Classification"
        )

        lines.append("")

        lines.append(
            "| Classification | Meaning | Included in REAL recovery? |"
        )

        lines.append(
            "|---|---|---|"
        )

        lines.append(
            "| REAL | Razorpay TEST MODE Payment Link API call succeeded | Yes |"
        )

        lines.append(
            "| SIMULATED | API cap prevented the real call | No |"
        )

        lines.append(
            "| NONE | No recovery operation succeeded | No |"
        )

        lines.append("")

        # -------------------------------------------------
        # Failure reason breakdown
        # -------------------------------------------------

        lines.append(
            "## 3. Breakdown by Failure Reason"
        )

        lines.append("")

        lines.append(
            "| Failure Reason | Count | "
            "Amount at Risk | Real Recoveries | "
            "Real Recovery Rate |"
        )

        lines.append(
            "|---|---:|---:|---:|---:|"
        )

        for reason in sorted(
            breakdown.keys()
        ):
            stats = breakdown[reason]

            count = stats["count"]

            recovered_count = (
                stats["recovered_count"]
            )

            amount_at_risk = (
                stats["amount_at_risk"]
            )

            recovered_amount = (
                stats["real_recovered_amount"]
            )

            if amount_at_risk == 0:
                recovery_rate = 0.0
            else:
                recovery_rate = (
                    recovered_amount
                    / amount_at_risk
                ) * 100

            lines.append(
                f"| {reason} | "
                f"{count} | "
                f"₹{amount_at_risk:,.2f} | "
                f"{recovered_count} | "
                f"{recovery_rate:.2f}% |"
            )

        lines.append("")

        # -------------------------------------------------
        # Exceptions
        # -------------------------------------------------

        lines.append(
            "## 4. Honest Exceptions"
        )

        lines.append("")

        lines.append(
            "These records were either escalated to a human "
            "or blocked from further automatic retry."
        )

        lines.append("")

        if not exceptions:
            lines.append(
                "No ESCALATE_HUMAN or DO_NOT_RETRY records "
                "were present in this batch."
            )
        else:
            lines.append(
                "| Payment ID | Failure Reason | "
                "Amount | Decision | Reason |"
            )

            lines.append(
                "|---|---|---:|---|---|"
            )

            for result in exceptions:
                reason = (
                    result.get("reason")
                    or "No reason provided"
                )

                # Prevent a pipe character inside the
                # reason from breaking the Markdown table.
                reason = reason.replace(
                    "|",
                    "\\|",
                )

                lines.append(
                    f"| {result['payment_id']} | "
                    f"{result['failure_reason']} | "
                    f"₹{float(result['amount']):,.2f} | "
                    f"{result['decision']} | "
                    f"{reason} |"
                )

        lines.append("")

        # -------------------------------------------------
        # Processing outcomes
        # -------------------------------------------------

        lines.append(
            "## 5. Processing Outcomes"
        )

        lines.append("")

        outcome_counts = defaultdict(int)

        for result in results:
            outcome_counts[
                result.get(
                    "outcome",
                    "unknown",
                )
            ] += 1

        lines.append(
            "| Outcome | Count |"
        )

        lines.append(
            "|---|---:|"
        )

        for outcome in sorted(
            outcome_counts.keys()
        ):
            lines.append(
                f"| {outcome} | "
                f"{outcome_counts[outcome]} |"
            )

        lines.append("")

        # -------------------------------------------------
        # Test Mode limitation
        # -------------------------------------------------

        lines.append(
            "## 6. Test Mode Limitation"
        )

        lines.append("")

        lines.append(
            "The application intentionally limits real "
            "Razorpay Payment Link API calls using "
            "`MAX_REAL_API_CALLS` from `.env`."
        )

        lines.append("")

        lines.append(
            "When the cap is reached, remaining "
            "`SEND_NEW_LINK` decisions are marked "
            "`simulated_due_to_test_mode_cap` in the "
            "audit trail. They are **not** sent to Razorpay "
            "and are **not** counted as real recovered revenue."
        )

        lines.append("")

        lines.append(
            "This is a deliberate test-mode safety mechanism "
            "and is reported openly rather than hidden."
        )

        lines.append("")

        # -------------------------------------------------
        # Stopping rules
        # -------------------------------------------------

        lines.append(
            "## 7. Stopping Rules"
        )

        lines.append("")

        lines.append(
            "1. **Maximum 3 attempts:** Any payment with "
            "`attempt_count >= 3` receives `DO_NOT_RETRY`."
        )

        lines.append(
            "2. **10-minute retry cooldown:** A payment "
            "attempted within the previous 10 minutes is "
            "blocked from automatic retry."
        )

        lines.append(
            "3. **Fraud escalation:** `fraud_block` is "
            "immediately escalated and never automatically "
            "retried."
        )

        lines.append("")

        # -------------------------------------------------
        # Audit information
        # -------------------------------------------------

        lines.append(
            "## 8. Audit Trail"
        )

        lines.append("")

        lines.append(
            "Every processed payment is stored in the "
            "SQLite audit database with timestamp, payment "
            "information, failure reason, decision, action, "
            "API request/response, outcome, and recovery "
            "classification."
        )

        lines.append("")

        lines.append(
            "The audit database is the explainability layer "
            "for the recovery decisions."
        )

        lines.append("")

        return "\n".join(lines)

    # -----------------------------------------------------
    # Save report
    # -----------------------------------------------------

    def save_report(
        self,
        results: list[dict],
        filename: str = "report.md",
    ) -> Path:
        """
        Generate and save the Markdown report.
        """

        report = self.generate_markdown(
            results
        )

        report_path = (
            self.output_directory
            / filename
        )

        report_path.write_text(
            report,
            encoding="utf-8",
        )

        return report_path

    # -----------------------------------------------------
    # Console summary
    # -----------------------------------------------------

    def print_summary(
        self,
        results: list[dict],
    ) -> None:
        """
        Print the key final metrics to the terminal.
        """

        total_risk = (
            self.total_amount_at_risk(
                results
            )
        )

        real_amount = (
            self.real_recovery_amount(
                results
            )
        )

        simulated_amount = (
            self.simulated_recovery_amount(
                results
            )
        )

        real_count = (
            self.real_recovery_count(
                results
            )
        )

        simulated_count = (
            self.simulated_recovery_count(
                results
            )
        )

        real_percentage = (
            self.real_recovery_percentage(
                results
            )
        )

        combined_percentage = (
            self.combined_recovery_percentage(
                results
            )
        )

        exceptions = (
            self.exceptions(results)
        )

        print()
        print("=" * 70)
        print("FINAL RECOVERY REPORT")
        print("=" * 70)

        print(
            f"Total amount at risk: "
            f"₹{total_risk:,.2f}"
        )

        print(
            f"REAL API recoveries: "
            f"₹{real_amount:,.2f} "
            f"({real_count} records)"
        )

        print(
            f"SIMULATED recoveries: "
            f"₹{simulated_amount:,.2f} "
            f"({simulated_count} records)"
        )

        print(
            f"REAL recovery rate: "
            f"{real_percentage:.2f}%"
        )

        print(
            f"Combined real + simulated rate: "
            f"{combined_percentage:.2f}%"
        )

        print(
            f"Honest exceptions: "
            f"{len(exceptions)}"
        )

        print("=" * 70)


# ---------------------------------------------------------
# Direct execution test
# ---------------------------------------------------------

if __name__ == "__main__":
    reporter = RecoveryReporter()

    test_results = [
        {
            "payment_id": "report_test_001",
            "customer_name": "Test Customer",
            "email": "test@example.com",
            "phone": "9876543210",
            "amount": 1000.00,
            "failure_reason": "card_expired",
            "payment_type": "one-time",
            "attempt_count": 1,
            "decision": "SEND_NEW_LINK",
            "action_taken": "PAYMENT_LINK_CREATED",
            "outcome": "recovered",
            "recovery_type": "real",
            "real_api_call": True,
            "simulated": False,
            "reason": "Test real recovery",
        },
        {
            "payment_id": "report_test_002",
            "customer_name": "Test Customer 2",
            "email": "test2@example.com",
            "phone": "9876543211",
            "amount": 2000.00,
            "failure_reason": "card_expired",
            "payment_type": "one-time",
            "attempt_count": 1,
            "decision": "SEND_NEW_LINK",
            "action_taken": (
                "simulated_due_to_test_mode_cap"
            ),
            "outcome": "still_failed",
            "recovery_type": "simulated",
            "real_api_call": False,
            "simulated": True,
            "reason": (
                "Test Mode API cap reached"
            ),
        },
        {
            "payment_id": "report_test_003",
            "customer_name": "Test Customer 3",
            "email": "test3@example.com",
            "phone": "9876543212",
            "amount": 3000.00,
            "failure_reason": "fraud_block",
            "payment_type": "one-time",
            "attempt_count": 1,
            "decision": "ESCALATE_HUMAN",
            "action_taken": "ESCALATE_HUMAN",
            "outcome": "escalated",
            "recovery_type": "none",
            "real_api_call": False,
            "simulated": False,
            "reason": (
                "Fraud-blocked payment requires "
                "human review."
            ),
        },
    ]

    report_path = reporter.save_report(
        test_results
    )

    reporter.print_summary(
        test_results
    )

    print()
    print(
        f"Report saved to: {report_path}"
    )