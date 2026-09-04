import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.config import DATABASE_DIR


class AuditLogger:
    """
    SQLite-based audit logger.

    The audit database stores the decisions, actions,
    outcomes, and confirmed settlement information for
    the current processing batch.

    Supports both:
    - Failed payment recovery records
    - Checkout drop-off recovery records

    Complex Python objects such as dictionaries and lists
    are converted to JSON strings before being stored.
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

    # -----------------------------------------------------
    # Database connection
    # -----------------------------------------------------

    def _connect(self):
        return sqlite3.connect(
            str(self.database_path)
        )

    # -----------------------------------------------------
    # Initialize database
    # -----------------------------------------------------

    def _initialize_database(self) -> None:
        """
        Create the audit table if it does not exist.

        Also migrate older database versions by adding any
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
                    settlement_checked_at TEXT
                )
                """
            )

            connection.commit()

            self._migrate_schema(
                connection
            )

    # -----------------------------------------------------
    # Schema migration
    # -----------------------------------------------------

    def _migrate_schema(
        self,
        connection,
    ) -> None:
        """
        Add missing columns to an older audit database.

        This allows an existing audit.db to continue being
        used after the project schema is upgraded.
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

            "real_api_call": "INTEGER DEFAULT 0",
            "simulated": "INTEGER DEFAULT 0",

            "notes": "TEXT",

            # -------------------------------------------------
            # Confirmed settlement fields
            # -------------------------------------------------

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

    # -----------------------------------------------------
    # Clear current audit records
    # -----------------------------------------------------

    def clear_logs(self) -> None:
        """
        Clear previous development/run records.

        The project processes one synthetic batch at a time.
        Starting a new batch with a clean audit table prevents
        previous executions from contaminating the current
        batch's metrics and audit verification.

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

    # -----------------------------------------------------
    # Serialize values
    # -----------------------------------------------------

    @staticmethod
    def _serialize(
        value: Any,
    ) -> Optional[str]:
        """
        Convert Python values into SQLite-compatible values.

        Dictionaries, lists, and tuples are stored as JSON.
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

    # -----------------------------------------------------
    # Boolean conversion
    # -----------------------------------------------------

    @staticmethod
    def _bool_to_int(
        value: Any,
    ) -> int:
        return 1 if bool(value) else 0

    # -----------------------------------------------------
    # Store audit record
    # -----------------------------------------------------

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
        # Checkout information
        # -------------------------------------------------

        record_type: str = "payment",
        checkout_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        currency: Optional[str] = None,
        started_at: Optional[str] = None,

        # -------------------------------------------------
        # Confirmed settlement information
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
    ) -> None:
        """
        Store one complete audit record.

        Settlement fields are stored separately from the
        general API request/response fields so confirmed
        recovered revenue can be measured reliably.
        """

        if timestamp is None:
            timestamp = (
                datetime.now().isoformat(
                    timespec="seconds"
                )
            )

        # If a settlement status was supplied but no explicit
        # check timestamp was provided, use the audit timestamp.
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
                    settlement_checked_at
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
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
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
                ),
            )

            connection.commit()

    # -----------------------------------------------------
    # Convert row to dictionary
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Get all logs
    # -----------------------------------------------------

    def get_all_logs(self) -> list[dict]:
        """
        Return every audit record.
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT
                    id,
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
                    settlement_checked_at

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

    # -----------------------------------------------------
    # Get logs for payment IDs
    # -----------------------------------------------------

    def get_logs_for_payment_ids(
        self,
        payment_ids: list[str],
    ) -> list[dict]:
        """
        Return audit records for the supplied payment IDs.
        """

        if not payment_ids:
            return []

        placeholders = ",".join(
            "?"
            for _ in payment_ids
        )

        query = f"""
            SELECT
                id,
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
                settlement_checked_at

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

    # -----------------------------------------------------
    # Get confirmed settlements
    # -----------------------------------------------------

    def get_confirmed_settlements(
        self,
    ) -> list[dict]:
        """
        Return audit records where Razorpay confirmed
        an actual payment.

        This provides a direct source for calculating
        confirmed recovered revenue.
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT
                    id,
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
                    settlement_checked_at

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

    # -----------------------------------------------------
    # Confirmed recovered amount
    # -----------------------------------------------------

    def get_confirmed_recovered_amount(
        self,
    ) -> float:
        """
        Return total amount actually paid through confirmed
        Payment Link settlements.
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

    # -----------------------------------------------------
    # Count logs
    # -----------------------------------------------------

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