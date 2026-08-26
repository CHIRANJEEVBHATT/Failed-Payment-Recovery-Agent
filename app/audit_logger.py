import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.config import DATABASE_DIR


class AuditLogger:
    """
    SQLite-based audit logger.

    The audit database stores the decisions and outcomes
    for the current processing batch.

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
        Also migrate older database versions.
        """

        with self._connect() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    timestamp TEXT NOT NULL,

                    payment_id TEXT NOT NULL,
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

                    notes TEXT
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
        }

        for column_name, column_type in (
            required_columns.items()
        ):
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
        payment_id: str,
        customer_name: str,
        email: str,
        amount: float,
        failure_reason: str,
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
                    notes
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    timestamp,
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
                    notes
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
                notes
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

    print("=" * 60)