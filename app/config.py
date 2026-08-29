import os
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------
# Project directories
# ---------------------------------------------------------

BASE_DIR = Path(
    __file__
).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

DATABASE_DIR = BASE_DIR / "database"

LOGS_DIR = BASE_DIR / "logs"

OUTPUT_DIR = BASE_DIR / "output"


# ---------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------

ENV_FILE = BASE_DIR / ".env"

load_dotenv(
    dotenv_path=ENV_FILE
)


# ---------------------------------------------------------
# Razorpay configuration
# ---------------------------------------------------------

RAZORPAY_KEY_ID = os.getenv(
    "RAZORPAY_KEY_ID",
    "",
).strip()

RAZORPAY_KEY_SECRET = os.getenv(
    "RAZORPAY_KEY_SECRET",
    "",
).strip()

RAZORPAY_BASE_URL = (
    "https://api.razorpay.com/v1"
)

# ---------------------------------------------------------
# OpenAI configuration
# ---------------------------------------------------------

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY",
    "",
).strip()

OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5.6-luna",
).strip()

# ---------------------------------------------------------
# Test Mode API safety cap
# ---------------------------------------------------------

def get_max_real_api_calls() -> int:
    """
    Read MAX_REAL_API_CALLS from .env.

    The project requirement defaults this to 20.

    A minimum value of 0 is allowed because setting it to
    zero is useful when running the project without making
    any real Razorpay API calls.
    """

    raw_value = os.getenv(
        "MAX_REAL_API_CALLS",
        "20",
    ).strip()

    try:
        value = int(raw_value)
    except ValueError:
        raise ValueError(
            "MAX_REAL_API_CALLS must be an integer."
        )

    if value < 0:
        raise ValueError(
            "MAX_REAL_API_CALLS cannot be negative."
        )

    return value


MAX_REAL_API_CALLS = (
    get_max_real_api_calls()
)


# ---------------------------------------------------------
# Synthetic dataset size
# ---------------------------------------------------------

MIN_SYNTHETIC_RECORDS = 60

MAX_SYNTHETIC_RECORDS = 100


# ---------------------------------------------------------
# Utility
# ---------------------------------------------------------

def ensure_directories() -> None:
    """
    Create runtime directories if they don't exist.
    """

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    DATABASE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    LOGS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


# Create the directories when the configuration module
# is imported.
ensure_directories()


# ---------------------------------------------------------
# Configuration summary
# ---------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("FAILED PAYMENT RECOVERY AGENT CONFIGURATION")
    print("=" * 60)

    print(
        "Project:",
        BASE_DIR,
    )

    print(
        "Data directory:",
        DATA_DIR,
    )

    print(
        "Database directory:",
        DATABASE_DIR,
    )

    print(
        "Logs directory:",
        LOGS_DIR,
    )

    print(
        "Output directory:",
        OUTPUT_DIR,
    )

    print(
        "Razorpay key configured:",
        bool(RAZORPAY_KEY_ID),
    )

    print(
        "Razorpay secret configured:",
        bool(RAZORPAY_KEY_SECRET),
    )

    print(
        "Razorpay base URL:",
        RAZORPAY_BASE_URL,
    )

    print(
        "Maximum real API calls:",
        MAX_REAL_API_CALLS,
    )

    print(
        "Synthetic record range:",
        f"{MIN_SYNTHETIC_RECORDS}-"
        f"{MAX_SYNTHETIC_RECORDS}",
    )
    print(
        "OpenAI API key configured:",
        bool(OPENAI_API_KEY),
    )

    print(
        "OpenAI model:",
        OPENAI_MODEL,
    )
    print("=" * 60)
 