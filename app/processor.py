from datetime import datetime
from typing import Optional

from app.config import MAX_REAL_API_CALLS
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
from app.razorpay_client import RazorpayClient


class PaymentProcessor:
    """
    Coordinates recovery decisions and execution.

    Real Razorpay Payment Link calls are capped by
    MAX_REAL_API_CALLS.

    Real successful Payment Link creation is counted as
    real recovery.

    Simulated actions are never counted as real recovery.
    """

    def __init__(
        self,
        razorpay_client: Optional[RazorpayClient] = None,
        audit_logger=None,
        max_real_api_calls: Optional[int] = None,
    ):
        self.razorpay_client = (
            razorpay_client
            if razorpay_client is not None
            else RazorpayClient()
        )

        if audit_logger is None:
            from app.audit_logger import AuditLogger

            self.audit_logger = AuditLogger()
        else:
            self.audit_logger = audit_logger

        self.max_real_api_calls = (
            MAX_REAL_API_CALLS
            if max_real_api_calls is None
            else max_real_api_calls
        )

        self.real_api_calls = 0

    # -----------------------------------------------------
    # Batch processing
    # -----------------------------------------------------

    def process_batch(
        self,
        payments: list[FailedPayment],
    ) -> list[dict]:
        """
        Process the entire batch.
        """

        results = []

        print()
        print("=" * 70)
        print("FAILED PAYMENT RECOVERY AGENT")
        print("=" * 70)

        print(
            f"Records to process: {len(payments)}"
        )

        print(
            f"Real Payment Link API cap: "
            f"{self.max_real_api_calls}"
        )

        print("=" * 70)

        for index, payment in enumerate(
            payments,
            start=1,
        ):
            result = self.process_payment(
                payment
            )

            results.append(result)

            self._print_result(
                index=index,
                total=len(payments),
                payment=payment,
                result=result,
            )

        print("=" * 70)

        print(
            "Real Razorpay API calls made: "
            f"{self.real_api_calls}"
        )

        print("=" * 70)

        return results

    # -----------------------------------------------------
    # Single payment
    # -----------------------------------------------------

    def process_payment(
        self,
        payment: FailedPayment,
    ) -> dict:
        """
        Process one failed payment.
        """

        decision = decide(
            payment
        )

        result = self._base_result(
            payment=payment,
            decision=decision,
        )

        # -------------------------------------------------
        # DO_NOT_RETRY
        # -------------------------------------------------

        if decision.action == DO_NOT_RETRY:
            result.update(
                {
                    "action_taken": DO_NOT_RETRY,
                    "outcome": "still_failed",
                    "recovery_type": "none",
                    "real_api_call": False,
                    "simulated": False,
                    "notes": decision.reason,
                }
            )

            self._write_audit(
                payment,
                result,
            )

            return result

        # -------------------------------------------------
        # ESCALATE_HUMAN
        # -------------------------------------------------

        if decision.action == ESCALATE_HUMAN:
            result.update(
                {
                    "action_taken": ESCALATE_HUMAN,
                    "outcome": "escalated",
                    "recovery_type": "none",
                    "real_api_call": False,
                    "simulated": False,
                    "notes": decision.reason,
                }
            )

            self._write_audit(
                payment,
                result,
            )

            return result

        # -------------------------------------------------
        # RETRY_NOW
        # -------------------------------------------------

        if decision.action == RETRY_NOW:
            result.update(
                {
                    "action_taken": (
                        "RETRY_NOW_SCHEDULED"
                    ),
                    "outcome": "still_failed",
                    "recovery_type": "none",
                    "real_api_call": False,
                    "simulated": False,
                    "notes": (
                        "Immediate retry selected. "
                        "No silent duplicate charge "
                        "was performed."
                    ),
                }
            )

            self._write_audit(
                payment,
                result,
            )

            return result

        # -------------------------------------------------
        # RETRY_LATER
        # -------------------------------------------------

        if decision.action == RETRY_LATER:
            result.update(
                {
                    "action_taken": (
                        "RETRY_LATER_SCHEDULED"
                    ),
                    "outcome": "still_failed",
                    "recovery_type": "none",
                    "real_api_call": False,
                    "simulated": False,
                    "notes": (
                        f"Retry scheduled after "
                        f"{decision.delay_hours} hours."
                    ),
                }
            )

            self._write_audit(
                payment,
                result,
            )

            return result

        # -------------------------------------------------
        # SEND_REMINDER
        # -------------------------------------------------

        if decision.action == SEND_REMINDER:
            result.update(
                {
                    "action_taken": SEND_REMINDER,
                    "outcome": "still_failed",
                    "recovery_type": "none",
                    "real_api_call": False,
                    "simulated": False,
                    "notes": (
                        "Customer reminder selected. "
                        "No silent retry performed."
                    ),
                }
            )

            self._write_audit(
                payment,
                result,
            )

            return result

        # -------------------------------------------------
        # SEND_NEW_LINK
        # -------------------------------------------------

        if decision.action == SEND_NEW_LINK:
            return self._handle_new_payment_link(
                payment=payment,
                result=result,
            )

        # -------------------------------------------------
        # Unknown action
        # -------------------------------------------------

        result.update(
            {
                "action_taken": ESCALATE_HUMAN,
                "outcome": "escalated",
                "recovery_type": "none",
                "real_api_call": False,
                "simulated": False,
                "notes": (
                    "Unknown recovery action. "
                    "Escalated for safety."
                ),
            }
        )

        self._write_audit(
            payment,
            result,
        )

        return result

    # -----------------------------------------------------
    # Payment Link handling
    # -----------------------------------------------------

    def _handle_new_payment_link(
        self,
        payment: FailedPayment,
        result: dict,
    ) -> dict:
        """
        Execute SEND_NEW_LINK.

        A real API attempt consumes one slot from the
        configured real API cap.

        A successful HTTP response is real recovery.

        A failed API response is not recovery.

        Once the cap is reached, remaining records are
        explicitly simulated.
        """

        # -------------------------------------------------
        # Test-mode cap
        # -------------------------------------------------

        if (
            self.real_api_calls
            >= self.max_real_api_calls
        ):
            result.update(
                {
                    "action_taken": (
                        "simulated_due_to_test_mode_cap"
                    ),
                    "outcome": "still_failed",
                    "recovery_type": "simulated",
                    "real_api_call": False,
                    "simulated": True,
                    "notes": (
                        "Real Razorpay Payment Link "
                        "API cap reached. No API request "
                        "was made. This is a simulation "
                        "and is not counted as real "
                        "recovered revenue."
                    ),
                }
            )

            self._write_audit(
                payment,
                result,
            )

            return result

        # -------------------------------------------------
        # Make one real API call
        # -------------------------------------------------

        self.real_api_calls += 1

        api_result = (
            self.razorpay_client.create_payment_link(
                amount=payment.amount,
                customer_name=payment.customer_name,
                email=payment.email,
                phone=payment.phone,
                reference_id=payment.payment_id,
            )
        )

        result["api_request"] = (
            api_result.get("request")
        )

        result["api_response"] = (
            api_result.get("data")
        )

        result["api_status_code"] = (
            api_result.get("status_code")
        )

        # -------------------------------------------------
        # SUCCESS
        # -------------------------------------------------

        if api_result.get("success") is True:
            response_data = (
                api_result.get("data")
                or {}
            )

            result.update(
                {
                    "action_taken": (
                        "PAYMENT_LINK_CREATED"
                    ),
                    "outcome": "recovered",
                    "recovery_type": "real",
                    "real_api_call": True,
                    "simulated": False,
                    "payment_link": (
                        response_data.get(
                            "short_url"
                        )
                    ),
                    "notes": (
                        "Razorpay TEST MODE Payment "
                        "Link was created successfully."
                    ),
                }
            )

            self._write_audit(
                payment,
                result,
            )

            return result

        # -------------------------------------------------
        # RATE LIMIT
        # -------------------------------------------------

        if api_result.get(
            "status_code"
        ) == 429:
            result.update(
                {
                    "action_taken": (
                        "PAYMENT_LINK_API_RATE_LIMITED"
                    ),
                    "outcome": "still_failed",
                    "recovery_type": "none",
                    "real_api_call": True,
                    "simulated": False,
                    "notes": (
                        "Razorpay returned HTTP 429 "
                        "Too Many Requests. The real "
                        "API call consumed one cap slot, "
                        "but no recovery is counted."
                    ),
                }
            )

            self._write_audit(
                payment,
                result,
            )

            return result

        # -------------------------------------------------
        # EXISTING REFERENCE ID
        # -------------------------------------------------

        error_text = (
            api_result.get(
                "error"
            )
            or ""
        )

        if (
            "reference_id" in error_text
            and "already exists" in error_text
        ):
            result.update(
                {
                    "action_taken": (
                        "PAYMENT_LINK_ALREADY_EXISTS"
                    ),
                    "outcome": "still_failed",
                    "recovery_type": "none",
                    "real_api_call": True,
                    "simulated": False,
                    "notes": (
                        "Razorpay rejected the request "
                        "because a Payment Link already "
                        "exists for this reference_id. "
                        "No new recovery is counted."
                    ),
                }
            )

            self._write_audit(
                payment,
                result,
            )

            return result

        # -------------------------------------------------
        # OTHER API FAILURE
        # -------------------------------------------------

        result.update(
            {
                "action_taken": (
                    "PAYMENT_LINK_API_FAILED"
                ),
                "outcome": "still_failed",
                "recovery_type": "none",
                "real_api_call": True,
                "simulated": False,
                "notes": (
                    "A real Razorpay TEST MODE "
                    "Payment Link request was attempted "
                    "but failed. "
                    f"API error: "
                    f"{api_result.get('error')}"
                ),
            }
        )

        self._write_audit(
            payment,
            result,
        )

        return result

    # -----------------------------------------------------
    # Base result
    # -----------------------------------------------------

    @staticmethod
    def _base_result(
        payment: FailedPayment,
        decision,
    ) -> dict:
        """
        Create the common result structure.
        """

        return {
            "timestamp": (
                datetime.now().isoformat(
                    timespec="seconds"
                )
            ),
            "payment_id": payment.payment_id,
            "customer_name": (
                payment.customer_name
            ),
            "email": payment.email,
            "phone": payment.phone,
            "amount": payment.amount,
            "failure_reason": (
                payment.failure_reason
            ),
            "payment_type": (
                payment.payment_type
            ),
            "attempt_count": (
                payment.attempt_count
            ),
            "last_attempt_at": (
                payment.last_attempt_at
            ),
            "decision": decision.action,
            "reason": decision.reason,
            "delay_hours": (
                decision.delay_hours
            ),
            "action_taken": None,
            "api_request": None,
            "api_response": None,
            "api_status_code": None,
            "outcome": None,
            "recovery_type": "none",
            "real_api_call": False,
            "simulated": False,
            "payment_link": None,
            "notes": None,
        }

    # -----------------------------------------------------
    # Audit
    # -----------------------------------------------------

    def _write_audit(
        self,
        payment: FailedPayment,
        result: dict,
    ) -> None:
        """
        Write one audit record.
        """

        self.audit_logger.log(
            payment_id=payment.payment_id,
            customer_name=payment.customer_name,
            email=payment.email,
            amount=payment.amount,
            failure_reason=payment.failure_reason,
            payment_type=payment.payment_type,
            attempt_count=payment.attempt_count,
            decision=result["decision"],
            decision_reason=result["reason"],
            action_taken=result["action_taken"],
            api_request=result["api_request"],
            api_response=result["api_response"],
            api_status_code=result[
                "api_status_code"
            ],
            outcome=result["outcome"],
            notes=result["notes"],
            recovery_type=result[
                "recovery_type"
            ],
            real_api_call=result[
                "real_api_call"
            ],
            simulated=result[
                "simulated"
            ],
            timestamp=result["timestamp"],
        )

    # -----------------------------------------------------
    # Console output
    # -----------------------------------------------------

    def _print_result(
        self,
        index: int,
        total: int,
        payment: FailedPayment,
        result: dict,
    ) -> None:
        """
        Print one processing result.
        """

        print(
            f"[{index}/{total}] "
            f"{payment.payment_id} | "
            f"{payment.failure_reason} | "
            f"₹{payment.amount:.2f}"
        )

        print(
            f"    Decision: "
            f"{result['decision']}"
        )

        print(
            f"    Action:   "
            f"{result['action_taken']}"
        )

        print(
            f"    Outcome:  "
            f"{result['outcome']}"
        )

        if result.get(
            "recovery_type"
        ) == "real":
            print(
                f"    Real API calls: "
                f"{self.real_api_calls}/"
                f"{self.max_real_api_calls}"
            )

        if result.get(
            "recovery_type"
        ) == "simulated":
            print(
                "    Simulation: "
                "Test Mode API cap reached"
            )