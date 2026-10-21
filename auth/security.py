"""Password hashing (bcrypt) and password policy."""
import re

import bcrypt

from utils.errors import BusinessRuleError


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str) -> None:
    problems = []
    if len(password) < 8:
        problems.append("at least 8 characters")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        problems.append("both letters and digits")
    if len(password.encode("utf-8")) > 72:
        problems.append("at most 72 bytes")
    if problems:
        raise BusinessRuleError("Password must contain " + ", ".join(problems) + ".")
