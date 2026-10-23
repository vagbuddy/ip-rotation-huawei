"""Internet connectivity watchdog service that reboots the router when offline."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Callable, Sequence

import requests


logger = logging.getLogger(__name__)

DEFAULT_CONNECTIVITY_URLS: Sequence[str] = (
    "https://1.1.1.1",
    "http://detectportal.firefox.com/canonical.html",
    "http://connectivitycheck.gstatic.com/generate_204",
)

DEFAULT_CHECK_TIMEOUT_SECONDS = 5


def current_utc_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""

    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class WatchdogStatus:
    """In-memory snapshot of the internet connectivity watchdog state."""

    enabled: bool = True
    is_online: bool = True
    offline_since: str | None = None
    offline_duration_seconds: int = 0
    last_online_at: str | None = None
    last_reboot_at: str | None = None
    last_reboot_reason: str | None = None
    consecutive_failures: int = 0
    total_reboots: int = 0


def _is_valid_probe_response(url: str, response: requests.Response) -> bool:
    """Validate that the HTTP response indicates genuine internet connectivity.

    Rejects captive portal redirects (3xx) and validates specific canonical endpoint contents.
    """

    if 300 <= response.status_code < 400 or getattr(response, "is_redirect", False) is True:
        return False

    url_lower = url.lower()
    if "canonical.html" in url_lower:
        # Firefox captive portal endpoint must return 200 with text starting with "success"
        text = getattr(response, "text", "") or ""
        return response.status_code == 200 and text.strip().startswith("success")

    if "generate_204" in url_lower:
        # Android / Chromium captive portal check returns status 204 No Content
        return response.status_code == 204

    # Standard check for generic endpoints (e.g. https://1.1.1.1)
    return 200 <= response.status_code < 300


def check_internet_connectivity(
    urls: Sequence[str] = DEFAULT_CONNECTIVITY_URLS,
    timeout: int = DEFAULT_CHECK_TIMEOUT_SECONDS,
) -> bool:
    """Check whether at least one public endpoint is reachable.

    Uses allow_redirects=False to avoid being fooled by captive portal redirects.

    Args:
        urls: List of endpoints to query in order until one responds.
        timeout: Maximum seconds to wait per request.

    Returns:
        True if any endpoint responds with a valid non-captive probe response, False otherwise.
    """

    for url in urls:
        try:
            response = requests.get(url, timeout=timeout, allow_redirects=False)
            if _is_valid_probe_response(url, response):
                return True
        except Exception:
            continue

    return False


class WatchdogService:
    """Monitors internet connectivity and triggers a router reboot if down too long."""

    def __init__(
        self,
        enabled: bool = True,
        timeout_seconds: int = 900,
        check_interval_seconds: int = 30,
        reboot_cooldown_seconds: int = 300,
        reboot_fn: Callable[[], None] | None = None,
        is_rotating_fn: Callable[[], bool] | None = None,
        connectivity_checker: Callable[[], bool] | None = None,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        self.check_interval_seconds = check_interval_seconds
        self.reboot_cooldown_seconds = reboot_cooldown_seconds
        self.reboot_fn = reboot_fn
        self.is_rotating_fn = is_rotating_fn or (lambda: False)
        self.connectivity_checker = connectivity_checker or check_internet_connectivity
        self.time_fn = time_fn or time.monotonic

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._is_online = True
        self._offline_since_monotonic: float | None = None
        self._offline_since_iso: str | None = None
        self._last_online_iso: str | None = None
        self._last_reboot_monotonic: float | None = None
        self._last_reboot_iso: str | None = None
        self._last_reboot_reason: str | None = None
        self._consecutive_failures = 0
        self._total_reboots = 0

    def get_status(self) -> dict[str, Any]:
        """Return a dictionary snapshot of the current watchdog state."""

        with self._lock:
            duration = 0
            if self._offline_since_monotonic is not None:
                duration = max(0, int(self.time_fn() - self._offline_since_monotonic))

            return asdict(
                WatchdogStatus(
                    enabled=self.enabled,
                    is_online=self._is_online,
                    offline_since=self._offline_since_iso,
                    offline_duration_seconds=duration,
                    last_online_at=self._last_online_iso,
                    last_reboot_at=self._last_reboot_iso,
                    last_reboot_reason=self._last_reboot_reason,
                    consecutive_failures=self._consecutive_failures,
                    total_reboots=self._total_reboots,
                )
            )

    def tick(self) -> bool:
        """Run a single watchdog health check cycle.

        Returns:
            True if a reboot was triggered during this check, False otherwise.
        """

        if not self.enabled:
            return False

        # If a planned IP rotation workflow is in progress, do not treat the temporary
        # network drop as an unexpected failure.
        if self.is_rotating_fn():
            return False

        online = self.connectivity_checker()
        now_mono = self.time_fn()
        now_iso = current_utc_iso()
        reboot_triggered = False

        with self._lock:
            if online:
                self._is_online = True
                self._offline_since_monotonic = None
                self._offline_since_iso = None
                self._consecutive_failures = 0
                self._last_online_iso = now_iso
            else:
                self._is_online = False
                self._consecutive_failures += 1
                if self._offline_since_monotonic is None:
                    self._offline_since_monotonic = now_mono
                    self._offline_since_iso = now_iso

                elapsed = now_mono - self._offline_since_monotonic

                in_cooldown = False
                if self._last_reboot_monotonic is not None:
                    time_since_reboot = now_mono - self._last_reboot_monotonic
                    if time_since_reboot < self.reboot_cooldown_seconds:
                        in_cooldown = True

                if elapsed >= self.timeout_seconds and not in_cooldown:
                    reason = (
                        f"Internet offline for {int(elapsed)}s "
                        f"(threshold: {self.timeout_seconds}s)"
                    )
                    logger.warning("Watchdog triggering router reboot: %s", reason)
                    self._last_reboot_monotonic = now_mono
                    self._last_reboot_iso = now_iso
                    self._last_reboot_reason = reason
                    self._total_reboots += 1
                    # Advance the offline start anchor to now so that another reboot won't
                    # be triggered until a full timeout period elapses again.
                    self._offline_since_monotonic = now_mono
                    reboot_triggered = True

        if reboot_triggered and self.reboot_fn is not None:
            try:
                self.reboot_fn()
            except Exception as exc:
                logger.error("Watchdog failed to trigger router reboot: %s", exc)

        return reboot_triggered

    def _run_loop(self) -> None:
        """Continuously run watchdog checks in a background thread until stopped."""

        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                logger.error("Unexpected error in watchdog tick: %s", exc)

            self._stop_event.wait(self.check_interval_seconds)

    def start(self) -> None:
        """Start the watchdog background monitoring thread."""

        if not self.enabled:
            return

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop, name="RouterWatchdog", daemon=True
            )
            self._thread.start()
            logger.info(
                "Router watchdog started (timeout=%ss, interval=%ss, cooldown=%ss)",
                self.timeout_seconds,
                self.check_interval_seconds,
                self.reboot_cooldown_seconds,
            )

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the watchdog background monitoring thread."""

        self._stop_event.set()
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=timeout)
                self._thread = None
            logger.info("Router watchdog stopped")
