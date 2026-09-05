import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.config import DATABASE_DIR


class AuditLogger:
    """
    SQLite-based audit logger.

    Supports:
        - Failed payment recovery records
        - Checkout drop-off recovery records
        - B2B receivable recovery records
        - Promise-to-Pay recovery records

    The audit trail records:
        decision
        action
        outcome
        recovery classification
        API activity
        settlement information
        B2B collection information
        Promise-to-Pay information
    """

    def __init__(
        self,
        database_path: Optional[str] = None,
    ):
        if database_path is None:
            self.database_path = (
                Path(DATABASE_DIR)
                / "audit.db"
            )
        else:
            self.database_path = Path(
                database_path
            )

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize_database()

    # =====================================================
    # Database Connection
    # =====================================================

    def _connect(self):
        return sqlite3.connect(
            str(self.database_path)
        )

    # =====================================================
    # Initialize Database
    # =====================================================

    def _initialize_database(self) -> None:
        """
        Create the audit table if it does not exist.

        Also migrates older database versions by adding
        newly introduced columns.
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    timestamp TEXT NOT NULL,

                    record_type TEXT DEFAULT 'payment',

                    checkout_id TEXT,
                    customer_id TEXT,
                    currency TEXT,
                    started_at TEXT,

                    payment_id TEXT,
                    customer_name TEXT,
                    email TEXT,
                    amount REAL,

                    failure_reason TEXT,
                    payment_type TEXT,
                    attempt_count INTEGER,

                    decision TEXT,
                    decision_reason TEXT,

                    action_taken TEXT,

                    api_request TEXT,
                    api_response TEXT,
                    api_status_code INTEGER,

                    outcome TEXT,

                    recovery_type TEXT,

                    real_api_call INTEGER DEFAULT 0,
                    simulated INTEGER DEFAULT 0,

                    notes TEXT,

                    payment_link_id TEXT,
                    settlement_status TEXT,
                    settlement_confirmed INTEGER DEFAULT 0,
                    settlement_amount REAL DEFAULT 0,
                    settlement_amount_paid REAL DEFAULT 0,
                    settlement_payment_id TEXT,
                    settlement_api_status_code INTEGER,
                    settlement_error TEXT,
                    settlement_checked_at TEXT,

                    invoice_id TEXT,
                    company_name TEXT,
                    due_date TEXT,
                    days_overdue INTEGER,
                    payment_status TEXT,
                    previous_reminders INTEGER DEFAULT 0,
                    promised_payment_date TEXT,
                    paid_at TEXT,

                    promise_id TEXT,
                    promise_status TEXT,
                    previous_missed_promises INTEGER DEFAULT 0,
                    contact_channel TEXT
                )
                """
            )

            connection.commit()

            self._migrate_schema(
                connection
            )

    # =====================================================
    # Schema Migration
    # =====================================================

    def _migrate_schema(
        self,
        connection,
    ) -> None:
        """
        Add missing columns to older audit databases.
        """

        cursor = connection.cursor()

        cursor.execute(
            """
            PRAGMA table_info(audit_logs)
            """
        )

        existing_columns = {
            row[1]
            for row in cursor.fetchall()
        }

        required_columns = {
            "timestamp": "TEXT",
            "record_type": "TEXT DEFAULT 'payment'",

            "checkout_id": "TEXT",
            "customer_id": "TEXT",
            "currency": "TEXT",
            "started_at": "TEXT",

            "payment_id": "TEXT",
            "customer_name": "TEXT",
            "email": "TEXT",
            "amount": "REAL",

            "failure_reason": "TEXT",
            "payment_type": "TEXT",
            "attempt_count": "INTEGER",

            "decision": "TEXT",
            "decision_reason": "TEXT",
            "action_taken": "TEXT",

            "api_request": "TEXT",
            "api_response": "TEXT",
            "api_status_code": "INTEGER",

            "outcome": "TEXT",
            "recovery_type": "TEXT",

            "real_api_call": (
                "INTEGER DEFAULT 0"
            ),
            "simulated": (
                "INTEGER DEFAULT 0"
            ),

            "notes": "TEXT",

            "payment_link_id": "TEXT",
            "settlement_status": "TEXT",
            "settlement_confirmed": (
                "INTEGER DEFAULT 0"
            ),
            "settlement_amount": (
                "REAL DEFAULT 0"
            ),
            "settlement_amount_paid": (
                "REAL DEFAULT 0"
            ),
            "settlement_payment_id": "TEXT",
            "settlement_api_status_code": (
                "INTEGER"
            ),
            "settlement_error": "TEXT",
            "settlement_checked_at": "TEXT",

            # -------------------------------------------------
            # B2B fields
            # -------------------------------------------------

            "invoice_id": "TEXT",
            "company_name": "TEXT",
            "due_date": "TEXT",
            "days_overdue": "INTEGER",
            "payment_status": "TEXT",
            "previous_reminders": (
                "INTEGER DEFAULT 0"
            ),
            "promised_payment_date": "TEXT",
            "paid_at": "TEXT",

            # -------------------------------------------------
            # Promise-to-Pay fields
            # -------------------------------------------------

            "promise_id": "TEXT",
            "promise_status": "TEXT",
            "previous_missed_promises": (
                "INTEGER DEFAULT 0"
            ),
            "contact_channel": "TEXT",
        }

        for (
            column_name,
            column_type,
        ) in required_columns.items():

            if column_name in existing_columns:
                continue

            cursor.execute(
                f"""
                ALTER TABLE audit_logs
                ADD COLUMN {column_name}
                {column_type}
                """
            )

        connection.commit()

    # =====================================================
    # Clear Current Audit Records
    # =====================================================

    def clear_logs(self) -> None:
        """
        Clear previous development/run records.

        The table structure itself is preserved.
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                DELETE FROM audit_logs
                """
            )

            connection.commit()

    # =====================================================
    # Serialize Values
    # =====================================================

    @staticmethod
    def _serialize(
        value: Any,
    ) -> Optional[str]:
        """
        Convert Python values into SQLite-compatible values.
        """

        if value is None:
            return None

        if isinstance(
            value,
            (dict, list, tuple),
        ):
            return json.dumps(
                value,
                ensure_ascii=False,
                default=str,
            )

        if isinstance(
            value,
            bool,
        ):
            return (
                "true"
                if value
                else "false"
            )

        if isinstance(
            value,
            (str, int, float),
        ):
            return value

        return str(value)

    # =====================================================
    # Boolean Conversion
    # =====================================================

    @staticmethod
    def _bool_to_int(
        value: Any,
    ) -> int:
        return 1 if bool(value) else 0

    # =====================================================
    # Store Audit Record
    # =====================================================

    def log(
        self,
        payment_id: Optional[str],
        customer_name: Optional[str],
        email: Optional[str],
        amount: float,
        failure_reason: Optional[str],
        payment_type: str,
        attempt_count: int,
        decision: str,
        decision_reason: str,
        action_taken: str,
        api_request: Any = None,
        api_response: Any = None,
        outcome: str = "",
        notes: Optional[str] = None,
        recovery_type: str = "none",
        real_api_call: bool = False,
        simulated: bool = False,
        api_status_code: Optional[int] = None,
        timestamp: Optional[str] = None,

        # -------------------------------------------------
        # Checkout fields
        # -------------------------------------------------

        record_type: str = "payment",
        checkout_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        currency: Optional[str] = None,
        started_at: Optional[str] = None,

        # -------------------------------------------------
        # Settlement fields
        # -------------------------------------------------

        payment_link_id: Optional[str] = None,
        settlement_status: Optional[str] = None,
        settlement_confirmed: bool = False,
        settlement_amount: float = 0.0,
        settlement_amount_paid: float = 0.0,
        settlement_payment_id: Optional[str] = None,
        settlement_api_status_code: Optional[int] = None,
        settlement_error: Optional[str] = None,
        settlement_checked_at: Optional[str] = None,

        # -------------------------------------------------
        # B2B fields
        # -------------------------------------------------

        invoice_id: Optional[str] = None,
        company_name: Optional[str] = None,
        due_date: Optional[str] = None,
        days_overdue: Optional[int] = None,
        payment_status: Optional[str] = None,
        previous_reminders: int = 0,
        promised_payment_date: Optional[str] = None,
        paid_at: Optional[str] = None,

        # -------------------------------------------------
        # Promise-to-Pay fields
        # -------------------------------------------------

        promise_id: Optional[str] = None,
        promise_status: Optional[str] = None,
        previous_missed_promises: int = 0,
        contact_channel: Optional[str] = None,
    ) -> None:
        """
        Store one complete audit record.
        """

        if timestamp is None:
            timestamp = (
                datetime.now().isoformat(
                    timespec="seconds"
                )
            )

        if (
            settlement_status is not None
            and settlement_checked_at is None
        ):
            settlement_checked_at = timestamp

        serialized_request = (
            self._serialize(
                api_request
            )
        )

        serialized_response = (
            self._serialize(
                api_response
            )
        )

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                INSERT INTO audit_logs (

                    timestamp,

                    record_type,
                    checkout_id,
                    customer_id,
                    currency,
                    started_at,

                    payment_id,
                    customer_name,
                    email,
                    amount,

                    failure_reason,
                    payment_type,
                    attempt_count,

                    decision,
                    decision_reason,

                    action_taken,

                    api_request,
                    api_response,
                    api_status_code,

                    outcome,

                    recovery_type,

                    real_api_call,
                    simulated,

                    notes,

                    payment_link_id,
                    settlement_status,
                    settlement_confirmed,
                    settlement_amount,
                    settlement_amount_paid,
                    settlement_payment_id,
                    settlement_api_status_code,
                    settlement_error,
                    settlement_checked_at,

                    invoice_id,
                    company_name,
                    due_date,
                    days_overdue,
                    payment_status,
                    previous_reminders,
                    promised_payment_date,
                    paid_at,

                    promise_id,
                    promise_status,
                    previous_missed_promises,
                    contact_channel
                )

                VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?,
                    ?, ?, ?,
                    ?,
                    ?,
                    ?, ?,
                    ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
                """,
                (
                    timestamp,

                    record_type,
                    checkout_id,
                    customer_id,
                    currency,
                    started_at,

                    payment_id,
                    customer_name,
                    email,
                    amount,

                    failure_reason,
                    payment_type,
                    attempt_count,

                    decision,
                    decision_reason,

                    action_taken,

                    serialized_request,
                    serialized_response,
                    api_status_code,

                    outcome,

                    recovery_type,

                    self._bool_to_int(
                        real_api_call
                    ),
                    self._bool_to_int(
                        simulated
                    ),

                    notes,

                    payment_link_id,
                    settlement_status,
                    self._bool_to_int(
                        settlement_confirmed
                    ),
                    settlement_amount,
                    settlement_amount_paid,
                    settlement_payment_id,
                    settlement_api_status_code,
                    settlement_error,
                    settlement_checked_at,

                    invoice_id,
                    company_name,
                    due_date,
                    days_overdue,
                    payment_status,
                    previous_reminders,
                    promised_payment_date,
                    paid_at,

                    promise_id,
                    promise_status,
                    previous_missed_promises,
                    contact_channel,
                ),
            )

            connection.commit()

    # =====================================================
    # Convert Row To Dictionary
    # =====================================================

    @staticmethod
    def _row_to_dict(
        cursor,
        row,
    ) -> dict:
        columns = [
            description[0]
            for description in cursor.description
        ]

        return dict(
            zip(
                columns,
                row,
            )
        )

    # =====================================================
    # Get All Logs
    # =====================================================

    def get_all_logs(self) -> list[dict]:
        """
        Return every audit record.
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT *
                FROM audit_logs
                ORDER BY id ASC
                """
            )

            rows = cursor.fetchall()

            return [
                self._row_to_dict(
                    cursor,
                    row,
                )
                for row in rows
            ]

    # =====================================================
    # Payment Logs
    # =====================================================

    def get_logs_for_payment_ids(
        self,
        payment_ids: list[str],
    ) -> list[dict]:
        """
        Return audit records for supplied payment IDs.
        """

        if not payment_ids:
            return []

        placeholders = ",".join(
            "?"
            for _ in payment_ids
        )

        query = f"""
            SELECT *
            FROM audit_logs
            WHERE payment_id IN (
                {placeholders}
            )
            ORDER BY id ASC
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                query,
                payment_ids,
            )

            rows = cursor.fetchall()

            return [
                self._row_to_dict(
                    cursor,
                    row,
                )
                for row in rows
            ]

    # =====================================================
    # B2B Logs
    # =====================================================

    def get_b2b_logs(self) -> list[dict]:
        """
        Return all B2B receivable audit records.
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT *
                FROM audit_logs
                WHERE record_type = 'b2b'
                ORDER BY id ASC
                """
            )

            rows = cursor.fetchall()

            return [
                self._row_to_dict(
                    cursor,
                    row,
                )
                for row in rows
            ]

    # =====================================================
    # B2B Outstanding Amount
    # =====================================================

    def get_b2b_outstanding_amount(
        self,
    ) -> float:
        """
        Return total B2B amount currently marked as
        still outstanding in the current audit batch.
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT
                    COALESCE(
                        SUM(amount),
                        0
                    )
                FROM audit_logs
                WHERE record_type = 'b2b'
                AND outcome = 'still_outstanding'
                """
            )

            result = cursor.fetchone()

            return float(
                result[0]
            )

    # =====================================================
    # Promise-to-Pay Logs
    # =====================================================

    def get_promise_to_pay_logs(
        self,
    ) -> list[dict]:
        """
        Return all Promise-to-Pay audit records.
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT *
                FROM audit_logs
                WHERE record_type = 'promise_to_pay'
                ORDER BY id ASC
                """
            )

            rows = cursor.fetchall()

            return [
                self._row_to_dict(
                    cursor,
                    row,
                )
                for row in rows
            ]

    # =====================================================
    # Promise-to-Pay Outstanding Amount
    # =====================================================

    def get_promise_to_pay_outstanding_amount(
        self,
    ) -> float:
        """
        Return total Promise-to-Pay amount currently
        recorded as still outstanding.
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT
                    COALESCE(
                        SUM(amount),
                        0
                    )
                FROM audit_logs
                WHERE record_type = 'promise_to_pay'
                AND outcome = 'still_outstanding'
                """
            )

            result = cursor.fetchone()

            return float(
                result[0]
            )

    # =====================================================
    # Confirmed Settlements
    # =====================================================

    def get_confirmed_settlements(
        self,
    ) -> list[dict]:
        """
        Return audit records where Razorpay confirmed
        an actual payment.
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT *
                FROM audit_logs
                WHERE settlement_confirmed = 1
                ORDER BY id ASC
                """
            )

            rows = cursor.fetchall()

            return [
                self._row_to_dict(
                    cursor,
                    row,
                )
                for row in rows
            ]

    # =====================================================
    # Confirmed Recovered Amount
    # =====================================================

    def get_confirmed_recovered_amount(
        self,
    ) -> float:
        """
        Return total amount actually paid through
        confirmed Payment Link settlements.
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT
                    COALESCE(
                        SUM(
                            settlement_amount_paid
                        ),
                        0
                    )
                FROM audit_logs
                WHERE settlement_confirmed = 1
                """
            )

            result = cursor.fetchone()

            return float(
                result[0]
            )

    # =====================================================
    # Count Logs
    # =====================================================

    def count_logs(self) -> int:
        """
        Return total audit records.
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM audit_logs
                """
            )

            result = cursor.fetchone()

            return int(
                result[0]
            )


if __name__ == "__main__":

    logger = AuditLogger()

    print("=" * 60)
    print("AUDIT LOGGER TEST")
    print("=" * 60)

    print(
        "Database:",
        logger.database_path,
    )

    print(
        "Audit records:",
        logger.count_logs(),
    )

    print(
        "B2B audit records:",
        len(
            logger.get_b2b_logs()
        ),
    )

    print(
        "B2B outstanding amount:",
        f"₹{logger.get_b2b_outstanding_amount():.2f}",
    )

    print(
        "Promise-to-Pay audit records:",
        len(
            logger.get_promise_to_pay_logs()
        ),
    )

    print(
        "Promise-to-Pay outstanding amount:",
        f"₹{logger.get_promise_to_pay_outstanding_amount():.2f}",
    )

    print(
        "Confirmed settlements:",
        len(
            logger.get_confirmed_settlements()
        ),
    )

    print(
        "Confirmed recovered amount:",
        f"₹{logger.get_confirmed_recovered_amount():.2f}",
    )

    print("=" * 60)