import sys
from pathlib import Path


# Add the project root to Python's import path so tests can
# import the app package reliably on Windows and in different
# Python/pytest environments.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))