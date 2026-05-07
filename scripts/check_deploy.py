"""Pre-deploy readiness checks for Stash production releases."""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ENV_PATH = BACKEND / ".env"
ENV_EXAMPLE_PATH = BACKEND / ".env.example"
OPTIONAL_ENV_KEYS = {
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GEMINI_TRANSCRIPTION_INLINE_MAX_BYTES",
    "PORT",
    "SKIP_AUTH",
    "STASH_TMP_DIR",
    "YTDLP_COOKIES_BROWSER",
    "YTDLP_COOKIES_FILE",
}


def _parse_env(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE env file without expanding values."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env() -> dict[str, str]:
    """Return process environment merged with backend .env values."""
    merged = dict(os.environ)
    if ENV_PATH.exists():
        merged.update(_parse_env(ENV_PATH))
    return merged


def _run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command and capture combined output."""
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _print_result(name: str, passed: bool, detail: str = "") -> bool:
    """Print a colored checklist result."""
    symbol = "\033[32mOK\033[0m" if passed else "\033[31mFAIL\033[0m"
    suffix = f" - {detail}" if detail else ""
    print(f"{symbol} {name}{suffix}")
    return passed


def check_env_matches_example() -> bool:
    """Check backend .env has exactly the same keys as .env.example."""
    if not ENV_PATH.exists():
        return _print_result("Environment file", False, "backend/.env is missing")
    if not ENV_EXAMPLE_PATH.exists():
        return _print_result("Environment file", False, "backend/.env.example is missing")

    env_values = _parse_env(ENV_PATH)
    example_values = _parse_env(ENV_EXAMPLE_PATH)
    missing = sorted(set(example_values) - set(env_values) - OPTIONAL_ENV_KEYS)
    empty = sorted(
        key
        for key, value in env_values.items()
        if key in example_values and key not in OPTIONAL_ENV_KEYS and not value
    )

    if missing or empty:
        detail_parts = []
        if missing:
            detail_parts.append(f"missing: {', '.join(missing)}")
        if empty:
            detail_parts.append(f"empty: {', '.join(empty)}")
        return _print_result("Environment file", False, "; ".join(detail_parts))

    return _print_result("Environment file", True)


def check_docker_builds(env: dict[str, str]) -> bool:
    """Check backend and frontend Docker images build successfully."""
    backend_result = _run(["docker", "build", "-t", "stash-backend-check", "-f", "backend/Dockerfile", "."], ROOT, env)
    if backend_result.returncode != 0:
        return _print_result("Docker builds", False, backend_result.stdout.splitlines()[-1] if backend_result.stdout else "")

    frontend_result = _run(["docker", "build", "-t", "stash-frontend-check", "."], FRONTEND, env)
    if frontend_result.returncode != 0:
        return _print_result("Docker builds", False, frontend_result.stdout.splitlines()[-1] if frontend_result.stdout else "")

    return _print_result("Docker builds", True)


def check_pytest(env: dict[str, str]) -> bool:
    """Run backend tests."""
    result = _run([sys.executable, "-m", "pytest", "tests/"], BACKEND, env)
    return _print_result("Pytest", result.returncode == 0, result.stdout.splitlines()[-1] if result.returncode else "")


def check_alembic_current(env: dict[str, str]) -> bool:
    """Check the connected database is at the current Alembic head."""
    current = _run([sys.executable, "-m", "alembic", "current"], BACKEND, env)
    heads = _run([sys.executable, "-m", "alembic", "heads"], BACKEND, env)
    if current.returncode != 0:
        return _print_result("Alembic migrations", False, current.stdout.splitlines()[-1] if current.stdout else "")
    if heads.returncode != 0:
        return _print_result("Alembic migrations", False, heads.stdout.splitlines()[-1] if heads.stdout else "")

    current_text = current.stdout.strip()
    heads_text = heads.stdout.strip()
    head_revision = heads_text.split()[0] if heads_text else ""
    passed = bool(head_revision and head_revision in current_text and "(head)" in current_text)
    return _print_result("Alembic migrations", passed, "" if passed else f"current={current_text} heads={heads_text}")


def check_r2_access(env: dict[str, str]) -> bool:
    """Check the configured R2 bucket is reachable."""
    try:
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=f"https://{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=env["R2_ACCESS_KEY"],
            aws_secret_access_key=env["R2_SECRET_KEY"],
            region_name="auto",
        )
        client.head_bucket(Bucket=env["R2_BUCKET_NAME"])
        return _print_result("R2 bucket", True)
    except Exception as exc:
        return _print_result("R2 bucket", False, str(exc))


def check_telegram_token(env: dict[str, str]) -> bool:
    """Call Telegram getMe to verify the bot token."""
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return _print_result("Telegram bot token", False, "TELEGRAM_BOT_TOKEN is empty")

    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=10) as response:
            passed = response.status == 200
            return _print_result("Telegram bot token", passed)
    except (urllib.error.URLError, TimeoutError) as exc:
        return _print_result("Telegram bot token", False, str(exc))


def main() -> int:
    """Run all deploy checks and return a process exit code."""
    env = _env()
    checks = [
        check_env_matches_example(),
        check_docker_builds(env),
        check_pytest(env),
        check_alembic_current(env),
        check_r2_access(env),
        check_telegram_token(env),
    ]
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
