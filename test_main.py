"""Focused tests for rotate endpoint activity logging."""

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException


os.environ.setdefault("ROUTER_PASSWORD", "test-password")

import main


class RotateLogTests(unittest.TestCase):
    """Verify that rotate calls are captured for the dashboard log."""

    def setUp(self) -> None:
        """Reset in-memory state before each test."""

        with main.ROTATE_LOG_LOCK:
            main.ROTATE_LOG.clear()

        with main.ROTATE_STATUS_LOCK:
            main.ROTATE_STATUS = main.RotateStatus()

    @patch("main._start_rotate_sequence")
    def test_rotate_records_event_when_started(self, start_rotate_sequence) -> None:
        """Rotate calls should be stored when the workflow starts successfully."""

        response = main.rotate()

        self.assertEqual(response, {"status": "rotating"})
        start_rotate_sequence.assert_called_once_with()

        log_response = main.rotate_log()

        self.assertEqual(len(log_response["events"]), 1)
        self.assertIn("timestamp", log_response["events"][0])

    @patch(
        "main._start_rotate_sequence",
        side_effect=HTTPException(status_code=409, detail={"status": "rotating"}),
    )
    def test_rotate_records_event_even_when_start_is_rejected(self, start_rotate_sequence) -> None:
        """Rotate calls should be stored even when a second start attempt is rejected."""

        with self.assertRaises(HTTPException) as raised_exception:
            main.rotate()

        self.assertEqual(raised_exception.exception.status_code, 409)
        start_rotate_sequence.assert_called_once_with()

        log_response = main.rotate_log()

        self.assertEqual(len(log_response["events"]), 1)


if __name__ == "__main__":
    unittest.main()