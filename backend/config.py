"""Environment-backed runtime configuration for Stash."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")


def get_env(name: str, default: str | None = None, *, required: bool = False) -> str:
    """Return an environment variable, optionally enforcing that it is present."""
    value = os.getenv(name)
    if value is None or value == "":
        if required:
            raise RuntimeError(f"{name} is not configured.")
        return default or ""
    return value


def get_bool_env(name: str, default: bool = False) -> bool:
    """Return a boolean environment variable value."""
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def get_int_env(name: str, default: int) -> int:
    """Return an integer environment variable value."""
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def get_csv_env(name: str, *, required: bool = False) -> list[str]:
    """Return a comma-separated environment variable as a list."""
    raw_value = get_env(name, required=required)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def get_path_env(name: str, default: str) -> Path:
    """Return an environment variable as a filesystem path."""
    return Path(get_env(name, default))
