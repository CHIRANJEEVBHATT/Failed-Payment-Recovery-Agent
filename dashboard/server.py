import json
import sqlite3
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "database" / "audit.db"
DASHBOARD_PATH = Path(__file__).resolve().parent / "index.html"

HOST = "127.0.0.1"
PORT = 5000
API_CAP = 20


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def safe_float(value):
    if value is None:
        return 0.0
    return float(value)


def build_dashboard_data():
    with get_connection() as connection:
        cursor = connection.cursor()

        # =========================================================
        # OVERALL AUDIT METRICS
        # =========================================================

        cursor.execute("""
            SELECT COUNT(*) AS total_records
            FROM audit_logs
        """)
        total_audit_records = cursor.fetchone()["total_records"]

        cursor.execute("""
            SELECT COUNT(*) AS payment_records
            FROM audit_logs
            WHERE record_type = 'payment'
        """)
        payment_records = cursor.fetchone()["payment_records"]

        cursor.execute("""
            SELECT COUNT(*) AS checkout_records
            FROM audit_logs
            WHERE record_type = 'checkout'
        """)
        checkout_records = cursor.fetchone()["checkout_records"]

        cursor.execute("""
            SELECT COUNT(*) AS b2b_records
            FROM audit_logs
            WHERE record_type = 'b2b'
        """)
        b2b_records = cursor.fetchone()["b2b_records"]

        cursor.execute("""
            SELECT COUNT(*) AS ptp_records
            FROM audit_logs
            WHERE record_type = 'promise_to_pay'
        """)
        ptp_records = cursor.fetchone()["ptp_records"]

        # =========================================================
        # PAYMENT METRICS
        # =========================================================

        cursor.execute("""
            SELECT
                COALESCE(SUM(amount), 0) AS amount_at_risk
            FROM audit_logs
            WHERE record_type = 'payment'
        """)
        payment_amount_at_risk = safe_float(
            cursor.fetchone()["amount_at_risk"]
        )

        cursor.execute("""
            SELECT
                COALESCE(SUM(settlement_amount_paid), 0)
                    AS confirmed_recovered,
                COUNT(*) AS confirmed_count
            FROM audit_logs
            WHERE record_type = 'payment'
              AND settlement_confirmed = 1
        """)
        payment_recovery = cursor.fetchone()

        confirmed_payment_revenue = safe_float(
            payment_recovery["confirmed_recovered"]
        )
        confirmed_payment_count = payment_recovery["confirmed_count"]

        # =========================================================
        # PAYMENT API ACTIONS
        # =========================================================

        cursor.execute("""
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(amount), 0) AS amount
            FROM audit_logs
            WHERE record_type = 'payment'
              AND real_api_call = 1
              AND settlement_confirmed = 0
        """)
        triggered = cursor.fetchone()

        recovery_actions_triggered = triggered["count"]
        recovery_actions_amount = safe_float(triggered["amount"])

        cursor.execute("""
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(amount), 0) AS amount
            FROM audit_logs
            WHERE record_type = 'payment'
              AND simulated = 1
        """)
        simulated = cursor.fetchone()

        simulated_count = simulated["count"]
        simulated_amount = safe_float(simulated["amount"])

        # =========================================================
        # API USAGE
        # =========================================================

        cursor.execute("""
            SELECT COUNT(*) AS api_calls
            FROM audit_logs
            WHERE real_api_call = 1
        """)
        real_api_calls = cursor.fetchone()["api_calls"]

        # =========================================================
        # PAYMENT OUTCOMES
        # =========================================================

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'payment'
              AND outcome = 'still_failed'
        """)
        still_failed = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'payment'
              AND outcome = 'escalated'
        """)
        escalated = cursor.fetchone()["count"]

        # =========================================================
        # PAYMENT DECISION BREAKDOWN
        # =========================================================

        cursor.execute("""
            SELECT
                decision,
                COUNT(*) AS count,
                COALESCE(SUM(amount), 0) AS amount
            FROM audit_logs
            WHERE record_type = 'payment'
            GROUP BY decision
            ORDER BY count DESC
        """)

        decisions = [
            {
                "decision": row["decision"],
                "count": row["count"],
                "amount": safe_float(row["amount"]),
            }
            for row in cursor.fetchall()
        ]

        # =========================================================
        # PAYMENT FAILURE REASONS
        # =========================================================

        cursor.execute("""
            SELECT
                failure_reason,
                COUNT(*) AS count,
                COALESCE(SUM(amount), 0) AS amount
            FROM audit_logs
            WHERE record_type = 'payment'
            GROUP BY failure_reason
            ORDER BY count DESC
        """)

        failure_reasons = [
            {
                "reason": row["failure_reason"],
                "count": row["count"],
                "amount": safe_float(row["amount"]),
            }
            for row in cursor.fetchall()
        ]

        # =========================================================
        # CHECKOUT METRICS
        # =========================================================

        cursor.execute("""
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(amount), 0) AS value
            FROM audit_logs
            WHERE record_type = 'checkout'
        """)
        checkout_total = cursor.fetchone()

        checkout_value = safe_float(checkout_total["value"])

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'checkout'
              AND decision = 'NO_ACTION'
        """)
        checkout_completed = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'checkout'
              AND decision = 'SEND_CHECKOUT_REMINDER'
        """)
        checkout_reminders = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'checkout'
              AND decision = 'WAIT'
        """)
        checkout_waiting = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT
                COALESCE(SUM(settlement_amount_paid), 0) AS amount,
                COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'checkout'
              AND settlement_confirmed = 1
        """)
        checkout_recovery = cursor.fetchone()

        checkout_confirmed_revenue = safe_float(
            checkout_recovery["amount"]
        )
        checkout_confirmed_count = checkout_recovery["count"]

        cursor.execute("""
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(amount), 0) AS amount
            FROM audit_logs
            WHERE record_type = 'checkout'
              AND outcome = 'checkout_recovered'
        """)
        checkout_simulated = cursor.fetchone()

        checkout_simulated_count = checkout_simulated["count"]
        checkout_simulated_amount = safe_float(
            checkout_simulated["amount"]
        )

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'checkout'
              AND outcome = 'still_abandoned'
        """)
        checkout_abandoned = cursor.fetchone()["count"]

        # =========================================================
        # B2B METRICS
        # =========================================================

        cursor.execute("""
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(amount), 0) AS amount
            FROM audit_logs
            WHERE record_type = 'b2b'
        """)
        b2b_total = cursor.fetchone()

        b2b_value = safe_float(b2b_total["amount"])

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'b2b'
              AND decision = 'SEND_REMINDER'
        """)
        b2b_reminders = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'b2b'
              AND decision = 'SEND_STRONGER_REMINDER'
        """)
        b2b_stronger_reminders = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'b2b'
              AND decision = 'ESCALATE_ACCOUNT'
        """)
        b2b_account_escalations = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'b2b'
              AND decision = 'ESCALATE_HUMAN'
        """)
        b2b_human_escalations = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT
                COALESCE(SUM(amount), 0) AS amount
            FROM audit_logs
            WHERE record_type = 'b2b'
              AND outcome = 'still_outstanding'
        """)
        b2b_outstanding = safe_float(
            cursor.fetchone()["amount"]
        )

        cursor.execute("""
            SELECT
                COALESCE(SUM(settlement_amount_paid), 0) AS amount
            FROM audit_logs
            WHERE record_type = 'b2b'
              AND settlement_confirmed = 1
        """)
        b2b_confirmed_revenue = safe_float(
            cursor.fetchone()["amount"]
        )

        # =========================================================
        # PROMISE-TO-PAY METRICS
        # =========================================================

        cursor.execute("""
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(amount), 0) AS amount
            FROM audit_logs
            WHERE record_type = 'promise_to_pay'
        """)
        ptp_total = cursor.fetchone()

        ptp_value = safe_float(ptp_total["amount"])

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'promise_to_pay'
              AND decision = 'SEND_PAYMENT_REMINDER'
        """)
        ptp_payment_reminders = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'promise_to_pay'
              AND decision = 'SEND_STRONGER_REMINDER'
        """)
        ptp_stronger_reminders = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'promise_to_pay'
              AND decision = 'ESCALATE_ACCOUNT'
        """)
        ptp_account_escalations = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'promise_to_pay'
              AND decision = 'ESCALATE_HUMAN'
        """)
        ptp_human_escalations = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'promise_to_pay'
              AND decision = 'WAIT'
        """)
        ptp_waiting = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM audit_logs
            WHERE record_type = 'promise_to_pay'
              AND outcome = 'already_paid'
        """)
        ptp_already_paid = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT
                COALESCE(SUM(amount), 0) AS amount
            FROM audit_logs
            WHERE record_type = 'promise_to_pay'
              AND outcome = 'still_outstanding'
        """)
        ptp_outstanding = safe_float(
            cursor.fetchone()["amount"]
        )

        cursor.execute("""
            SELECT
                COALESCE(SUM(settlement_amount_paid), 0) AS amount
            FROM audit_logs
            WHERE record_type = 'promise_to_pay'
              AND settlement_confirmed = 1
        """)
        ptp_confirmed_revenue = safe_float(
            cursor.fetchone()["amount"]
        )

        # =========================================================
        # SAFETY EXCEPTIONS
        # =========================================================

        cursor.execute("""
            SELECT
                timestamp,
                payment_id,
                customer_name,
                amount,
                failure_reason,
                decision,
                decision_reason,
                action_taken,
                outcome,
                notes
            FROM audit_logs
            WHERE record_type = 'payment'
              AND decision IN (
                  'ESCALATE_HUMAN',
                  'DO_NOT_RETRY'
              )
            ORDER BY id DESC
        """)

        exceptions = [
            dict(row)
            for row in cursor.fetchall()
        ]

        # =========================================================
        # RECENT AUDIT TRAIL
        # =========================================================

        cursor.execute("""
            SELECT
                id,
                timestamp,
                record_type,
                payment_id,
                checkout_id,
                invoice_id,
                promise_id,
                customer_id,
                customer_name,
                company_name,
                amount,
                currency,
                failure_reason,
                decision,
                decision_reason,
                action_taken,
                outcome,
                recovery_type,
                real_api_call,
                simulated,
                settlement_confirmed,
                settlement_amount_paid,
                notes
            FROM audit_logs
            ORDER BY id DESC
            LIMIT 150
        """)

        audit_records = [
            dict(row)
            for row in cursor.fetchall()
        ]

        # =========================================================
        # COMBINED METRICS
        # =========================================================

        combined_amount_at_risk = (
            payment_amount_at_risk
            + checkout_value
            + b2b_value
            + ptp_value
        )

        combined_confirmed_revenue = (
            confirmed_payment_revenue
            + checkout_confirmed_revenue
            + b2b_confirmed_revenue
            + ptp_confirmed_revenue
        )

        payment_recovery_rate = (
            confirmed_payment_revenue
            / payment_amount_at_risk
            * 100
            if payment_amount_at_risk > 0
            else 0.0
        )

        combined_recovery_rate = (
            combined_confirmed_revenue
            / combined_amount_at_risk
            * 100
            if combined_amount_at_risk > 0
            else 0.0
        )

        return {
            "summary": {
                "total_amount_at_risk": combined_amount_at_risk,
                "payment_amount_at_risk": payment_amount_at_risk,
                "checkout_value_observed": checkout_value,
                "b2b_value_at_risk": b2b_value,
                "ptp_value_at_risk": ptp_value,

                "confirmed_recovered": combined_confirmed_revenue,
                "confirmed_payment_revenue": confirmed_payment_revenue,
                "confirmed_checkout_revenue": checkout_confirmed_revenue,
                "confirmed_b2b_revenue": b2b_confirmed_revenue,
                "confirmed_ptp_revenue": ptp_confirmed_revenue,

                "payment_recovery_rate": payment_recovery_rate,
                "combined_recovery_rate": combined_recovery_rate,

                "confirmed_payment_count": confirmed_payment_count,
                "confirmed_checkout_count": checkout_confirmed_count,

                "recovery_actions_triggered": (
                    recovery_actions_triggered
                ),
                "recovery_actions_amount": (
                    recovery_actions_amount
                ),

                "simulated_count": simulated_count,
                "simulated_amount": simulated_amount,

                "real_api_calls": real_api_calls,
                "api_cap": API_CAP,

                "payment_records": payment_records,
                "checkout_records": checkout_records,
                "b2b_records": b2b_records,
                "ptp_records": ptp_records,
                "total_audit_records": total_audit_records,

                "still_failed": still_failed,
                "escalated": escalated,
            },

            "checkout": {
                "sessions": checkout_records,
                "value_observed": checkout_value,
                "completed": checkout_completed,
                "reminders": checkout_reminders,
                "waiting": checkout_waiting,
                "returned": checkout_simulated_count,
                "simulated_recovery_amount": checkout_simulated_amount,
                "still_abandoned": checkout_abandoned,
                "confirmed_revenue": checkout_confirmed_revenue,
            },

            "b2b": {
                "invoices": b2b_records,
                "value_at_risk": b2b_value,
                "reminders": b2b_reminders,
                "stronger_reminders": b2b_stronger_reminders,
                "account_escalations": b2b_account_escalations,
                "human_escalations": b2b_human_escalations,
                "still_outstanding": b2b_outstanding,
                "confirmed_revenue": b2b_confirmed_revenue,
            },

            "promise_to_pay": {
                "records": ptp_records,
                "value_at_risk": ptp_value,
                "payment_reminders": ptp_payment_reminders,
                "stronger_reminders": ptp_stronger_reminders,
                "account_escalations": ptp_account_escalations,
                "human_escalations": ptp_human_escalations,
                "waiting": ptp_waiting,
                "already_paid": ptp_already_paid,
                "still_outstanding": ptp_outstanding,
                "confirmed_revenue": ptp_confirmed_revenue,
            },

            "decisions": decisions,
            "failure_reasons": failure_reasons,
            "exceptions": exceptions,
            "audit_records": audit_records,
        }


class DashboardHandler(BaseHTTPRequestHandler):

    def send_json(self, data, status=200):
        payload = json.dumps(
            data,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(payload)),
        )
        self.send_header(
            "Cache-Control",
            "no-store",
        )
        self.end_headers()

        self.wfile.write(payload)

    def send_html(self, content, status=200):
        payload = content.encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(payload)),
        )
        self.end_headers()

        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/":
            try:
                html = DASHBOARD_PATH.read_text(
                    encoding="utf-8"
                )
                self.send_html(html)
            except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                # Browser/client closed the connection while the HTML was being sent.
                # Do not attempt to write another response to the closed socket.
                pass
            except Exception as exc:
                print(f"Dashboard HTML error: {exc}")
                try:
                    self.send_json(
                        {"error": str(exc)},
                        status=500,
                    )
                except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                    pass
            return

        if parsed.path == "/api/dashboard":
            try:
                data = build_dashboard_data()
                self.send_json(data)
            except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                # Browser/client closed the API connection during the response.
                pass
            except Exception as exc:
                print(f"Dashboard API error: {exc}")
                try:
                    self.send_json(
                        {"error": str(exc)},
                        status=500,
                    )
                except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                    pass
            return

        try:
            self.send_json(
                {"error": "Not found"},
                status=404,
            )
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):
        return


def main():
    if not DATABASE_PATH.exists():
        print(
            f"Audit database not found: {DATABASE_PATH}"
        )
        print(
            "Run 'python run.py' first."
        )
        return

    server = HTTPServer(
        (HOST, PORT),
        DashboardHandler,
    )

    print("=" * 70)
    print("FAILED PAYMENT RECOVERY DASHBOARD")
    print("=" * 70)
    print(
        f"Dashboard: http://{HOST}:{PORT}"
    )
    print(
        f"Database:  {DATABASE_PATH}"
    )
    print()
    print("Press Ctrl+C to stop.")
    print("=" * 70)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()