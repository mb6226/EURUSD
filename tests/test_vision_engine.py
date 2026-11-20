from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from eurusd_ai_monitor.engines.vision_engine import (
    LocalOllamaVisionProvider,
    ScreenshotChangedError,
    VisionRuntime,
    inspect_screenshot,
)


class FakeVisionProvider:
    model = "fake-local-vision"

    def __init__(self):
        self.calls = []
        self.completed = threading.Event()

    def analyze(self, path, *, timeframe, expected_sha256):
        self.calls.append((Path(path), timeframe, expected_sha256))
        self.completed.set()
        return {
            "status": "ANALYZED",
            "provider": "fake-local",
            "model": self.model,
            "timeframe": timeframe,
            "image_sha256": expected_sha256,
            "analysis": {"observed_direction": "DOWN"},
            "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        }


class ScreenshotRaceProvider:
    model = "fake-local-vision"

    def __init__(self):
        self.calls = 0
        self.completed = threading.Event()

    def analyze(self, path, *, timeframe, expected_sha256):
        self.calls += 1
        if self.calls == 1:
            raise ScreenshotChangedError("screenshot rotated before read")
        self.completed.set()
        return {
            "status": "ANALYZED",
            "provider": "fake-local",
            "model": self.model,
            "timeframe": timeframe,
            "image_sha256": expected_sha256,
            "analysis": {"observed_direction": "RANGE"},
            "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        }


class VisionScreenshotEvidenceTests(unittest.TestCase):
    def test_missing_screenshot_is_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            result = inspect_screenshot(Path(directory) / "missing.png")
        self.assertEqual(result["status"], "MISSING")
        self.assertFalse(result["semantic_analysis_available"])
        self.assertEqual(result["vision_analysis"], "NOT_CONNECTED")

    def test_stale_screenshot_is_not_accepted_as_current_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chart.png"
            Image.new("RGB", (32, 24), "white").save(path)
            old = (datetime.now(timezone.utc) - timedelta(seconds=120)).timestamp()
            os.utime(path, (old, old))
            result = inspect_screenshot(path, max_age_seconds=30)
        self.assertEqual(result["status"], "STALE")
        self.assertFalse(result["semantic_analysis_available"])

    def test_ready_image_has_stable_provenance_and_quality_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "EURUSD_M1.png"
            Image.new("RGB", (64, 48), "white").save(path)
            first = inspect_screenshot(path)
            second = inspect_screenshot(path)

        self.assertEqual(first["status"], "IMAGE_READY")
        self.assertEqual(first["width"], 64)
        self.assertEqual(first["height"], 48)
        self.assertEqual(first["format"], "PNG")
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["evidence_id"], second["evidence_id"])
        self.assertIn("grayscale_entropy", first["image_quality"])
        self.assertEqual(first["analysis_status"], "AWAITING_VISION_PROVIDER")
        self.assertFalse(first["semantic_analysis_available"])

    def test_changed_image_content_changes_evidence_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chart.png"
            Image.new("RGB", (32, 24), "white").save(path)
            first = inspect_screenshot(path)
            Image.new("RGB", (32, 24), "black").save(path)
            second = inspect_screenshot(path)
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertNotEqual(first["evidence_id"], second["evidence_id"])

    def test_invalid_image_is_reported_without_claiming_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.png"
            path.write_bytes(b"not-an-image")
            result = inspect_screenshot(path)
        self.assertEqual(result["status"], "INVALID_IMAGE")
        self.assertTrue(result["reason_code"].startswith("SCREENSHOT_DECODE_FAILED:"))
        self.assertFalse(result["semantic_analysis_available"])

    def test_provider_rejects_non_loopback_endpoint(self):
        with self.assertRaisesRegex(ValueError, "local loopback"):
            LocalOllamaVisionProvider(base_url="https://example.com")

    def test_provider_normalizes_unexpected_model_output_types(self):
        normalized = LocalOllamaVisionProvider._normalize_analysis({
            "chart_visible": True,
            "observed_direction": "SIDEWAYS",
            "chart_quality": "EXCELLENT",
            "uncertainty_notes": "some labels are unreadable",
        })
        self.assertEqual(normalized["observed_direction"], "UNCLEAR")
        self.assertEqual(normalized["chart_quality"], "DEGRADED")
        self.assertEqual(normalized["uncertainty_notes"], ["some labels are unreadable"])

    def test_runtime_processes_latest_frame_in_background(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chart.png"
            Image.new("RGB", (32, 24), "white").save(path)
            screenshot = inspect_screenshot(path)
            provider = FakeVisionProvider()
            runtime = VisionRuntime(
                provider,
                analysis_interval_seconds=3600,
                max_result_age_seconds=3600,
            )
            runtime.start()
            runtime.submit("M1", path, screenshot)
            self.assertTrue(provider.completed.wait(2))
            result = runtime.latest("M1")

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["status"], "ANALYZED")
        self.assertTrue(result["is_recent"])
        self.assertEqual(result["analysis"]["observed_direction"], "DOWN")

    def test_runtime_retries_when_screenshot_is_overwritten_before_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chart.png"
            Image.new("RGB", (32, 24), "white").save(path)
            screenshot = inspect_screenshot(path)
            provider = ScreenshotRaceProvider()
            runtime = VisionRuntime(
                provider,
                analysis_interval_seconds=3600,
                max_result_age_seconds=3600,
            )
            runtime.start()
            runtime.submit("M1", path, screenshot)
            deadline = time.monotonic() + 2
            while not provider.completed.is_set() and time.monotonic() < deadline:
                runtime.submit("M1", path, screenshot)
                provider.completed.wait(0.01)
            result = runtime.latest("M1")

        self.assertEqual(provider.calls, 2)
        self.assertEqual(result["status"], "ANALYZED")
        self.assertEqual(result["analysis"]["observed_direction"], "RANGE")


if __name__ == "__main__":
    unittest.main()
