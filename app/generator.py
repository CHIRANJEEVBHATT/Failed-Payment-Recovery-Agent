import csv
import json
import random
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from app.config import (
    DATA_DIR,
    MAX_SYNTHETIC_RECORDS,
    MIN_SYNTHETIC_RECORDS,
)

from app.models import CheckoutSession, FailedPayment
from app.models import FailedPayment


# ---------------------------------------------------------
# Synthetic data options
# ---------------------------------------------------------

CUSTOMER_NAMES = [
    "Aarav Sharma",
    "Vivaan Patel",
    "Aditya Kumar",
    "Arjun Singh",
    "Rohan Mehta",
    "Karan Shah",
    "Rahul Verma",
    "Ananya Iyer",
    "Diya Nair",
    "Ishita Rao",
    "Priya Menon",
    "Sneha Gupta",
    "Neha Kapoor",
    "Meera Joshi",
    "Kavya Reddy",
]

FAILURE_REASONS = [
    "insufficient_funds",
    "card_expired",
    "bank_timeout",
    "otp_failed",
    "fraud_block",
    "mandate_failed",
]

PAYMENT_TYPES = [
    "one-time",
    "subscription",
]


# ---------------------------------------------------------
# Helper functions
# ---------------------------------------------------------

def generate_email(name: str, index: int) -> str:
    """
    Generate a fake email address.
    """

    clean_name = (
        name.lower()
        .replace(" ", ".")
    )

    return f"{clean_name}{index}@example.com"


def generate_phone(index: int) -> str:
    """
    Generate a unique-looking fake phone number.

    The previous implementation could generate values such
    as 9999999999, which Razorpay Test Mode rejects because
    repeated digits are not allowed.

    We therefore use a deterministic 10-digit number with
    varied digits.
    """

    # Generate a varied number from the record index.
    #
    # Example:
    # index = 1 -> 9123456781
    # index = 2 -> 9234567892
    #
    # The values contain varied digits and avoid obvious
    # repeated-digit test numbers.

    prefix = 9000000000 + (
        (index * 73129) % 999999999
    )

    phone = str(prefix)

    # Make absolutely sure we have exactly 10 digits.
    phone = phone[-10:]

    # If an unlikely repeated-digit number appears,
    # generate a known varied fallback.
    if len(set(phone)) < 5:
        phone = (
            f"9{index % 10}"
            f"8{(index + 1) % 10}"
            f"7{(index + 2) % 10}"
            f"6{(index + 3) % 10}"
            f"5{(index + 4) % 10}"
            f"4{(index + 5) % 10}"
            f"3{(index + 6) % 10}"
            f"2{(index + 7) % 10}"
        )

    return phone


def generate_amount() -> float:
    """
    Generate a realistic-looking payment amount.
    """

    amounts = [
        499.00,
        799.00,
        999.00,
        1499.00,
        1999.00,
        2499.00,
        2999.00,
        3999.00,
        4999.00,
        5999.00,
        9999.00,
    ]

    return random.choice(amounts)


def generate_last_attempt_time(index: int) -> str:
    """
    Generate a timestamp for the latest payment attempt.

    Most records are older than 10 minutes.

    Every tenth record is intentionally recent so the
    decision engine can demonstrate the retry cooldown rule.
    """

    now = datetime.now()

    if index % 10 == 0:
        # Inside the 10-minute cooldown window.
        minutes_ago = random.randint(1, 9)
    else:
        # Outside the cooldown window.
        minutes_ago = random.randint(
            11,
            24 * 60,
        )

    timestamp = (
        now - timedelta(minutes=minutes_ago)
    )

    return timestamp.isoformat(
        timespec="seconds"
    )


def generate_attempt_count(
    failure_reason: str,
) -> int:
    """
    Generate an attempt count appropriate for the failure.

    Some records intentionally reach 3 attempts so that
    DO_NOT_RETRY can be demonstrated.
    """

    if failure_reason == "fraud_block":
        return random.choice([1, 1, 2])

    if failure_reason == "mandate_failed":
        return random.choice([1, 1, 2])

    return random.randint(1, 3)


# ---------------------------------------------------------
# Main generator
# ---------------------------------------------------------

def generate_failed_payments() -> list[FailedPayment]:
    """
    Generate between 60 and 100 synthetic failed payments.
    """

    record_count = random.randint(
        MIN_SYNTHETIC_RECORDS,
        MAX_SYNTHETIC_RECORDS,
    )

    payments = []

    for index in range(
        1,
        record_count + 1,
    ):
        customer_name = random.choice(
            CUSTOMER_NAMES
        )

        failure_reason = random.choice(
            FAILURE_REASONS
        )

        payment = FailedPayment(
            payment_id=f"pay_test_{index:04d}",
            customer_name=customer_name,
            email=generate_email(
                customer_name,
                index,
            ),
            phone=generate_phone(index),
            amount=generate_amount(),
            failure_reason=failure_reason,
            attempt_count=generate_attempt_count(
                failure_reason
            ),
            payment_type=random.choice(
                PAYMENT_TYPES
            ),
            last_attempt_at=generate_last_attempt_time(
                index
            ),
        )

        payments.append(payment)

    return payments


# ---------------------------------------------------------
# JSON writer
# ---------------------------------------------------------

def save_json(
    payments: list[FailedPayment],
) -> Path:
    """
    Save failed payments as JSON.
    """

    output_directory = Path(DATA_DIR)

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = (
        output_directory
        / "failed_payments.json"
    )

    data = [
        asdict(payment)
        for payment in payments
    ]

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            indent=4,
        )

    return output_file


# ---------------------------------------------------------
# CSV writer
# ---------------------------------------------------------

def save_csv(
    payments: list[FailedPayment],
) -> Path:
    """
    Save failed payments as CSV.
    """

    output_directory = Path(DATA_DIR)

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = (
        output_directory
        / "failed_payments.csv"
    )

    fieldnames = [
        "payment_id",
        "customer_name",
        "email",
        "phone",
        "amount",
        "failure_reason",
        "attempt_count",
        "payment_type",
        "last_attempt_at",
    ]

    with output_file.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for payment in payments:
            writer.writerow(
                asdict(payment)
            )

    return output_file


# ---------------------------------------------------------
# Public generator function
# ---------------------------------------------------------

def generate_and_save_data() -> list[FailedPayment]:
    """
    Generate synthetic data and save both JSON and CSV.
    """

    payments = generate_failed_payments()

    json_file = save_json(payments)
    csv_file = save_csv(payments)

    print(
        f"Generated {len(payments)} "
        f"failed payment records."
    )

    print(
        f"JSON saved to: {json_file}"
    )

    print(
        f"CSV saved to:  {csv_file}"
    )

    return payments

def generate_checkout_dropoffs(
    count: int = 20,
) -> list[CheckoutSession]:
    """
    Generate synthetic checkout sessions.

    Some sessions are completed and some are abandoned.
    Abandoned sessions older than 30 minutes represent
    potential revenue at risk.
    """

    sessions = []

    for index in range(1, count + 1):
        checkout_id = f"checkout_test_{index:04d}"
        customer_id = f"cust_{random.randint(1000, 9999)}"

        amount = generate_amount()

        started_at = datetime.now() - timedelta(
            minutes=random.randint(30, 1440)
        )

        # Roughly 65% completed, 35% abandoned.
        completed = random.random() < 0.65

        completed_at = None

        if completed:
            completed_at = started_at + timedelta(
                minutes=random.randint(1, 20)
            )

        sessions.append(
            CheckoutSession(
                checkout_id=checkout_id,
                customer_id=customer_id,
                amount=amount,
                currency="INR",
                started_at=started_at,
                completed=completed,
                completed_at=completed_at,
            )
        )

    return sessions

# ---------------------------------------------------------
# Direct execution
# ---------------------------------------------------------

if __name__ == "__main__":
    generate_and_save_data()