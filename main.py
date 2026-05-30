import ipaddress
import threading
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from huawei_lte_api.Client import Client
from huawei_lte_api.Connection import Connection
from huawei_lte_api.enums.device import ControlModeEnum

from config import load_config


APP_CONFIG = load_config()
ROUTER_URL = APP_CONFIG.router_url

PUBLIC_IP_TIMEOUT_SECONDS = 5
PUBLIC_IP_RETRY_ATTEMPTS = 3
PUBLIC_IP_RETRY_DELAY_SECONDS = 2
PUBLIC_IP_URL = "https://ifconfig.me/ip"
ROTATE_HEALTH_INITIAL_DELAY_SECONDS = 60
ROTATE_HEALTH_TIMEOUT_SECONDS = 60
ROTATE_HEALTH_POLL_INTERVAL_SECONDS = 5
ROUTER_READY_TIMEOUT_SECONDS = 180
ROUTER_READY_POLL_INTERVAL_SECONDS = 5

ROTATE_STATE_IDLE = "idle"
ROTATE_STATE_ROTATING = "rotating"
ROTATE_STATE_SUCCEEDED = "succeeded"
ROTATE_STATE_FAILED = "failed"

NETWORK_MODES = {
    "3g": ("02", "3FFFFFFF", "7FFFFFFFFFFFFFFF"),
    "4g": ("03", "3FFFFFFF", "7FFFFFFFFFFFFFFF"),
}

app = FastAPI(title="Huawei B818 Control Panel")

DASHBOARD_STATIC_DIR = Path(__file__).resolve().parent / "static"
DASHBOARD_HTML_PATH = Path(__file__).resolve().parent / "templates" / "dashboard.html"

app.mount("/static", StaticFiles(directory=DASHBOARD_STATIC_DIR), name="static")


@dataclass
class RotateStatus:
    """In-memory snapshot of the last rotation workflow."""

    state: str = ROTATE_STATE_IDLE
    started_at: str | None = None
    finished_at: str | None = None
    public_ip_before: str | None = None
    public_ip_after: str | None = None
    message: str | None = None
    error: str | None = None


ROTATE_STATUS_LOCK = threading.Lock()
ROTATE_STATUS = RotateStatus()


@lru_cache(maxsize=1)
def _load_dashboard_html() -> str:
    """Load the dashboard HTML page from disk."""

    if not DASHBOARD_HTML_PATH.exists():
        raise HTTPException(status_code=500, detail="Dashboard HTML file is missing.")

    return DASHBOARD_HTML_PATH.read_text(encoding="utf-8")


def _render_dashboard() -> HTMLResponse:
    """Return the dashboard HTML page."""

    return HTMLResponse(_load_dashboard_html())


def _read_router_status():
    """Return the current router monitoring status."""

    with Connection(ROUTER_URL) as connection:
        client = Client(connection)
        return client.monitoring.status()


def _current_timestamp() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""

    return datetime.now(timezone.utc).isoformat()


def _get_rotate_status_snapshot() -> dict[str, str | None]:
    """Return a copy of the last rotation workflow status."""

    with ROTATE_STATUS_LOCK:
        return asdict(ROTATE_STATUS)


def _update_rotate_status(**updates: str | None) -> None:
    """Update the in-memory rotation workflow status."""

    with ROTATE_STATUS_LOCK:
        for key, value in updates.items():
            setattr(ROTATE_STATUS, key, value)


def _get_public_ip() -> str:
    """Fetch and validate the current public IP address.

    Returns:
        The public IP address as a validated string.

    Raises:
        HTTPException: If the public IP cannot be determined after retries.
    """

    last_error: Exception | None = None

    for attempt in range(1, PUBLIC_IP_RETRY_ATTEMPTS + 1):
        try:
            response = requests.get(
                PUBLIC_IP_URL,
                timeout=PUBLIC_IP_TIMEOUT_SECONDS,
                headers={"Accept": "text/plain"},
            )
            response.raise_for_status()

            public_ip = response.text.strip()
            if not public_ip:
                raise ValueError("Пустой ответ от сервиса определения IP.")

            try:
                ipaddress.ip_address(public_ip)
            except ValueError as exc:
                raise ValueError(f"Сервис определения IP вернул некорректный адрес: {public_ip!r}") from exc

            return public_ip
        except Exception as exc:
            last_error = exc
            if attempt < PUBLIC_IP_RETRY_ATTEMPTS:
                time.sleep(PUBLIC_IP_RETRY_DELAY_SECONDS)

    raise HTTPException(status_code=503, detail=f"Не удалось определить IP: {last_error}")


def _set_network_mode(mode: str) -> None:
    """Set the router to the requested network mode."""

    mode_config = NETWORK_MODES.get(mode.lower())
    if mode_config is None:
        raise HTTPException(status_code=400, detail="Используйте 3g или 4g")

    try:
        with Connection(ROUTER_URL) as connection:
            client = Client(connection)
            network_mode, network_band, lte_band = mode_config
            client.net.set_net_mode(
                networkmode=network_mode,
                networkband=network_band,
                lteband=lte_band,
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ошибка роутера: {exc}") from exc


def _reboot_router() -> None:
    """Reboot the router through the modern Huawei API."""

    try:
        with Connection(ROUTER_URL) as connection:
            client = Client(connection)
            client.device.set_control(ControlModeEnum.REBOOT)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ошибка перезагрузки роутера: {exc}") from exc


def _set_mobile_data(enabled: bool) -> None:
    """Enable or disable the router mobile data switch."""

    try:
        with Connection(ROUTER_URL) as connection:
            client = Client(connection)
            client.dial_up.set_mobile_dataswitch(1 if enabled else 0)
    except Exception as exc:
        action = "включения" if enabled else "выключения"
        raise HTTPException(status_code=500, detail=f"Ошибка {action} mobile data: {exc}") from exc


def _reconnect_router() -> None:
    """Ask the router to reconnect its network session."""

    try:
        with Connection(ROUTER_URL) as connection:
            client = Client(connection)
            client.net.reconnect()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ошибка переподключения роутера: {exc}") from exc


def _wait_for_router_health(
    timeout_seconds: int = ROUTER_READY_TIMEOUT_SECONDS,
    poll_interval_seconds: int = ROUTER_READY_POLL_INTERVAL_SECONDS,
    initial_delay_seconds: int = 0,
) -> None:
    """Wait until the router responds to a monitoring status request.

    Args:
        timeout_seconds: Maximum time to poll after the optional initial delay.
        poll_interval_seconds: Delay between status checks.
        initial_delay_seconds: Optional pause before the first status check.

    Returns:
        None.

    Raises:
        HTTPException: If the router does not become reachable in time.
    """

    if initial_delay_seconds > 0:
        time.sleep(initial_delay_seconds)

    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            _read_router_status()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(poll_interval_seconds)

    detail = f"Роутер не вышел в online за {timeout_seconds} секунд."
    if last_error is not None:
        detail = f"{detail} Последняя ошибка: {last_error}"

    raise HTTPException(status_code=504, detail=detail)


def _run_rotate_sequence() -> None:
    """Execute the rotation workflow in a background thread."""

    public_ip_before: str | None = None
    public_ip_after: str | None = None

    try:
        public_ip_before = _get_public_ip()
        _update_rotate_status(public_ip_before=public_ip_before, message="Переключаемся в 3g.")

        _set_network_mode("3g")
        _reboot_router()
        _wait_for_router_health(
            timeout_seconds=ROTATE_HEALTH_TIMEOUT_SECONDS,
            poll_interval_seconds=ROTATE_HEALTH_POLL_INTERVAL_SECONDS,
            initial_delay_seconds=ROTATE_HEALTH_INITIAL_DELAY_SECONDS,
        )

        _update_rotate_status(message="Возвращаемся в 4g.")
        _set_network_mode("4g")
        _wait_for_router_health(
            timeout_seconds=ROTATE_HEALTH_TIMEOUT_SECONDS,
            poll_interval_seconds=ROTATE_HEALTH_POLL_INTERVAL_SECONDS,
        )

        public_ip_after = _get_public_ip()
        if public_ip_before == public_ip_after:
            _update_rotate_status(
                state=ROTATE_STATE_FAILED,
                finished_at=_current_timestamp(),
                public_ip_after=public_ip_after,
                message="Внешний IP не изменился после ротации.",
                error=None,
            )
            return

        _update_rotate_status(
            state=ROTATE_STATE_SUCCEEDED,
            finished_at=_current_timestamp(),
            public_ip_after=public_ip_after,
            message="Ротация завершена.",
            error=None,
        )
    except Exception as exc:
        _update_rotate_status(
            state=ROTATE_STATE_FAILED,
            finished_at=_current_timestamp(),
            public_ip_before=public_ip_before,
            public_ip_after=public_ip_after,
            message="Ротация не удалась.",
            error=str(exc),
        )


def _start_rotate_sequence() -> None:
    """Start the rotation workflow in a background thread."""

    with ROTATE_STATUS_LOCK:
        if ROTATE_STATUS.state == ROTATE_STATE_ROTATING:
            raise HTTPException(
                status_code=409,
                detail={
                    "status": ROTATE_STATE_ROTATING,
                    "message": "Ротация уже выполняется.",
                    "rotation": asdict(ROTATE_STATUS),
                },
            )

        ROTATE_STATUS.state = ROTATE_STATE_ROTATING
        ROTATE_STATUS.started_at = _current_timestamp()
        ROTATE_STATUS.finished_at = None
        ROTATE_STATUS.public_ip_before = None
        ROTATE_STATUS.public_ip_after = None
        ROTATE_STATUS.message = "Ротация запущена."
        ROTATE_STATUS.error = None

    threading.Thread(target=_run_rotate_sequence, daemon=True).start()


@app.get("/health", summary="Проверка состояния роутера")
def health():
    """Check whether the router is reachable and responsive."""

    try:
        _read_router_status()
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Роутер недоступен: {exc}") from exc


@app.get("/", include_in_schema=False, response_class=HTMLResponse)
def dashboard():
    """Render the local control dashboard."""

    return _render_dashboard()


@app.get("/status", summary="Получить статус роутера")
def status():
    """Return the current router monitoring status and rotation workflow state."""

    rotation = _get_rotate_status_snapshot()

    try:
        router_status = _read_router_status()
    except Exception as exc:
        if rotation["state"] == ROTATE_STATE_ROTATING:
            return {
                "router_status": None,
                "router_error": str(exc),
                "rotation": rotation,
            }

        raise HTTPException(status_code=503, detail=f"Роутер недоступен: {exc}") from exc

    return {
        "router_status": router_status,
        "rotation": rotation,
    }


@app.get("/public-ip", summary="Узнать внешний IP")
def public_ip():
    """Return the current public IP address."""

    return {"public_ip": _get_public_ip()}


@app.get("/mobile-data/on", summary="Включить mobile data")
def mobile_data_on():
    """Enable the router mobile data switch."""

    _set_mobile_data(True)
    return {"status": "ok", "mobile_data": "on"}


@app.get("/mobile-data/off", summary="Выключить mobile data")
def mobile_data_off():
    """Disable the router mobile data switch."""

    _set_mobile_data(False)
    return {"status": "ok", "mobile_data": "off"}


@app.get("/mode/{mode}", summary="Переключить режим сети")
def mode(mode: str):
    """Set the router network mode to 3G or 4G."""

    _set_network_mode(mode)
    return {"status": "ok", "network_mode": mode.lower()}


@app.get("/reboot", summary="Перезагрузить роутер")
def reboot():
    """Reboot the router through the Huawei API."""

    _reboot_router()
    return {"status": "rebooting", "method": "device.set_control(REBOOT)"}


@app.get("/reconnect", summary="Переподключить сеть")
def reconnect():
    """Reconnect the router network session."""

    _reconnect_router()
    return {"status": "ok", "action": "reconnect"}


@app.get("/rotate", summary="Запустить ротацию соединения асинхронно")
def rotate():
    """Start the rotation workflow and return immediately."""

    _start_rotate_sequence()
    return {"status": "rotating"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=APP_CONFIG.app_host, port=APP_CONFIG.app_port)
