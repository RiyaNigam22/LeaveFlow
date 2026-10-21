"""Central configuration. All values come from environment variables / .env."""
import os
from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://leaveflow:leaveflow@localhost:5432/leaveflow",
)
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://leaveflow:leaveflow@localhost:5432/leaveflow_test",
)
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Kolkata")
SESSION_TIMEOUT_MINUTES = _int("SESSION_TIMEOUT_MINUTES", 30)
MAX_LOGIN_ATTEMPTS = _int("MAX_LOGIN_ATTEMPTS", 5)
LOCKOUT_MINUTES = _int("LOCKOUT_MINUTES", 15)
MAX_DOCUMENT_MB = _int("MAX_DOCUMENT_MB", 5)
SICK_LEAVE_CODE = os.getenv("SICK_LEAVE_CODE", "SICK")
SQL_ECHO = os.getenv("SQL_ECHO", "false").lower() == "true"

APP_NAME = "LeaveFlow"

# Roles
ROLE_EMPLOYEE = "EMPLOYEE"
ROLE_MANAGER = "MANAGER"
ROLE_HR = "HR_ADMIN"
ROLES = (ROLE_EMPLOYEE, ROLE_MANAGER, ROLE_HR)

# Leave types that are not absences (excluded from absenteeism calculations), comma separated codes
NON_ABSENCE_CODES = tuple(c.strip() for c in os.getenv("NON_ABSENCE_CODES", "WFH").split(",") if c.strip())
