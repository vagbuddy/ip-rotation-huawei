import time

import requests
from fastapi import FastAPI, HTTPException
from huawei_lte_api.Client import Client
from huawei_lte_api.Connection import Connection

from config import load_config


APP_CONFIG = load_config()
ROUTER_URL = APP_CONFIG.router_url

PUBLIC_IP_TIMEOUT_SECONDS = 5
ROUTER_READY_TIMEOUT_SECONDS = 180
ROUTER_READY_POLL_INTERVAL_SECONDS = 5

NETWORK_MODES = {
    "3g": ("02", "3FFFFFFF", "7FFFFFFFFFFFFFFF"),
    "4g": ("03", "3FFFFFFF", "7FFFFFFFFFFFFFFF"),
}

app = FastAPI(title="Huawei B818 Control Panel")


def _read_router_status():
    """Return the current router monitoring status."""

    with Connection(ROUTER_URL) as connection:
        client = Client(connection)
        return client.monitoring.status()


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
    """Reboot the router through the Huawei API."""

    try:
        with Connection(ROUTER_URL) as connection:
            client = Client(connection)
            client.device.reboot()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ошибка перезагрузки роутера: {exc}") from exc


def _wait_for_router_health(
    timeout_seconds: int = ROUTER_READY_TIMEOUT_SECONDS,
    poll_interval_seconds: int = ROUTER_READY_POLL_INTERVAL_SECONDS,
) -> None:
    """Wait until the router responds to a monitoring status request."""

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


@app.get("/health", summary="Проверка состояния роутера")
def health():
    """Check whether the router is reachable and responsive."""

    try:
        _read_router_status()
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Роутер недоступен: {exc}") from exc


@app.get("/public-ip", summary="Узнать внешний IP")
def public_ip():
    """Return the current public IP address."""

    try:
        response = requests.get("https://ifconfig.me", timeout=PUBLIC_IP_TIMEOUT_SECONDS)
        response.raise_for_status()
        return {"public_ip": response.text.strip()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Не удалось определить IP: {exc}") from exc


@app.get("/rotate", summary="Выполнить ротацию соединения")
def rotate():
    """Rotate the connection by switching to 3G, rebooting, and restoring 4G."""

    _set_network_mode("3g")
    _reboot_router()
    _wait_for_router_health()
    _set_network_mode("4g")
    _wait_for_router_health()
    return {"status": "rotated", "network_mode": "4g"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=APP_CONFIG.app_host, port=APP_CONFIG.app_port)
