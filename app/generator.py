import csv
import json
import random
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from app.config import (
    DATA_DIR,
    MAX_SYNTHETIC_RECORDS,
    MIN_SYNTHETIC_RECORDS,
)

from app.models import (
    B2BReceivable,
    CheckoutSession,
    FailedPayment,
    PromiseToPay,
)


# =========================================================
# Synthetic Payment Data
# =========================================================

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


# =========================================================
# B2B Synthetic Data
# =========================================================

COMPANY_NAMES = [
    "Acme Technologies",
    "Nova Retail Pvt Ltd",
    "Vertex Solutions",
    "BluePeak Systems",
    "Apex Enterprises",
    "Orbit Digital",
    "NextGen Logistics",
    "CloudBridge India",
    "Zenith Consulting",
    "PrimeWorks Pvt Ltd",
]


B2B_AMOUNTS = [
    15000.00,
    25000.00,
    40000.00,
    50000.00,
    75000.00,
    100000.00,
    125000.00,
    150000.00,
    200000.00,
]


# =========================================================
# Promise-to-Pay Synthetic Data
# =========================================================

PTP_CONTACT_CHANNELS = [
    "email",
    "sms",
    "whatsapp",
]


PTP_AMOUNTS = [
    2500.00,
    4999.00,
    7500.00,
    9999.00,
    15000.00,
    25000.00,
    40000.00,
    50000.00,
]


# =========================================================
# Helper Functions
# =========================================================

def generate_email(
    name: str,
    index: int,
) -> str:
    """
    Generate a fake email address.
    """

    clean_name = (
        name.lower()
        .replace(" ", ".")
    )

    return (
        f"{clean_name}"
        f"{index}"
        "@example.com"
    )


def generate_phone(
    index: int,
) -> str:
    """
    Generate a varied synthetic 10-digit phone number.

    The generated value avoids obvious repeated-digit
    patterns that Razorpay TEST MODE may reject.
    """

    prefix = (
        9000000000
        + ((index * 73129) % 999999999)
    )

    phone = str(prefix)

    phone = phone[-10:]

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


def generate_last_attempt_time(
    index: int,
) -> str:
    """
    Generate the timestamp of the latest payment attempt.

    Every tenth record is intentionally recent so the
    retry cooldown rule can be demonstrated.
    """

    now = datetime.now()

    if index % 10 == 0:
        minutes_ago = random.randint(
            1,
            9,
        )
    else:
        minutes_ago = random.randint(
            11,
            24 * 60,
        )

    timestamp = (
        now
        - timedelta(
            minutes=minutes_ago,
        )
    )

    return timestamp.isoformat(
        timespec="seconds"
    )


def generate_attempt_count(
    failure_reason: str,
) -> int:
    """
    Generate an attempt count appropriate for the failure.

    Some records intentionally reach three attempts so
    DO_NOT_RETRY can be demonstrated.
    """

    if failure_reason == "fraud_block":
        return random.choice(
            [1, 1, 2]
        )

    if failure_reason == "mandate_failed":
        return random.choice(
            [1, 1, 2]
        )

    return random.randint(
        1,
        3,
    )


# =========================================================
# Failed Payment Generator
# =========================================================

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
            payment_id=(
                f"pay_test_{index:04d}"
            ),
            customer_name=customer_name,
            email=generate_email(
                customer_name,
                index,
            ),
            phone=generate_phone(
                index,
            ),
            amount=generate_amount(),
            failure_reason=failure_reason,
            attempt_count=generate_attempt_count(
                failure_reason,
            ),
            payment_type=random.choice(
                PAYMENT_TYPES
            ),
            last_attempt_at=generate_last_attempt_time(
                index,
            ),
        )

        payments.append(payment)

    return payments


# =========================================================
# JSON Writer
# =========================================================

def save_json(
    payments: list[FailedPayment],
) -> Path:
    """
    Save failed payments as JSON.
    """

    output_directory = Path(
        DATA_DIR
    )

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


# =========================================================
# CSV Writer
# =========================================================

def save_csv(
    payments: list[FailedPayment],
) -> Path:
    """
    Save failed payments as CSV.
    """

    output_directory = Path(
        DATA_DIR
    )

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


# =========================================================
# Public Payment Generator
# =========================================================

def generate_and_save_data() -> list[FailedPayment]:
    """
    Generate synthetic failed-payment data and save
    both JSON and CSV.
    """

    payments = (
        generate_failed_payments()
    )

    json_file = save_json(
        payments
    )

    csv_file = save_csv(
        payments
    )

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


# =========================================================
# Checkout Drop-off Generator
# =========================================================

def generate_checkout_dropoffs(
    count: int = 20,
) -> list[CheckoutSession]:
    """
    Generate synthetic checkout sessions.

    Some sessions are completed while others remain
    abandoned. Abandoned sessions older than 30 minutes
    represent potential revenue at risk.
    """

    sessions = []

    for index in range(
        1,
        count + 1,
    ):
        checkout_id = (
            f"checkout_test_{index:04d}"
        )

        customer_id = (
            f"cust_{random.randint(1000, 9999)}"
        )

        amount = generate_amount()

        started_at = (
            datetime.now()
            - timedelta(
                minutes=random.randint(
                    30,
                    1440,
                )
            )
        )

        completed = (
            random.random() < 0.65
        )

        completed_at = None

        if completed:
            completed_at = (
                started_at
                + timedelta(
                    minutes=random.randint(
                        1,
                        20,
                    )
                )
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


# =========================================================
# B2B Receivables Generator
# =========================================================

def generate_b2b_receivables(
    count: int = 20,
) -> list[B2BReceivable]:
    """
    Generate synthetic B2B invoices.

    The generated records deliberately cover:

        1-7 days
        8-15 days
        16-30 days
        31-60 days
    """

    receivables = []

    overdue_ranges = [
        (1, 7),
        (8, 15),
        (16, 30),
        (31, 60),
    ]

    for index in range(
        1,
        count + 1,
    ):
        company_name = random.choice(
            COMPANY_NAMES
        )

        customer_id = (
            f"b2b_cust_"
            f"{random.randint(1000, 9999)}"
        )

        amount = random.choice(
            B2B_AMOUNTS
        )

        minimum_days, maximum_days = (
            overdue_ranges[
                (index - 1)
                % len(overdue_ranges)
            ]
        )

        days_overdue = random.randint(
            minimum_days,
            maximum_days,
        )

        due_date = (
            datetime.now()
            - timedelta(
                days=days_overdue
            )
        )

        previous_reminders = random.randint(
            0,
            3,
        )

        receivable = B2BReceivable(
            invoice_id=(
                f"inv_test_{index:04d}"
            ),
            company_name=company_name,
            customer_id=customer_id,
            amount=amount,
            currency="INR",
            due_date=due_date,
            days_overdue=days_overdue,
            payment_status="overdue",
            previous_reminders=previous_reminders,
        )

        receivables.append(
            receivable
        )

    return receivables


# =========================================================
# Promise-to-Pay Generator
# =========================================================

def generate_promise_to_pay(
    count: int = 20,
) -> list[PromiseToPay]:
    """
    Generate synthetic Promise-to-Pay records.

    The generator intentionally cycles through every
    decision tier:

        0 -> already paid
        future -> upcoming promise
        today -> due today
        1-3 days overdue
        4-7 days overdue
        >7 days overdue

    A promise is never treated as recovered revenue.
    """

    promises = []

    now = datetime.now()

    for index in range(
        1,
        count + 1,
    ):
        customer_name = (
            CUSTOMER_NAMES[
                (index - 1)
                % len(CUSTOMER_NAMES)
            ]
        )

        customer_id = (
            f"ptp_cust_{index:04d}"
        )

        amount = (
            PTP_AMOUNTS[
                (index - 1)
                % len(PTP_AMOUNTS)
            ]
        )

        created_at = (
            now
            - timedelta(
                days=random.randint(
                    1,
                    14,
                )
            )
        )

        tier = (
            (index - 1) % 6
        )

        status = "promised"

        if tier == 0:
            # Already paid promise.
            promised_date = (
                now
                - timedelta(days=2)
            )
            status = "paid"

        elif tier == 1:
            # Promise is upcoming.
            promised_date = (
                now
                + timedelta(
                    days=random.randint(
                        1,
                        3,
                    )
                )
            )

        elif tier == 2:
            # Due today.
            promised_date = now

        elif tier == 3:
            # 1-3 days overdue.
            promised_date = (
                now
                - timedelta(
                    days=random.randint(
                        1,
                        3,
                    )
                )
            )

        elif tier == 4:
            # 4-7 days overdue.
            promised_date = (
                now
                - timedelta(
                    days=random.randint(
                        4,
                        7,
                    )
                )
            )

        else:
            # More than 7 days overdue.
            promised_date = (
                now
                - timedelta(
                    days=random.randint(
                        8,
                        14,
                    )
                )
            )

        if status == "paid":
            previous_missed_promises = 0
        else:
            previous_missed_promises = random.randint(
                0,
                2,
            )

        promises.append(
            PromiseToPay(
                promise_id=(
                    f"promise_test_{index:04d}"
                ),
                customer_id=customer_id,
                customer_name=customer_name,
                amount=amount,
                currency="INR",
                promised_date=promised_date,
                created_at=created_at,
                status=status,
                previous_missed_promises=(
                    previous_missed_promises
                ),
                contact_channel=random.choice(
                    PTP_CONTACT_CHANNELS
                ),
            )
        )

    return promises


# =========================================================
# Direct Execution
# =========================================================

if __name__ == "__main__":
    generate_and_save_data()