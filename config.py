"""Application configuration loaded from environment variables."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote


DEFAULT_ROUTER_IP = "192.168.8.1"
DEFAULT_ROUTER_LOGIN = "admin"
DEFAULT_APP_HOST = "0.0.0.0"
DEFAULT_APP_PORT = 8000


def _load_dotenv_file() -> None:
    """Load key-value pairs from a local .env file if it exists."""

    dotenv_path = Path(__file__).with_name(".env")
    if not dotenv_path.exists():
        return

    for line_number, raw_line in enumerate(dotenv_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped_line = raw_line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue

        if stripped_line.startswith("export "):
            stripped_line = stripped_line[7:].lstrip()

        if "=" not in stripped_line:
            raise RuntimeError(f"Invalid line {line_number} in .env: missing '='.")

        key, value = stripped_line.split("=", 1)
        key = key.strip()
        if not key:
            raise RuntimeError(f"Invalid line {line_number} in .env: empty variable name.")

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def _read_env(name: str, default: Optional[str] = None) -> str:
    """Return a trimmed environment variable value or a default.

    Args:
        name: Environment variable name.
        default: Fallback value when the variable is not set.

    Returns:
        The trimmed environment variable value.

    Raises:
        RuntimeError: If the value is missing and no default was provided.
    """

    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Environment variable {name} is required.")

    value = value.strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} must not be empty.")

    return value


def _read_int_env(name: str, default: int) -> int:
    """Return an integer environment variable or a default.

    Args:
        name: Environment variable name.
        default: Fallback value when the variable is not set.

    Returns:
        Parsed integer value.

    Raises:
        RuntimeError: If the value cannot be parsed as an integer.
    """

    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default

    try:
        return int(raw_value.strip())
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer.") from exc


@dataclass(frozen=True)
class AppConfig:
    """Application settings loaded from environment variables."""

    router_ip: str
    router_login: str
    router_password: str
    app_host: str
    app_port: int

    @property
    def router_url(self) -> str:
        """Build the router URL with URL-encoded credentials."""

        return (
            f"http://{quote(self.router_login, safe='')}:{quote(self.router_password, safe='')}"
            f"@{self.router_ip}/"
        )


def load_config() -> AppConfig:
    """Load the application configuration from environment variables."""

    _load_dotenv_file()

    return AppConfig(
        router_ip=_read_env("ROUTER_IP", DEFAULT_ROUTER_IP),
        router_login=_read_env("ROUTER_LOGIN", DEFAULT_ROUTER_LOGIN),
        router_password=_read_env("ROUTER_PASSWORD"),
        app_host=_read_env("APP_HOST", DEFAULT_APP_HOST),
        app_port=_read_int_env("APP_PORT", DEFAULT_APP_PORT),
    )