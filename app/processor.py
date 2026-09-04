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
    decide_checkout_recovery,
)

from app.models import CheckoutSession, FailedPayment
from app.razorpay_client import RazorpayClient


class PaymentProcessor:
    """
    Coordinates recovery decisions and execution.

    Real Razorpay Payment Link creation calls are capped by
    MAX_REAL_API_CALLS.

    IMPORTANT:
        Creating a Payment Link is NOT considered confirmed
        revenue recovery.

    A Payment Link becomes confirmed recovery only when
    Razorpay reports:

        status == "paid"
        AND
        amount_paid > 0

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

        # Counts real Payment Link creation attempts.
        #
        # Settlement status checks are tracked separately so
        # a GET status check does not consume a Payment Link
        # creation slot.
        self.real_api_calls = 0

        # Number of real settlement status checks.
        self.settlement_checks = 0

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
            "Real Razorpay Payment Link creation calls made: "
            f"{self.real_api_calls}"
        )

        print(
            "Razorpay settlement status checks made: "
            f"{self.settlement_checks}"
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
    # Checkout drop-off
    # -----------------------------------------------------

    @staticmethod
    def _simulate_checkout_followup(
        session: CheckoutSession,
    ) -> bool:
        """
        Simulate whether a customer returns after a checkout
        recovery reminder.

        This is deterministic so every demo run is reproducible.
        Even-numbered synthetic checkout IDs return and complete;
        odd-numbered IDs remain abandoned.

        IMPORTANT:
            This is synthetic demo behavior. A simulated checkout
            recovery is never counted as real Razorpay revenue.
        """

        try:
            checkout_number = int(
                session.checkout_id.rsplit("_", 1)[-1]
            )
        except (ValueError, IndexError):
            return False

        return checkout_number % 2 == 0

    def _write_checkout_audit(
        self,
        session: CheckoutSession,
        result: dict,
    ) -> None:
        """
        Write exactly one audit record for a checkout session.
        """

        self.audit_logger.log(
            payment_id=None,
            customer_name=None,
            email=None,
            amount=session.amount,
            failure_reason=None,
            payment_type="checkout",
            attempt_count=0,
            decision=result["decision"],
            decision_reason=result["reason"],
            action_taken=result["action_taken"],
            outcome=result["outcome"],
            recovery_type=result["recovery_type"],
            real_api_call=result["real_api_call"],
            simulated=result["simulated"],
            notes=result["notes"],
            record_type="checkout",
            checkout_id=session.checkout_id,
            customer_id=session.customer_id,
            currency=session.currency,
            started_at=session.started_at.isoformat(
                timespec="seconds"
            ),
            timestamp=result["timestamp"],
        )

    def process_checkout(
        self,
        session: CheckoutSession,
    ) -> dict:
        """
        Process one checkout session.

        Workflow:

            1. Observe checkout state.
            2. Decide whether recovery is appropriate.
            3. Send a reminder for an eligible drop-off.
            4. Simulate a customer return/completion event.
            5. Record the verified demo outcome.

        No payment is automatically charged.

        Simulated checkout recovery is clearly separated from
        real Razorpay settlement recovery.
        """

        decision = decide_checkout_recovery(session)

        result = {
            "timestamp": datetime.now().isoformat(
                timespec="seconds"
            ),
            "checkout_id": session.checkout_id,
            "customer_id": session.customer_id,
            "amount": session.amount,
            "currency": session.currency,
            "started_at": session.started_at.isoformat(
                timespec="seconds"
            ),
            "completed": session.completed,
            "decision": decision["action"],
            "reason": decision["reason"],
            "action_taken": None,
            "outcome": None,
            "recovery_type": "none",
            "real_api_call": False,
            "simulated": False,
            "customer_returned": False,
            "notes": None,
        }

        # -------------------------------------------------
        # Already completed
        # -------------------------------------------------

        if decision["action"] == "NO_ACTION":
            result.update(
                {
                    "action_taken": "NO_ACTION",
                    "outcome": "already_completed",
                    "notes": (
                        "Checkout was already completed. "
                        "No recovery action was required."
                    ),
                }
            )

            self._write_checkout_audit(
                session,
                result,
            )

            return result

        # -------------------------------------------------
        # Too recent
        # -------------------------------------------------

        if decision["action"] == "WAIT":
            result.update(
                {
                    "action_taken": "WAIT",
                    "outcome": "waiting",
                    "notes": (
                        "Checkout is too recent for recovery. "
                        "No reminder was sent."
                    ),
                }
            )

            self._write_checkout_audit(
                session,
                result,
            )

            return result

        # -------------------------------------------------
        # Abandoned checkout
        # -------------------------------------------------

        if decision["action"] == "SEND_CHECKOUT_REMINDER":
            customer_returned = (
                self._simulate_checkout_followup(
                    session
                )
            )

            result["action_taken"] = (
                "CHECKOUT_REMINDER_SENT"
            )
            result["customer_returned"] = (
                customer_returned
            )
            result["simulated"] = True

            if customer_returned:
                result.update(
                    {
                        "outcome": "checkout_recovered",
                        "recovery_type": "simulated",
                        "notes": (
                            "Recovery reminder was sent. "
                            "The synthetic customer returned "
                            "and completed checkout. This is "
                            "simulated recovery and is NOT "
                            "counted as real Razorpay revenue."
                        ),
                    }
                )
            else:
                result.update(
                    {
                        "outcome": "still_abandoned",
                        "recovery_type": "none",
                        "notes": (
                            "Recovery reminder was sent, but "
                            "the synthetic customer did not "
                            "return. No recovered revenue is "
                            "counted."
                        ),
                    }
                )

            self._write_checkout_audit(
                session,
                result,
            )

            return result

        # -------------------------------------------------
        # Safety fallback
        # -------------------------------------------------

        result.update(
            {
                "action_taken": "ESCALATE_HUMAN",
                "outcome": "escalated",
                "notes": (
                    "Unknown checkout recovery action. "
                    "Escalated for safety."
                ),
            }
        )

        self._write_checkout_audit(
            session,
            result,
        )

        return result

    def process_checkout_batch(
        self,
        sessions: list[CheckoutSession],
    ) -> list[dict]:
        """
        Process a batch of checkout sessions.
        """

        results = []

        print()
        print("=" * 70)
        print("CHECKOUT DROP-OFF RECOVERY")
        print("=" * 70)

        print(
            f"Checkout sessions to process: "
            f"{len(sessions)}"
        )

        print("=" * 70)

        for index, session in enumerate(
            sessions,
            start=1,
        ):
            result = self.process_checkout(
                session
            )

            results.append(result)

            print(
                f"[{index}/{len(sessions)}] "
                f"{session.checkout_id} | "
                f"₹{session.amount:.2f}"
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

            if result.get("customer_returned"):
                print(
                    "    Customer: RETURNED"
                )

        print("=" * 70)

        recovered = sum(
            1
            for result in results
            if result.get("outcome")
            == "checkout_recovered"
        )

        recovered_amount = sum(
            result["amount"]
            for result in results
            if result.get("outcome")
            == "checkout_recovered"
        )

        reminders = sum(
            1
            for result in results
            if result.get("action_taken")
            == "CHECKOUT_REMINDER_SENT"
        )

        still_abandoned = sum(
            1
            for result in results
            if result.get("outcome")
            == "still_abandoned"
        )

        print(
            f"Checkout reminders sent: {reminders}"
        )
        print(
            f"Customers returned: {recovered}"
        )
        print(
            f"Simulated checkout recovery: "
            f"₹{recovered_amount:.2f}"
        )
        print(
            f"Still abandoned: {still_abandoned}"
        )

        print("=" * 70)

        return results

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

        The workflow is now:

            1. Create Payment Link.
            2. Fetch Payment Link status.
            3. Confirm whether money was actually paid.

        IMPORTANT:

        A successful POST /payment_links response means
        only that the recovery action was triggered.

        It does NOT mean that revenue was recovered.

        Confirmed recovery requires Razorpay to report:

            status == "paid"
            AND
            amount_paid > 0

        Once the creation cap is reached, remaining
        Payment Link actions are explicitly simulated.
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
        # Make one real Payment Link creation call
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
        # Payment Link creation SUCCESS
        # -------------------------------------------------

        if api_result.get("success") is True:
            response_data = (
                api_result.get("data")
                or {}
            )

            payment_link_id = (
                response_data.get("id")
            )

            payment_link_url = (
                response_data.get("short_url")
            )

            result.update(
                {
                    "action_taken": (
                        "PAYMENT_LINK_CREATED"
                    ),

                    # IMPORTANT:
                    # Creating a link is not recovery.
                    "outcome": "awaiting_payment",

                    # Do NOT count this as recovered revenue.
                    "recovery_type": "none",

                    "real_api_call": True,
                    "simulated": False,

                    "payment_link": (
                        payment_link_url
                    ),

                    "payment_link_id": (
                        payment_link_id
                    ),

                    "settlement_status": (
                        "not_checked"
                    ),

                    "settlement_confirmed": (
                        False
                    ),

                    "settlement_amount_paid": (
                        0.0
                    ),

                    "settlement_payment_id": (
                        None
                    ),

                    "settlement_api_status_code": (
                        None
                    ),

                    "notes": (
                        "Razorpay TEST MODE Payment "
                        "Link was created successfully. "
                        "Payment recovery is NOT confirmed "
                        "until Razorpay reports the link "
                        "as paid."
                    ),
                }
            )

            # -------------------------------------------------
            # Confirmed settlement check
            # -------------------------------------------------

            if payment_link_id:

                settlement_result = (
                    self._check_payment_link_settlement(
                        payment_link_id
                    )
                )

                self._apply_settlement_result(
                    result=result,
                    settlement_result=(
                        settlement_result
                    ),
                )

            else:

                result.update(
                    {
                        "settlement_status": (
                            "missing_payment_link_id"
                        ),

                        "settlement_confirmed": (
                            False
                        ),

                        "notes": (
                            "Payment Link was created, "
                            "but Razorpay did not return "
                            "a Payment Link ID. "
                            "Confirmed recovery cannot "
                            "be established."
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
    # Settlement status check
    # -----------------------------------------------------

    def _check_payment_link_settlement(
        self,
        payment_link_id: str,
    ) -> dict:
        """
        Fetch the current Payment Link status from Razorpay.

        This is deliberately separate from the Payment Link
        creation cap.

        Why?

        The creation cap protects the number of real
        Payment Link creation actions.

        Settlement checks are read-only GET requests and
        are used to verify whether money was actually paid.
        """

        self.settlement_checks += 1

        try:

            return (
                self.razorpay_client
                .check_payment_link_settlement(
                    payment_link_id
                )
            )

        except Exception as exc:

            return {
                "success": False,
                "confirmed": False,
                "status": None,
                "amount": 0.0,
                "amount_paid": 0.0,
                "payment_link_id": (
                    payment_link_id
                ),
                "payment_id": None,
                "error": str(exc),
                "api_status_code": None,
                "api_response": None,
            }

    # -----------------------------------------------------
    # Apply settlement result
    # -----------------------------------------------------

    @staticmethod
    def _apply_settlement_result(
        result: dict,
        settlement_result: dict,
    ) -> None:
        """
        Apply normalized Razorpay settlement information
        to the processing result.

        Only a confirmed paid state becomes real recovery.
        """

        result["settlement_status"] = (
            settlement_result.get(
                "status"
            )
        )

        result["settlement_confirmed"] = (
            settlement_result.get(
                "confirmed",
                False
            )
        )

        result["settlement_amount"] = (
            settlement_result.get(
                "amount",
                0.0
            )
        )

        result["settlement_amount_paid"] = (
            settlement_result.get(
                "amount_paid",
                0.0
            )
        )

        result["settlement_payment_id"] = (
            settlement_result.get(
                "payment_id"
            )
        )

        result["settlement_api_status_code"] = (
            settlement_result.get(
                "api_status_code"
            )
        )

        result["settlement_error"] = (
            settlement_result.get(
                "error"
            )
        )

        result["settlement_api_response"] = (
            settlement_result.get(
                "api_response"
            )
        )

        # -------------------------------------------------
        # CONFIRMED SETTLEMENT
        # -------------------------------------------------

        if settlement_result.get(
            "confirmed"
        ) is True:

            result["outcome"] = (
                "confirmed_settlement"
            )

            result["recovery_type"] = (
                "real"
            )

            result["notes"] = (
                "Razorpay confirmed that the "
                "Payment Link was paid. "
                "This recovery is counted as "
                "confirmed recovered revenue."
            )

            return

        # -------------------------------------------------
        # PAYMENT NOT YET CONFIRMED
        # -------------------------------------------------

        result["outcome"] = (
            "awaiting_payment"
        )

        result["recovery_type"] = (
            "none"
        )

        if settlement_result.get(
            "success"
        ):

            result["notes"] = (
                "Payment Link was created successfully, "
                "but Razorpay has not confirmed payment. "
                "This amount is NOT counted as recovered "
                "revenue."
            )

        else:

            result["notes"] = (
                "Payment Link was created successfully, "
                "but the settlement status could not be "
                "confirmed. This amount is NOT counted "
                "as recovered revenue."
            )

    # -----------------------------------------------------
    # Re-check existing Payment Link
    # -----------------------------------------------------

    def check_existing_payment_link(
        self,
        payment_link_id: str,
    ) -> dict:
        """
        Public helper for checking an existing Payment Link.

        This can be used later by a scheduler, dashboard
        endpoint, or manual settlement verification command.

        It does NOT create a new Payment Link.
        """

        settlement_result = (
            self._check_payment_link_settlement(
                payment_link_id
            )
        )

        return settlement_result

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

            "payment_link_id": None,

            # -------------------------------------------------
            # Settlement tracking fields
            # -------------------------------------------------

            "settlement_status": (
                "not_applicable"
            ),

            "settlement_confirmed": (
                False
            ),

            "settlement_amount": (
                0.0
            ),

            "settlement_amount_paid": (
                0.0
            ),

            "settlement_payment_id": (
                None
            ),

            "settlement_api_status_code": (
                None
            ),

            "settlement_error": (
                None
            ),

            "settlement_api_response": (
                None
            ),

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

        Settlement fields are included in notes for now.

        The database schema will be upgraded separately so
        confirmed settlement data gets first-class columns.
        """

        notes = result.get(
            "notes"
        )

        settlement_status = result.get(
            "settlement_status"
        )

        settlement_confirmed = result.get(
            "settlement_confirmed"
        )

        settlement_amount_paid = result.get(
            "settlement_amount_paid",
            0.0
        )

        settlement_payment_id = result.get(
            "settlement_payment_id"
        )

        settlement_error = result.get(
            "settlement_error"
        )

        settlement_summary = (
            f" | Settlement status: "
            f"{settlement_status}; "
            f"confirmed: "
            f"{settlement_confirmed}; "
            f"amount paid: "
            f"₹{settlement_amount_paid:.2f}; "
            f"payment ID: "
            f"{settlement_payment_id or 'none'}"
        )

        if settlement_error:
            settlement_summary += (
                f"; settlement error: "
                f"{settlement_error}"
            )

        combined_notes = (
            f"{notes or ''}"
            f"{settlement_summary}"
        ).strip()

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
            notes=combined_notes,
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

        # -------------------------------------------------
        # Settlement information
        # -------------------------------------------------

        if result.get(
            "payment_link_id"
        ):

            print(
                f"    Link ID:  "
                f"{result['payment_link_id']}"
            )

            print(
                f"    Payment:  "
                f"{result.get('settlement_status')}"
            )

            print(
                f"    Confirmed: "
                f"{result.get('settlement_confirmed')}"
            )

            if result.get(
                "settlement_amount_paid",
                0.0
            ):

                print(
                    f"    Paid:     "
                    f"₹{result['settlement_amount_paid']:.2f}"
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