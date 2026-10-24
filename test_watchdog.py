"""Unit tests for the internet connectivity watchdog service and endpoints."""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("ROUTER_PASSWORD", "test-password")

import config
import main
import watchdog


class CheckInternetConnectivityTests(unittest.TestCase):
    """Verify endpoint checking logic in check_internet_connectivity."""

    @patch("watchdog.requests.get")
    def test_returns_true_when_first_url_succeeds(self, mock_get) -> None:
        mock_response = MagicMock(status_code=200)
        mock_get.return_value = mock_response

        self.assertTrue(watchdog.check_internet_connectivity(["http://test.local/1"]))
        mock_get.assert_called_once_with(
            "http://test.local/1",
            timeout=watchdog.DEFAULT_CHECK_TIMEOUT_SECONDS,
            allow_redirects=False,
        )

    @patch("watchdog.requests.get")
    def test_falls_back_to_second_url_when_first_fails(self, mock_get) -> None:
        mock_get.side_effect = [
            Exception("Connection refused"),
            MagicMock(status_code=204),
        ]

        result = watchdog.check_internet_connectivity(
            ["http://bad.local", "http://good.local"]
        )
        self.assertTrue(result)
        self.assertEqual(mock_get.call_count, 2)

    @patch("watchdog.requests.get")
    def test_returns_false_when_all_endpoints_fail(self, mock_get) -> None:
        mock_get.side_effect = [
            Exception("Timeout"),
            MagicMock(status_code=500),
            Exception("DNS error"),
        ]

        result = watchdog.check_internet_connectivity(
            ["http://one.local", "http://two.local", "http://three.local"]
        )
        self.assertFalse(result)

    @patch("watchdog.requests.get")
    def test_rejects_captive_portal_redirects(self, mock_get) -> None:
        mock_get.side_effect = [
            MagicMock(status_code=307, is_redirect=True),
            MagicMock(status_code=302, is_redirect=True),
        ]

        result = watchdog.check_internet_connectivity(
            [
                "http://detectportal.firefox.com/canonical.html",
                "http://connectivitycheck.gstatic.com/generate_204",
            ]
        )
        self.assertFalse(result)

    @patch("watchdog.requests.get")
    def test_validates_firefox_canonical_html_body(self, mock_get) -> None:
        # Router captive portal returning 200 OK with HTML page must be rejected
        mock_get.return_value = MagicMock(status_code=200, text="<html><body>Huawei</body></html>")
        self.assertFalse(
            watchdog.check_internet_connectivity(["http://detectportal.firefox.com/canonical.html"])
        )

        # Genuine Firefox response ("success\n") must be accepted
        mock_get.return_value = MagicMock(status_code=200, text="success\n")
        self.assertTrue(
            watchdog.check_internet_connectivity(["http://detectportal.firefox.com/canonical.html"])
        )

    @patch("watchdog.requests.get")
    def test_validates_generate_204_requires_exact_204(self, mock_get) -> None:
        # Captive portal returning 200 OK on generate_204 must be rejected
        mock_get.return_value = MagicMock(status_code=200, text="OK")
        self.assertFalse(
            watchdog.check_internet_connectivity(["http://connectivitycheck.gstatic.com/generate_204"])
        )

        # Genuine 204 No Content must be accepted
        mock_get.return_value = MagicMock(status_code=204, text="")
        self.assertTrue(
            watchdog.check_internet_connectivity(["http://connectivitycheck.gstatic.com/generate_204"])
        )


class WatchdogServiceTests(unittest.TestCase):
    """Verify WatchdogService state transitions and reboot triggering."""

    def setUp(self) -> None:
        self.simulated_time = 1000.0
        self.reboot_called = 0

    def fake_time(self) -> float:
        return self.simulated_time

    def fake_reboot(self) -> None:
        self.reboot_called += 1

    def test_tick_when_online_maintains_healthy_status(self) -> None:
        service = watchdog.WatchdogService(
            enabled=True,
            timeout_seconds=900,
            check_interval_seconds=30,
            reboot_fn=self.fake_reboot,
            connectivity_checker=lambda: True,
            time_fn=self.fake_time,
        )

        triggered = service.tick()

        self.assertFalse(triggered)
        self.assertEqual(self.reboot_called, 0)
        status = service.get_status()
        self.assertTrue(status["is_online"])
        self.assertIsNone(status["offline_since"])
        self.assertEqual(status["offline_duration_seconds"], 0)
        self.assertIsNotNone(status["last_online_at"])
        self.assertEqual(status["consecutive_failures"], 0)

    def test_tick_when_offline_tracks_duration_and_does_not_reboot_before_timeout(self) -> None:
        service = watchdog.WatchdogService(
            enabled=True,
            timeout_seconds=900,
            check_interval_seconds=30,
            reboot_fn=self.fake_reboot,
            connectivity_checker=lambda: False,
            time_fn=self.fake_time,
        )

        # First failure at t=1000
        service.tick()
        status = service.get_status()
        self.assertFalse(status["is_online"])
        self.assertIsNotNone(status["offline_since"])
        self.assertEqual(status["consecutive_failures"], 1)
        self.assertEqual(self.reboot_called, 0)

        # Advance 300 seconds (5 minutes offline)
        self.simulated_time += 300
        triggered = service.tick()
        self.assertFalse(triggered)
        self.assertEqual(self.reboot_called, 0)
        status = service.get_status()
        self.assertEqual(status["offline_duration_seconds"], 300)
        self.assertEqual(status["consecutive_failures"], 2)

    def test_tick_triggers_reboot_at_15_minutes(self) -> None:
        service = watchdog.WatchdogService(
            enabled=True,
            timeout_seconds=900,
            check_interval_seconds=30,
            reboot_cooldown_seconds=300,
            reboot_fn=self.fake_reboot,
            connectivity_checker=lambda: False,
            time_fn=self.fake_time,
        )

        # Start of failure
        service.tick()
        self.assertEqual(self.reboot_called, 0)

        # Advance exactly 900 seconds
        self.simulated_time += 900
        triggered = service.tick()

        self.assertTrue(triggered)
        self.assertEqual(self.reboot_called, 1)
        status = service.get_status()
        self.assertEqual(status["total_reboots"], 1)
        self.assertIsNotNone(status["last_reboot_at"])
        self.assertIn("threshold: 900s", status["last_reboot_reason"])

    def test_cooldown_prevents_duplicate_reboots_immediately_after(self) -> None:
        service = watchdog.WatchdogService(
            enabled=True,
            timeout_seconds=900,
            check_interval_seconds=30,
            reboot_cooldown_seconds=300,
            reboot_fn=self.fake_reboot,
            connectivity_checker=lambda: False,
            time_fn=self.fake_time,
        )

        # First failure at t=1000
        service.tick()

        # Trigger reboot at t=1900
        self.simulated_time += 900
        service.tick()
        self.assertEqual(self.reboot_called, 1)

        # 1 minute later (t=1960), still offline, within 300s cooldown
        self.simulated_time += 60
        triggered = service.tick()
        self.assertFalse(triggered)
        self.assertEqual(self.reboot_called, 1)

    def test_tick_recovers_when_internet_comes_back(self) -> None:
        is_connected = False

        def checker():
            return is_connected

        service = watchdog.WatchdogService(
            enabled=True,
            timeout_seconds=900,
            reboot_fn=self.fake_reboot,
            connectivity_checker=checker,
            time_fn=self.fake_time,
        )

        # Down for 5 minutes
        service.tick()
        self.simulated_time += 300
        service.tick()
        self.assertFalse(service.get_status()["is_online"])

        # Internet restored
        is_connected = True
        self.simulated_time += 30
        triggered = service.tick()

        self.assertFalse(triggered)
        status = service.get_status()
        self.assertTrue(status["is_online"])
        self.assertIsNone(status["offline_since"])
        self.assertEqual(status["offline_duration_seconds"], 0)
        self.assertEqual(status["consecutive_failures"], 0)

    def test_tick_skipped_when_rotating(self) -> None:
        service = watchdog.WatchdogService(
            enabled=True,
            timeout_seconds=900,
            reboot_fn=self.fake_reboot,
            is_rotating_fn=lambda: True,
            connectivity_checker=lambda: False,
            time_fn=self.fake_time,
        )

        # Even after 1000 seconds, if rotation is active, tick should do nothing
        self.simulated_time += 1000
        triggered = service.tick()

        self.assertFalse(triggered)
        self.assertEqual(self.reboot_called, 0)

    def test_tick_skipped_when_disabled(self) -> None:
        service = watchdog.WatchdogService(
            enabled=False,
            timeout_seconds=900,
            reboot_fn=self.fake_reboot,
            connectivity_checker=lambda: False,
            time_fn=self.fake_time,
        )

        self.simulated_time += 1000
        triggered = service.tick()

        self.assertFalse(triggered)
        self.assertEqual(self.reboot_called, 0)
        status = service.get_status()
        self.assertFalse(status["enabled"])


class ConfigWatchdogTests(unittest.TestCase):
    """Verify parsing and defaults for watchdog settings in config.py."""

    def test_bool_env_parser(self) -> None:
        with patch.dict(os.environ, {"WATCHDOG_ENABLED": "true"}):
            self.assertTrue(config._read_bool_env("WATCHDOG_ENABLED", False))

        with patch.dict(os.environ, {"WATCHDOG_ENABLED": "false"}):
            self.assertFalse(config._read_bool_env("WATCHDOG_ENABLED", True))

        with patch.dict(os.environ, {"WATCHDOG_ENABLED": "0"}):
            self.assertFalse(config._read_bool_env("WATCHDOG_ENABLED", True))

        with patch.dict(os.environ, {"WATCHDOG_ENABLED": "invalid"}):
            with self.assertRaises(RuntimeError):
                config._read_bool_env("WATCHDOG_ENABLED", True)

    def test_load_config_defaults(self) -> None:
        with patch.dict(os.environ, {"ROUTER_PASSWORD": "secret"}, clear=True):
            app_cfg = config.load_config()
            self.assertTrue(app_cfg.watchdog_enabled)
            self.assertEqual(app_cfg.watchdog_timeout_seconds, 900)
            self.assertEqual(app_cfg.watchdog_check_interval_seconds, 30)
            self.assertEqual(app_cfg.watchdog_reboot_cooldown_seconds, 300)


class MainWatchdogEndpointsTests(unittest.TestCase):
    """Verify /watchdog and /status endpoints response payloads."""

    def test_watchdog_endpoint(self) -> None:
        data = main.watchdog()
        self.assertIn("enabled", data)
        self.assertIn("is_online", data)
        self.assertIn("total_reboots", data)
        self.assertIn("offline_duration_seconds", data)

    @patch("main._read_router_status", return_value={"ConnectionStatus": "901"})
    def test_status_endpoint_includes_watchdog_field(self, mock_read_status) -> None:
        data = main.status()
        self.assertIn("router_status", data)
        self.assertIn("rotation", data)
        self.assertIn("watchdog", data)
        self.assertIn("is_online", data["watchdog"])

    @patch("main._ensure_4g_mode")
    @patch("main.check_internet_connectivity")
    @patch("main._read_router_status", return_value={"ConnectionStatus": "902", "WanIPAddress": None})
    def test_check_connectivity_returns_false_when_router_disconnected(
        self, mock_read_status, mock_probe, mock_ensure_4g
    ) -> None:
        self.assertFalse(main._check_connectivity())
        mock_probe.assert_not_called()
        mock_ensure_4g.assert_called_once()

    @patch("main._ensure_4g_mode")
    @patch("main.check_internet_connectivity", return_value=True)
    @patch("main._read_router_status", return_value={"ConnectionStatus": "901", "WanIPAddress": "10.0.0.1"})
    def test_check_connectivity_probes_when_router_connected(
        self, mock_read_status, mock_probe, mock_ensure_4g
    ) -> None:
        self.assertTrue(main._check_connectivity())
        mock_probe.assert_called_once()
        mock_ensure_4g.assert_not_called()

    @patch("main.Client")
    @patch("main.Connection")
    def test_ensure_4g_mode_switches_when_not_4g(self, mock_conn, mock_client_cls) -> None:
        mock_client = MagicMock()
        mock_client.net.net_mode.return_value = {"NetworkMode": "02"}
        mock_client_cls.return_value = mock_client

        result = main._ensure_4g_mode()
        self.assertTrue(result)
        mock_client.net.set_net_mode.assert_called_once_with(
            networkmode="03",
            networkband="3FFFFFFF",
            lteband="7FFFFFFFFFFFFFFF",
        )

    @patch("main.Client")
    @patch("main.Connection")
    def test_ensure_4g_mode_does_nothing_when_already_4g(self, mock_conn, mock_client_cls) -> None:
        mock_client = MagicMock()
        mock_client.net.net_mode.return_value = {"NetworkMode": "03"}
        mock_client_cls.return_value = mock_client

        result = main._ensure_4g_mode()
        self.assertTrue(result)
        mock_client.net.set_net_mode.assert_not_called()

    @patch("main._reboot_router")
    @patch("main._ensure_4g_mode")
    def test_recover_router_ensures_4g_then_reboots(self, mock_ensure_4g, mock_reboot) -> None:
        main._recover_router()
        mock_ensure_4g.assert_called_once()
        mock_reboot.assert_called_once()


if __name__ == "__main__":
    unittest.main()
