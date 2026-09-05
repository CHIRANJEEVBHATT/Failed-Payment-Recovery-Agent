from datetime import datetime
from typing import Optional

from app.config import MAX_REAL_API_CALLS
from app.decision_engine import (
    DO_NOT_RETRY,
    ESCALATE_ACCOUNT,
    ESCALATE_B2B_HUMAN,
    ESCALATE_HUMAN,
    PTP_ESCALATE_ACCOUNT,
    PTP_ESCALATE_HUMAN,
    PTP_PAYMENT_REMINDER,
    PTP_STRONGER_REMINDER,
    PTP_WAIT,
    RETRY_LATER,
    RETRY_NOW,
    SEND_B2B_REMINDER,
    SEND_B2B_STRONGER_REMINDER,
    SEND_NEW_LINK,
    SEND_REMINDER,
    decide,
    decide_b2b_recovery,
    decide_checkout_recovery,
    decide_promise_to_pay,
)
from app.models import (
    B2BReceivable,
    CheckoutSession,
    FailedPayment,
    PromiseToPay,
)
from app.razorpay_client import RazorpayClient


class PaymentProcessor:
    """
    Coordinates recovery decisions and execution.

    Supports:
        - Failed payment recovery
        - Checkout drop-off recovery
        - B2B receivable recovery

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
        self.settlement_checks = 0

    # =====================================================
    # Failed Payment Processing
    # =====================================================

    def process_batch(
        self,
        payments: list[FailedPayment],
    ) -> list[dict]:
        """
        Process the entire failed-payment batch.
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

    def process_payment(
        self,
        payment: FailedPayment,
    ) -> dict:
        """
        Process one failed payment.
        """

        decision = decide(payment)

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
                    "action_taken": "RETRY_NOW_SCHEDULED",
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
                    "action_taken": "RETRY_LATER_SCHEDULED",
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

    # =====================================================
    # Checkout Drop-off
    # =====================================================

    @staticmethod
    def _simulate_checkout_followup(
        session: CheckoutSession,
    ) -> bool:
        """
        Simulate whether a customer returns after a
        checkout recovery reminder.

        Even-numbered synthetic checkout IDs return.
        Odd-numbered IDs remain abandoned.

        This is synthetic demo behavior and is never
        counted as real Razorpay revenue.
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
        Write exactly one audit record for a checkout.
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
        """

        decision = decide_checkout_recovery(
            session
        )

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

    # =====================================================
    # B2B Receivable Processing
    # =====================================================

    def _write_b2b_audit(
        self,
        receivable: B2BReceivable,
        result: dict,
    ) -> None:
        """
        Write exactly one audit record for a B2B receivable.
        """

        self.audit_logger.log(
            payment_id=None,
            customer_name=receivable.company_name,
            email=None,
            amount=receivable.amount,
            failure_reason="b2b_overdue",
            payment_type="b2b",
            attempt_count=receivable.previous_reminders,
            decision=result["decision"],
            decision_reason=result["reason"],
            action_taken=result["action_taken"],
            outcome=result["outcome"],
            recovery_type=result["recovery_type"],
            real_api_call=False,
            simulated=True,
            notes=result["notes"],
            record_type="b2b",
            customer_id=receivable.customer_id,
            currency=receivable.currency,
            started_at=receivable.due_date.isoformat(
                timespec="seconds"
            ),
            invoice_id=receivable.invoice_id,
            company_name=receivable.company_name,
            due_date=receivable.due_date.isoformat(
                timespec="seconds"
            ),
            days_overdue=receivable.days_overdue,
            payment_status=receivable.payment_status,
            previous_reminders=receivable.previous_reminders,
            promised_payment_date=(
                receivable.promised_payment_date.isoformat(
                    timespec="seconds"
                )
                if receivable.promised_payment_date
                else None
            ),
            paid_at=(
                receivable.paid_at.isoformat(
                    timespec="seconds"
                )
                if receivable.paid_at
                else None
            ),
            timestamp=result["timestamp"],
        )

    def process_b2b(
        self,
        receivable: B2BReceivable,
    ) -> dict:
        """
        Process one B2B receivable.

        This version simulates collection actions only.
        No automatic money movement is performed.

        IMPORTANT:
            A reminder or escalation is NOT counted as
            recovered revenue.
        """

        decision = decide_b2b_recovery(
            receivable
        )

        result = {
            "timestamp": datetime.now().isoformat(
                timespec="seconds"
            ),
            "invoice_id": receivable.invoice_id,
            "company_name": receivable.company_name,
            "customer_id": receivable.customer_id,
            "amount": receivable.amount,
            "currency": receivable.currency,
            "due_date": receivable.due_date.isoformat(
                timespec="seconds"
            ),
            "days_overdue": receivable.days_overdue,
            "payment_status": receivable.payment_status,
            "previous_reminders": receivable.previous_reminders,
            "decision": decision.action,
            "reason": decision.reason,
            "action_taken": None,
            "outcome": None,
            "recovery_type": "none",
            "real_api_call": False,
            "simulated": True,
            "notes": None,
        }

        # -------------------------------------------------
        # Already paid
        # -------------------------------------------------

        if decision.action == "NO_ACTION":
            result.update(
                {
                    "action_taken": "NO_ACTION",
                    "outcome": "already_paid",
                    "recovery_type": "none",
                    "simulated": False,
                    "notes": (
                        "B2B invoice is already marked as "
                        "paid. No recovery action required."
                    ),
                }
            )

            self._write_b2b_audit(
                receivable,
                result,
            )

            return result

        # -------------------------------------------------
        # Not overdue
        # -------------------------------------------------

        if decision.action == "WAIT":
            result.update(
                {
                    "action_taken": "WAIT",
                    "outcome": "waiting",
                    "notes": (
                        "Invoice is not overdue yet. "
                        "No collection action was performed."
                    ),
                }
            )

            self._write_b2b_audit(
                receivable,
                result,
            )

            return result

        # -------------------------------------------------
        # Standard reminder
        # -------------------------------------------------

        if decision.action == SEND_B2B_REMINDER:
            result.update(
                {
                    "action_taken": "B2B_REMINDER_SENT",
                    "outcome": "still_outstanding",
                    "recovery_type": "none",
                    "notes": (
                        "Standard B2B payment reminder "
                        "selected for an invoice 1-7 days "
                        "overdue. No payment is counted "
                        "as recovered."
                    ),
                }
            )

            self._write_b2b_audit(
                receivable,
                result,
            )

            return result

        # -------------------------------------------------
        # Stronger reminder
        # -------------------------------------------------

        if decision.action == SEND_B2B_STRONGER_REMINDER:
            result.update(
                {
                    "action_taken": (
                        "B2B_STRONGER_REMINDER_SENT"
                    ),
                    "outcome": "still_outstanding",
                    "recovery_type": "none",
                    "notes": (
                        "Stronger B2B payment reminder "
                        "selected for an invoice 8-15 days "
                        "overdue. No payment is counted "
                        "as recovered."
                    ),
                }
            )

            self._write_b2b_audit(
                receivable,
                result,
            )

            return result

        # -------------------------------------------------
        # Account escalation
        # -------------------------------------------------

        if decision.action == ESCALATE_ACCOUNT:
            result.update(
                {
                    "action_taken": ESCALATE_ACCOUNT,
                    "outcome": "escalated_account",
                    "recovery_type": "none",
                    "notes": (
                        "B2B invoice is 16-30 days overdue. "
                        "Escalated to the account owner for "
                        "direct customer follow-up."
                    ),
                }
            )

            self._write_b2b_audit(
                receivable,
                result,
            )

            return result

        # -------------------------------------------------
        # Human escalation
        # -------------------------------------------------

        if decision.action == ESCALATE_B2B_HUMAN:
            result.update(
                {
                    "action_taken": ESCALATE_B2B_HUMAN,
                    "outcome": "escalated",
                    "recovery_type": "none",
                    "notes": (
                        "B2B invoice is more than 30 days "
                        "overdue. Automatic collection "
                        "actions stop and human review is "
                        "required."
                    ),
                }
            )

            self._write_b2b_audit(
                receivable,
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
                "recovery_type": "none",
                "notes": (
                    "Unknown B2B recovery action. "
                    "Escalated for safety."
                ),
            }
        )

        self._write_b2b_audit(
            receivable,
            result,
        )

        return result

    def process_b2b_batch(
        self,
        receivables: list[B2BReceivable],
    ) -> list[dict]:
        """
        Process a batch of B2B receivables.
        """

        results = []

        print()
        print("=" * 70)
        print("B2B RECEIVABLE RECOVERY")
        print("=" * 70)

        print(
            f"B2B invoices to process: "
            f"{len(receivables)}"
        )

        total_outstanding = sum(
            receivable.amount
            for receivable in receivables
            if receivable.payment_status.lower()
            != "paid"
        )

        print(
            f"Outstanding amount at risk: "
            f"₹{total_outstanding:.2f}"
        )

        print("=" * 70)

        for index, receivable in enumerate(
            receivables,
            start=1,
        ):
            result = self.process_b2b(
                receivable
            )

            results.append(result)

            print(
                f"[{index}/{len(receivables)}] "
                f"{receivable.invoice_id} | "
                f"{receivable.company_name} | "
                f"₹{receivable.amount:.2f}"
            )

            print(
                f"    Days overdue: "
                f"{receivable.days_overdue}"
            )

            print(
                f"    Decision:     "
                f"{result['decision']}"
            )

            print(
                f"    Action:       "
                f"{result['action_taken']}"
            )

            print(
                f"    Outcome:      "
                f"{result['outcome']}"
            )

        print("=" * 70)

        reminders = sum(
            1
            for result in results
            if result["action_taken"]
            == "B2B_REMINDER_SENT"
        )

        stronger_reminders = sum(
            1
            for result in results
            if result["action_taken"]
            == "B2B_STRONGER_REMINDER_SENT"
        )

        account_escalations = sum(
            1
            for result in results
            if result["action_taken"]
            == ESCALATE_ACCOUNT
        )

        human_escalations = sum(
            1
            for result in results
            if result["action_taken"]
            == ESCALATE_B2B_HUMAN
        )

        still_outstanding = sum(
            result["amount"]
            for result in results
            if result["outcome"]
            == "still_outstanding"
        )

        print(
            f"B2B standard reminders: "
            f"{reminders}"
        )

        print(
            f"B2B stronger reminders: "
            f"{stronger_reminders}"
        )

        print(
            f"Account escalations: "
            f"{account_escalations}"
        )

        print(
            f"Human escalations: "
            f"{human_escalations}"
        )

        print(
            f"Still outstanding: "
            f"₹{still_outstanding:.2f}"
        )

        print(
            "Confirmed B2B recovered revenue: "
            "₹0.00"
        )

        print("=" * 70)

        return results
        # =====================================================
    # Promise-to-Pay Processing
    # =====================================================

    def _write_promise_to_pay_audit(
        self,
        promise: PromiseToPay,
        result: dict,
    ) -> None:
        """
        Write exactly one audit record for a
        Promise-to-Pay record.
        """

        self.audit_logger.log(
            payment_id=None,
            customer_name=promise.customer_name,
            email=None,
            amount=promise.amount,
            failure_reason="promise_to_pay",
            payment_type="promise_to_pay",
            attempt_count=promise.previous_missed_promises,
            decision=result["decision"],
            decision_reason=result["reason"],
            action_taken=result["action_taken"],
            outcome=result["outcome"],
            recovery_type=result["recovery_type"],
            real_api_call=False,
            simulated=True,
            notes=result["notes"],
            record_type="promise_to_pay",
            customer_id=promise.customer_id,
            currency=promise.currency,
            started_at=promise.created_at.isoformat(
                timespec="seconds"
            ),
            promised_payment_date=(
                promise.promised_date.isoformat(
                    timespec="seconds"
                )
            ),
            paid_at=(
                promise.paid_at.isoformat(
                    timespec="seconds"
                )
                if promise.paid_at
                else None
            ),
            timestamp=result["timestamp"],
            promise_id=promise.promise_id,
            promise_status=promise.status,
            previous_missed_promises=(
                promise.previous_missed_promises
            ),
            contact_channel=promise.contact_channel,
        )

    def process_promise_to_pay(
        self,
        promise: PromiseToPay,
    ) -> dict:
        """
        Process one Promise-to-Pay record.

        Follow-up actions are simulated only.

        IMPORTANT:

            Sending a reminder or escalating a promise
            is NOT considered recovered revenue.

            Actual recovery requires a confirmed payment.
        """

        decision = decide_promise_to_pay(
            promise
        )

        result = {
            "timestamp": datetime.now().isoformat(
                timespec="seconds"
            ),
            "promise_id": promise.promise_id,
            "customer_id": promise.customer_id,
            "customer_name": promise.customer_name,
            "amount": promise.amount,
            "currency": promise.currency,
            "promised_date": (
                promise.promised_date.isoformat(
                    timespec="seconds"
                )
            ),
            "created_at": (
                promise.created_at.isoformat(
                    timespec="seconds"
                )
            ),
            "status": promise.status,
            "previous_missed_promises": (
                promise.previous_missed_promises
            ),
            "contact_channel": promise.contact_channel,
            "decision": decision.action,
            "reason": decision.reason,
            "action_taken": None,
            "outcome": None,
            "recovery_type": "none",
            "real_api_call": False,
            "simulated": True,
            "notes": None,
        }

        # -------------------------------------------------
        # Already paid
        # -------------------------------------------------

        if decision.action == "NO_ACTION":
            result.update(
                {
                    "action_taken": "NO_ACTION",
                    "outcome": "already_paid",
                    "recovery_type": "none",
                    "simulated": False,
                    "notes": (
                        "The Promise-to-Pay amount is already "
                        "marked as paid. No recovery action "
                        "was required."
                    ),
                }
            )

            self._write_promise_to_pay_audit(
                promise,
                result,
            )

            return result

        # -------------------------------------------------
        # Upcoming promise
        # -------------------------------------------------

        if decision.action == PTP_WAIT:
            result.update(
                {
                    "action_taken": "WAIT",
                    "outcome": "waiting",
                    "notes": (
                        "The promised payment date has not "
                        "arrived yet. No reminder was sent."
                    ),
                }
            )

            self._write_promise_to_pay_audit(
                promise,
                result,
            )

            return result

        # -------------------------------------------------
        # Due today
        # -------------------------------------------------

        if decision.action == PTP_PAYMENT_REMINDER:
            result.update(
                {
                    "action_taken": (
                        "PAYMENT_REMINDER_SENT"
                    ),
                    "outcome": "still_outstanding",
                    "notes": (
                        "Payment reminder selected for a "
                        "promise due today. The follow-up "
                        "is simulated and no payment is "
                        "counted as recovered."
                    ),
                }
            )

            self._write_promise_to_pay_audit(
                promise,
                result,
            )

            return result

        # -------------------------------------------------
        # 1-3 days overdue
        # -------------------------------------------------

        if decision.action == PTP_STRONGER_REMINDER:
            result.update(
                {
                    "action_taken": (
                        "STRONGER_PAYMENT_REMINDER_SENT"
                    ),
                    "outcome": "still_outstanding",
                    "notes": (
                        "The promised payment is 1-3 days "
                        "overdue. A stronger follow-up was "
                        "selected. No payment is counted "
                        "as recovered."
                    ),
                }
            )

            self._write_promise_to_pay_audit(
                promise,
                result,
            )

            return result

        # -------------------------------------------------
        # 4-7 days overdue
        # -------------------------------------------------

        if decision.action == PTP_ESCALATE_ACCOUNT:
            result.update(
                {
                    "action_taken": PTP_ESCALATE_ACCOUNT,
                    "outcome": "escalated_account",
                    "notes": (
                        "The promised payment is 4-7 days "
                        "overdue. The case was escalated "
                        "to the account owner for direct "
                        "follow-up."
                    ),
                }
            )

            self._write_promise_to_pay_audit(
                promise,
                result,
            )

            return result

        # -------------------------------------------------
        # More than 7 days overdue
        # -------------------------------------------------

        if decision.action == PTP_ESCALATE_HUMAN:
            result.update(
                {
                    "action_taken": PTP_ESCALATE_HUMAN,
                    "outcome": "escalated",
                    "notes": (
                        "The promised payment is more than "
                        "7 days overdue. Automated follow-up "
                        "stops and human collection review "
                        "is required."
                    ),
                }
            )

            self._write_promise_to_pay_audit(
                promise,
                result,
            )

            return result

        # -------------------------------------------------
        # Safety fallback
        # -------------------------------------------------

        result.update(
            {
                "action_taken": ESCALATE_HUMAN,
                "outcome": "escalated",
                "recovery_type": "none",
                "notes": (
                    "Unknown Promise-to-Pay recovery action. "
                    "Escalated for safety."
                ),
            }
        )

        self._write_promise_to_pay_audit(
            promise,
            result,
        )

        return result

    def process_promise_to_pay_batch(
        self,
        promises: list[PromiseToPay],
    ) -> list[dict]:
        """
        Process a batch of Promise-to-Pay records.
        """

        results = []

        print()
        print("=" * 70)
        print("PROMISE-TO-PAY RECOVERY")
        print("=" * 70)

        print(
            f"Promises to process: {len(promises)}"
        )

        total_at_risk = sum(
            promise.amount
            for promise in promises
            if promise.status.lower() != "paid"
        )

        print(
            f"Promise amount at risk: "
            f"₹{total_at_risk:.2f}"
        )

        print("=" * 70)

        for index, promise in enumerate(
            promises,
            start=1,
        ):
            result = self.process_promise_to_pay(
                promise
            )

            results.append(result)

            print(
                f"[{index}/{len(promises)}] "
                f"{promise.promise_id} | "
                f"{promise.customer_name} | "
                f"₹{promise.amount:.2f}"
            )

            print(
                f"    Promise date: "
                f"{promise.promised_date.strftime('%Y-%m-%d')}"
            )

            print(
                f"    Decision:     "
                f"{result['decision']}"
            )

            print(
                f"    Action:       "
                f"{result['action_taken']}"
            )

            print(
                f"    Outcome:      "
                f"{result['outcome']}"
            )

        print("=" * 70)

        reminders = sum(
            1
            for result in results
            if result["action_taken"]
            == "PAYMENT_REMINDER_SENT"
        )

        stronger_reminders = sum(
            1
            for result in results
            if result["action_taken"]
            == "STRONGER_PAYMENT_REMINDER_SENT"
        )

        account_escalations = sum(
            1
            for result in results
            if result["action_taken"]
            == PTP_ESCALATE_ACCOUNT
        )

        human_escalations = sum(
            1
            for result in results
            if result["action_taken"]
            == PTP_ESCALATE_HUMAN
        )

        still_outstanding = sum(
            result["amount"]
            for result in results
            if result["outcome"]
            == "still_outstanding"
        )

        print(
            f"Payment reminders: {reminders}"
        )

        print(
            f"Stronger reminders: {stronger_reminders}"
        )

        print(
            f"Account escalations: "
            f"{account_escalations}"
        )

        print(
            f"Human escalations: "
            f"{human_escalations}"
        )

        print(
            f"Still outstanding: "
            f"₹{still_outstanding:.2f}"
        )

        print(
            "Confirmed PTP recovered revenue: "
            "₹0.00"
        )

        print("=" * 70)

        return results
    # =====================================================
    # Payment Link Handling
    # =====================================================

    def _handle_new_payment_link(
        self,
        payment: FailedPayment,
        result: dict,
    ) -> dict:
        """
        Execute SEND_NEW_LINK.

        A successful Payment Link creation is NOT recovery.

        Confirmed recovery requires Razorpay to report:

            status == "paid"
            AND
            amount_paid > 0
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
                    "outcome": "awaiting_payment",
                    "recovery_type": "none",
                    "real_api_call": True,
                    "simulated": False,
                    "payment_link": payment_link_url,
                    "payment_link_id": payment_link_id,
                    "settlement_status": (
                        "not_checked"
                    ),
                    "settlement_confirmed": False,
                    "settlement_amount_paid": 0.0,
                    "settlement_payment_id": None,
                    "settlement_api_status_code": None,
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
                    settlement_result=settlement_result,
                )

            else:

                result.update(
                    {
                        "settlement_status": (
                            "missing_payment_link_id"
                        ),
                        "settlement_confirmed": False,
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
            api_result.get("error")
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

    # =====================================================
    # Settlement Status Check
    # =====================================================

    def _check_payment_link_settlement(
        self,
        payment_link_id: str,
    ) -> dict:
        """
        Fetch the current Payment Link status from Razorpay.
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

    # =====================================================
    # Apply Settlement Result
    # =====================================================

    @staticmethod
    def _apply_settlement_result(
        result: dict,
        settlement_result: dict,
    ) -> None:
        """
        Apply normalized Razorpay settlement information.

        Only confirmed paid state becomes real recovery.
        """

        result["settlement_status"] = (
            settlement_result.get("status")
        )

        result["settlement_confirmed"] = (
            settlement_result.get(
                "confirmed",
                False,
            )
        )

        result["settlement_amount"] = (
            settlement_result.get(
                "amount",
                0.0,
            )
        )

        result["settlement_amount_paid"] = (
            settlement_result.get(
                "amount_paid",
                0.0,
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

        if settlement_result.get(
            "confirmed"
        ) is True:

            result["outcome"] = (
                "confirmed_settlement"
            )

            result["recovery_type"] = "real"

            result["notes"] = (
                "Razorpay confirmed that the "
                "Payment Link was paid. "
                "This recovery is counted as "
                "confirmed recovered revenue."
            )

            return

        result["outcome"] = (
            "awaiting_payment"
        )

        result["recovery_type"] = "none"

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

    # =====================================================
    # Re-check Existing Payment Link
    # =====================================================

    def check_existing_payment_link(
        self,
        payment_link_id: str,
    ) -> dict:
        """
        Public helper for checking an existing Payment Link.

        Does NOT create a new Payment Link.
        """

        return (
            self._check_payment_link_settlement(
                payment_link_id
            )
        )

    # =====================================================
    # Base Payment Result
    # =====================================================

    @staticmethod
    def _base_result(
        payment: FailedPayment,
        decision,
    ) -> dict:
        """
        Create the common payment result structure.
        """

        return {
            "timestamp": (
                datetime.now().isoformat(
                    timespec="seconds"
                )
            ),
            "payment_id": payment.payment_id,
            "customer_name": payment.customer_name,
            "email": payment.email,
            "phone": payment.phone,
            "amount": payment.amount,
            "failure_reason": payment.failure_reason,
            "payment_type": payment.payment_type,
            "attempt_count": payment.attempt_count,
            "last_attempt_at": payment.last_attempt_at,
            "decision": decision.action,
            "reason": decision.reason,
            "delay_hours": decision.delay_hours,
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
            "settlement_status": "not_applicable",
            "settlement_confirmed": False,
            "settlement_amount": 0.0,
            "settlement_amount_paid": 0.0,
            "settlement_payment_id": None,
            "settlement_api_status_code": None,
            "settlement_error": None,
            "settlement_api_response": None,
            "notes": None,
        }

    # =====================================================
    # Payment Audit
    # =====================================================

    def _write_audit(
        self,
        payment: FailedPayment,
        result: dict,
    ) -> None:
        """
        Write one payment audit record.
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
            0.0,
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
            api_status_code=result["api_status_code"],
            outcome=result["outcome"],
            notes=combined_notes,
            recovery_type=result["recovery_type"],
            real_api_call=result["real_api_call"],
            simulated=result["simulated"],
            timestamp=result["timestamp"],
            payment_link_id=result.get(
                "payment_link_id"
            ),
            settlement_status=result.get(
                "settlement_status"
            ),
            settlement_confirmed=result.get(
                "settlement_confirmed",
                False,
            ),
            settlement_amount=result.get(
                "settlement_amount",
                0.0,
            ),
            settlement_amount_paid=result.get(
                "settlement_amount_paid",
                0.0,
            ),
            settlement_payment_id=result.get(
                "settlement_payment_id"
            ),
            settlement_api_status_code=result.get(
                "settlement_api_status_code"
            ),
            settlement_error=result.get(
                "settlement_error"
            ),
        )

    # =====================================================
    # Console Output
    # =====================================================

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
                0.0,
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