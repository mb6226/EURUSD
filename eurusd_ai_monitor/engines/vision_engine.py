from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Event, Lock, Thread
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageStat


def inspect_screenshot(path: Path, max_age_seconds: int = 30) -> dict:
    """
Validate and fingerprint an MT5 screenshot for asynchronous local AI analysis.

    This stage records image provenance and quality only; semantic inference is
    performed by LocalOllamaVisionProvider in the background.
    """
    path = Path(path)
    if not path.exists():
        return {
            "status": "MISSING",
            "path": str(path),
            "semantic_analysis_available": False,
            "vision_analysis": "NOT_CONNECTED",
        }

    try:
        before = path.stat()
    except OSError as exc:
        return {
            "status": "UNAVAILABLE",
            "path": str(path),
            "reason_code": f"SCREENSHOT_STAT_FAILED:{type(exc).__name__}",
            "semantic_analysis_available": False,
            "vision_analysis": "NOT_CONNECTED",
        }

    age = max(0.0, datetime.now(timezone.utc).timestamp() - before.st_mtime)
    base = {
        "path": str(path),
        "age_seconds": round(age, 1),
        "file_size_bytes": before.st_size,
        "captured_at_utc": datetime.fromtimestamp(
            before.st_mtime, tz=timezone.utc
        ).isoformat(),
        "semantic_analysis_available": False,
        "vision_analysis": "NOT_CONNECTED",
        "provider": None,
    }
    if age > max_age_seconds:
        return {**base, "status": "STALE"}

    try:
        content = path.read_bytes()
        after = path.stat()
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or len(content) != after.st_size
        ):
            return {**base, "status": "IMAGE_UNSTABLE"}

        with Image.open(BytesIO(content)) as image:
            image.load()
            grayscale = image.convert("L")
            stats = ImageStat.Stat(grayscale)
            width, height = image.size
            image_format = image.format
            image_mode = image.mode
            entropy = round(grayscale.entropy(), 4)
            mean_luminance = round(stats.mean[0], 4)
            luminance_stddev = round(stats.stddev[0], 4)

        digest = sha256(content).hexdigest()
        return {
            **base,
            "status": "IMAGE_READY",
            "width": width,
            "height": height,
            "format": image_format,
            "mode": image_mode,
            "sha256": digest,
            "evidence_id": f"mt5-screenshot:{path.stem}:{digest[:16]}",
            "image_quality": {
                "grayscale_entropy": entropy,
                "mean_luminance": mean_luminance,
                "luminance_stddev": luminance_stddev,
            },
            "analysis_status": "AWAITING_VISION_PROVIDER",
        }
    except Exception as exc:
        return {
            **base,
            "status": "INVALID_IMAGE",
            "reason_code": f"SCREENSHOT_DECODE_FAILED:{type(exc).__name__}",
        }


class ScreenshotChangedError(RuntimeError):
    """Raised when MT5 overwrites a screenshot before it can be snapshotted."""


class LocalOllamaVisionProvider:
    """Local-only Qwen vision adapter; images never leave the host machine."""

    _PROMPT = (
        "You are a visual evidence extractor for an EURUSD market research system. "
        "Inspect only what is visibly present in this chart screenshot. "
        "Do not infer or invent exact prices, support/resistance levels, or hidden labels. "
        "Do not provide trade advice, entries, stops, targets, or predictions. "
        "Return compact JSON with keys: chart_visible (boolean), "
        "visible_instrument (string or null), visible_timeframe (string or null), "
        "observed_structure (short string), observed_direction "
        "(UP/DOWN/RANGE/UNCLEAR), chart_quality (GOOD/DEGRADED/POOR), "
        "uncertainty_notes (array of strings). If a field is unreadable, use null "
        "or UNCLEAR and explain the uncertainty."
    )

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5vl:7b",
        timeout_seconds: int = 120,
        max_image_width: int = 960,
        max_image_height: int = 540,
        jpeg_quality: int = 82,
        max_output_tokens: int = 180,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {
            "127.0.0.1", "localhost", "::1"
        }:
            raise ValueError("Vision endpoint must be a local loopback HTTP address")
        if not model.strip():
            raise ValueError("Vision model must be non-empty")
        if timeout_seconds < 1 or max_image_width < 64 or max_image_height < 64:
            raise ValueError("Invalid local vision resource limits")
        if not 40 <= jpeg_quality <= 95 or max_output_tokens < 32:
            raise ValueError("Invalid local vision output limits")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_image_size = (max_image_width, max_image_height)
        self.jpeg_quality = jpeg_quality
        self.max_output_tokens = max_output_tokens

    @staticmethod
    def _normalize_analysis(value: object) -> dict:
        if not isinstance(value, dict):
            raise ValueError("Vision response must be a JSON object")
        direction = str(value.get("observed_direction", "UNCLEAR")).upper()
        if direction not in {"UP", "DOWN", "RANGE", "UNCLEAR"}:
            direction = "UNCLEAR"
        quality = str(value.get("chart_quality", "DEGRADED")).upper()
        if quality not in {"GOOD", "DEGRADED", "POOR"}:
            quality = "DEGRADED"
        notes = value.get("uncertainty_notes", [])
        if isinstance(notes, str):
            notes = [notes]
        if not isinstance(notes, list):
            notes = ["Model returned uncertainty notes in an unsupported format"]
        return {
            "chart_visible": bool(value.get("chart_visible", False)),
            "visible_instrument": (
                str(value["visible_instrument"])[:32]
                if value.get("visible_instrument") is not None else None
            ),
            "visible_timeframe": (
                str(value["visible_timeframe"])[:16]
                if value.get("visible_timeframe") is not None else None
            ),
            "observed_structure": str(value.get("observed_structure", "UNCLEAR"))[:400],
            "observed_direction": direction,
            "chart_quality": quality,
            "uncertainty_notes": [str(note)[:240] for note in notes[:8]],
        }

    def analyze(
        self,
        path: Path,
        *,
        timeframe: str,
        expected_sha256: str,
    ) -> dict:
        started = time.monotonic()
        path = Path(path)
        content = path.read_bytes()
        digest = sha256(content).hexdigest()
        if digest != expected_sha256:
            raise ScreenshotChangedError("Screenshot changed before local vision analysis began")

        with Image.open(BytesIO(content)) as source:
            image = source.convert("RGB")
            image.thumbnail(self.max_image_size, Image.Resampling.LANCZOS)
            input_size = image.size
            buffer = BytesIO()
            image.save(
                buffer, format="JPEG", quality=self.jpeg_quality, optimize=True
            )
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

        payload = {
            "model": self.model,
            "prompt": f"{self._PROMPT} The chart timeframe requested by the data feed is {timeframe}.",
            "images": [encoded],
            "stream": False,
            "format": "json",
            "keep_alive": "5m",
            "options": {
                "temperature": 0,
                "num_predict": self.max_output_tokens,
            },
        }
        request = Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"Local Ollama request failed: {type(exc).__name__}") from exc

        raw_response = result.get("response")
        if not isinstance(raw_response, str):
            raise ValueError("Local Ollama response did not contain text")
        analysis = self._normalize_analysis(json.loads(raw_response))
        completed_at = datetime.now(timezone.utc)
        return {
            "status": "ANALYZED",
            "provider": "ollama-local",
            "model": self.model,
            "timeframe": timeframe,
            "image_sha256": digest,
            "input_image_width": input_size[0],
            "input_image_height": input_size[1],
            "input_image_bytes": len(buffer.getvalue()),
            "analysis": analysis,
            "evaluated_at_utc": completed_at.isoformat(),
            "latency_seconds": round(time.monotonic() - started, 1),
            "eval_count": result.get("eval_count"),
        }


class VisionRuntime:
    """Latest-frame-wins background runner; it never blocks market polling."""

    def __init__(
        self,
        provider: LocalOllamaVisionProvider,
        *,
        analysis_interval_seconds: int = 120,
        max_result_age_seconds: int = 240,
    ) -> None:
        if analysis_interval_seconds < 1 or max_result_age_seconds < 1:
            raise ValueError("Vision timing limits must be positive")
        self.provider = provider
        self.analysis_interval_seconds = analysis_interval_seconds
        self.max_result_age_seconds = max_result_age_seconds
        self._pending: dict[str, dict] = {}
        self._latest: dict[str, dict] = {}
        self._last_attempt: dict[str, float] = {}
        self._lock = Lock()
        self._wake = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = Thread(
                target=self._run,
                name="local-vision-worker",
                daemon=True,
            )
            self._thread.start()

    def submit(self, timeframe: str, path: Path, screenshot: dict) -> None:
        if screenshot.get("status") != "IMAGE_READY" or not screenshot.get("sha256"):
            return
        now = time.monotonic()
        with self._lock:
            last_attempt = self._last_attempt.get(timeframe)
            if (
                last_attempt is not None
                and now - last_attempt < self.analysis_interval_seconds
            ):
                return
            self._pending[timeframe] = {
                "path": Path(path),
                "sha256": screenshot["sha256"],
                "timeframe": timeframe,
            }
            self._wake.set()

    def latest(self, timeframe: str) -> dict | None:
        with self._lock:
            result = self._latest.get(timeframe)
            if result is None:
                return None
            result = dict(result)
        try:
            evaluated_at = datetime.fromisoformat(
                result["evaluated_at_utc"].replace("Z", "+00:00")
            )
            age = max(
                0.0,
                (datetime.now(timezone.utc) - evaluated_at).total_seconds(),
            )
        except (KeyError, TypeError, ValueError):
            age = float("inf")
        result["result_age_seconds"] = round(age, 1)
        result["is_recent"] = age <= self.max_result_age_seconds
        return result

    def _run(self) -> None:
        while True:
            self._wake.wait()
            while True:
                with self._lock:
                    if not self._pending:
                        self._wake.clear()
                        break
                    timeframe = next(iter(self._pending))
                    job = self._pending.pop(timeframe)
                    self._last_attempt[timeframe] = time.monotonic()
                try:
                    result = self.provider.analyze(
                        job["path"],
                        timeframe=job["timeframe"],
                        expected_sha256=job["sha256"],
                    )
                except ScreenshotChangedError:
                    with self._lock:
                        self._last_attempt.pop(timeframe, None)
                    continue
                except Exception as exc:
                    result = {
                        "status": "ERROR",
                        "provider": "ollama-local",
                        "model": getattr(self.provider, "model", None),
                        "timeframe": timeframe,
                        "image_sha256": job["sha256"],
                        "reason_code": f"LOCAL_VISION_ERROR:{type(exc).__name__}",
                        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                with self._lock:
                    self._latest[timeframe] = result
