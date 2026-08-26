from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


# ---------------------------------------------------------
# Paths
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATABASE_PATH = (
    PROJECT_ROOT
    / "database"
    / "audit.db"
)

DASHBOARD_FILE = (
    PROJECT_ROOT
    / "dashboard"
    / "index.html"
)


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

HOST = "127.0.0.1"
PORT = 5000

MAX_REAL_API_CALLS = 20


# ---------------------------------------------------------
# Database helpers
# ---------------------------------------------------------

def get_connection():
    """
    Open the existing SQLite audit database.

    The dashboard does not create a second database.
    It reads the same database used by the recovery agent.
    """

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Audit database not found: {DATABASE_PATH}"
        )

    connection = sqlite3.connect(
        DATABASE_PATH
    )

    connection.row_factory = sqlite3.Row

    return connection


def get_table_columns(connection):
    """
    Return all columns currently available
    in the audit_logs table.

    This keeps the dashboard compatible with
    the existing audit database schema.
    """

    rows = connection.execute(
        "PRAGMA table_info(audit_logs)"
    ).fetchall()

    return {
        row["name"]
        for row in rows
    }


# ---------------------------------------------------------
# Safe value helpers
# ---------------------------------------------------------

def safe_float(value):
    try:
        return float(value or 0)
    except (
        TypeError,
        ValueError
    ):
        return 0.0


def is_real_recovery(row):
    """
    Determine whether an audit record represents
    a genuine successful Razorpay API recovery.

    We deliberately require BOTH:

    1. recovered outcome
    2. real API recovery marker

    This prevents simulated recoveries from being
    counted as real revenue recovery.
    """

    outcome = str(
        row["outcome"] or ""
    ).lower()

    recovery_type = str(
        row["recovery_type"] or ""
    ).lower()

    return (
        outcome == "recovered"
        and recovery_type == "real_api"
    )


def is_simulated_recovery(row):
    """
    Identify simulated recoveries.

    These are reported separately and are never
    blended into real recovery metrics.
    """

    outcome = str(
        row["outcome"] or ""
    ).lower()

    recovery_type = str(
        row["recovery_type"] or ""
    ).lower()

    return (
        outcome == "recovered"
        and recovery_type == "simulated"
    )


# ---------------------------------------------------------
# Dashboard statistics
# ---------------------------------------------------------

def build_dashboard_data():
    """
    Read the current SQLite audit batch and produce
    the JSON structure consumed by index.html.
    """

    connection = get_connection()

    try:

        columns = get_table_columns(
            connection
        )

        required_columns = {
            "payment_id",
            "failure_reason",
            "amount",
            "outcome",
        }

        missing = (
            required_columns
            - columns
        )

        if missing:
            raise RuntimeError(
                "audit_logs is missing columns: "
                + ", ".join(
                    sorted(missing)
                )
            )

        rows = connection.execute(
            """
            SELECT *
            FROM audit_logs
            ORDER BY timestamp ASC
            """
        ).fetchall()

    finally:

        connection.close()


    total_payments = len(rows)


    # -----------------------------------------------------
    # Amount at risk
    # -----------------------------------------------------

    total_amount_at_risk = sum(
        safe_float(
            row["amount"]
        )
        for row in rows
    )


    # -----------------------------------------------------
    # Recovery metrics
    # -----------------------------------------------------

    real_recovered_amount = 0.0

    simulated_recovered_amount = 0.0

    real_api_calls = 0

    still_failed_amount = 0.0

    escalated_count = 0


    for row in rows:

        amount = safe_float(
            row["amount"]
        )

        if is_real_recovery(row):

            real_recovered_amount += amount

        elif is_simulated_recovery(row):

            simulated_recovered_amount += amount


        outcome = str(
            row["outcome"] or ""
        ).lower()


        if outcome == "escalated":

            escalated_count += 1


        if outcome == "still_failed":

            still_failed_amount += amount


        if (
            "api_status_code" in columns
            and row["api_status_code"] is not None
        ):

            try:

                status_code = int(
                    row["api_status_code"]
                )

                if status_code == 200:

                    real_api_calls += 1

            except (
                TypeError,
                ValueError
            ):

                pass


    # -----------------------------------------------------
    # Percentages
    # -----------------------------------------------------

    if total_amount_at_risk > 0:

        real_recovery_percentage = (
            real_recovered_amount
            / total_amount_at_risk
        ) * 100

        combined_recovery_percentage = (
            (
                real_recovered_amount
                + simulated_recovered_amount
            )
            / total_amount_at_risk
        ) * 100

    else:

        real_recovery_percentage = 0.0

        combined_recovery_percentage = 0.0


    # -----------------------------------------------------
    # Failure reason breakdown
    # -----------------------------------------------------

    breakdown = defaultdict(
        lambda: {
            "count": 0,
            "recovered_amount": 0.0,
        }
    )


    for row in rows:

        reason = str(
            row["failure_reason"]
        )

        breakdown[reason][
            "count"
        ] += 1


        if is_real_recovery(row):

            breakdown[reason][
                "recovered_amount"
            ] += safe_float(
                row["amount"]
            )


    failure_breakdown = []


    for reason, values in sorted(
        breakdown.items()
    ):

        failure_breakdown.append(
            {
                "failure_reason": reason,
                "count": values["count"],
                "recovered_amount": round(
                    values["recovered_amount"],
                    2
                ),
            }
        )


    # -----------------------------------------------------
    # Honest exceptions
    # -----------------------------------------------------

    exceptions = []


    for row in rows:

        outcome = str(
            row["outcome"] or ""
        ).lower()


        if outcome not in {
            "escalated",
            "still_failed",
        }:

            continue


        decision = ""

        if "decision" in columns:

            decision = str(
                row["decision"] or ""
            )


        reason = str(
            row["failure_reason"]
        )


        if decision:

            exception_reason = (
                f"{reason} — "
                f"{decision}"
            )

        else:

            exception_reason = reason


        exceptions.append(
            {
                "payment_id": str(
                    row["payment_id"]
                ),
                "reason": exception_reason,
            }
        )


    # -----------------------------------------------------
    # Final dashboard payload
    # -----------------------------------------------------

    return {
        "total_amount_at_risk": round(
            total_amount_at_risk,
            2
        ),

        "real_recovered_amount": round(
            real_recovered_amount,
            2
        ),

        "simulated_recovered_amount": round(
            simulated_recovered_amount,
            2
        ),

        "real_recovery_percentage": round(
            real_recovery_percentage,
            2
        ),

        "combined_recovery_percentage": round(
            combined_recovery_percentage,
            2
        ),

        "total_payments": total_payments,

        "real_api_calls": real_api_calls,

        "max_real_api_calls":
            MAX_REAL_API_CALLS,

        "still_failed_amount": round(
            still_failed_amount,
            2
        ),

        "escalated_count": escalated_count,

        "audit_records": total_payments,

        "failure_breakdown":
            failure_breakdown,

        "exceptions":
            exceptions,

    }


# ---------------------------------------------------------
# HTTP server
# ---------------------------------------------------------

class DashboardHandler(
    BaseHTTPRequestHandler
):

    def send_json(
        self,
        data,
        status=200
    ):

        body = json.dumps(
            data,
            indent=2
        ).encode(
            "utf-8"
        )

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            "application/json"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.end_headers()

        self.wfile.write(
            body
        )


    def do_GET(self):

        parsed_url = urlparse(
            self.path
        )

        path = parsed_url.path


        # ---------------------------------------------
        # Dashboard API
        # ---------------------------------------------

        if path == "/api/dashboard":

            try:

                data = build_dashboard_data()

                self.send_json(
                    data
                )

            except Exception as error:

                self.send_json(
                    {
                        "error": str(
                            error
                        )
                    },
                    status=500
                )

            return


        # ---------------------------------------------
        # Dashboard HTML
        # ---------------------------------------------

        if path in {
            "/",
            "/index.html",
        }:

            try:

                html = DASHBOARD_FILE.read_bytes()

            except FileNotFoundError:

                self.send_json(
                    {
                        "error":
                            "dashboard/index.html "
                            "not found"
                    },
                    status=404
                )

                return


            self.send_response(
                200
            )

            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8"
            )

            self.send_header(
                "Content-Length",
                str(len(html))
            )

            self.end_headers()

            self.wfile.write(
                html
            )

            return


        # ---------------------------------------------
        # Not found
        # ---------------------------------------------

        self.send_json(
            {
                "error": "Not found"
            },
            status=404
        )


    def log_message(
        self,
        format,
        *args
    ):

        print(
            "[Dashboard]",
            format % args
        )


# ---------------------------------------------------------
# Start server
# ---------------------------------------------------------

def main():

    print("=" * 60)

    print(
        "FAILED PAYMENT RECOVERY DASHBOARD"
    )

    print("=" * 60)

    print(
        f"Database: {DATABASE_PATH}"
    )

    print(
        f"Dashboard: {DASHBOARD_FILE}"
    )

    print(
        f"URL: http://{HOST}:{PORT}"
    )

    print()

    print(
        "Press CTRL+C to stop the server."
    )

    print("=" * 60)


    server = ThreadingHTTPServer(
        (
            HOST,
            PORT
        ),
        DashboardHandler
    )


    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print(
            "\nDashboard server stopped."
        )

    finally:

        server.server_close()


if __name__ == "__main__":

    main()