from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
IMAGE_DIR = ROOT / "Modules" / "Elliott_Waves" / "Dataset" / "external_references" / "chart_images"
IMAGE_INDEX = ROOT / "Modules" / "Elliott_Waves" / "Dataset" / "external_references" / "chart_image_extractions.jsonl"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
PRICE_RE = re.compile(r"(?<!\d)1\.\d{3,5}(?!\d)")
WAVE_RE = re.compile(r"^(?:[1-5]|[ivxIVX]{1,4}|[abcABC]|[wxyzWXYZ]|[①②③④⑤])$")
WAVE_PREFIX_RE = re.compile(r"^(?:wave\s*)?([1-5ivxabcwxyz]+)$", re.I)

_OCR_ENGINE = None


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def _host_allowed(url: str, allowed_domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return urlparse(url).scheme in ("http", "https") and any(
        host == domain.lower() or host.endswith("." + domain.lower())
        for domain in allowed_domains if domain
    )


def _existing_records() -> dict[str, dict]:
    records = {}
    if IMAGE_INDEX.exists():
        for line in IMAGE_INDEX.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                records[item.get("image_id")] = item
            except json.JSONDecodeError:
                pass
    return records


def _wave_token(text: str) -> str | None:
    token = re.sub(r"^wave\s*", "", text.strip(), flags=re.I).strip().strip("()[]{}.,:;").strip()
    match = WAVE_PREFIX_RE.fullmatch(token)
    if match:
        token = match.group(1)
    return token if WAVE_RE.fullmatch(token) else None


def _axis_calibration(detections: list[dict]) -> dict:
    # EURUSD price-axis labels are normally at the far-right edge of a chart.
    ticks = []
    for d in detections:
        x, y = d["center_normalized"]
        match = PRICE_RE.search(d["text"])
        if match and x >= 0.86:
            try:
                ticks.append((y, float(match.group(0))))
            except ValueError:
                pass
    unique = {(round(y, 4), price) for y, price in ticks}
    if len(unique) < 2:
        return {"status": "not_calibrated", "price_axis_ticks": []}
    points = list(unique)
    mean_y = sum(p[0] for p in points) / len(points)
    mean_price = sum(p[1] for p in points) / len(points)
    variance = sum((p[0] - mean_y) ** 2 for p in points)
    if variance <= 1e-10:
        return {"status": "not_calibrated", "price_axis_ticks": []}
    slope = sum((y - mean_y) * (price - mean_price) for y, price in points) / variance
    intercept = mean_price - slope * mean_y
    return {
        "status": "approximate_linear",
        "price_axis_ticks": [{"y_normalized": y, "price": price} for y, price in sorted(points)],
        "price_from_y": {"intercept": intercept, "slope": slope},
        "note": "Approximate linear y-to-price fit from right-axis OCR labels; verify against the chart."
    }


def extract_chart_image(image_url: str, record: dict, allowed_domains: list[str],
                        user_agent: str, timeout: int = 20) -> dict | None:
    """Download one public configured-domain image and OCR text/labels with positions."""
    if not _host_allowed(image_url, allowed_domains):
        return None
    image_id = hashlib.sha256((record["record_id"] + "|" + image_url).encode()).hexdigest()[:20]
    previous = _existing_records().get(image_id)
    if previous and previous.get("ocr_status") == "completed" and previous.get("extractor_version") == 3:
        return None

    try:
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        existing_path = ROOT / previous["local_image_path"] if previous and previous.get("local_image_path") else None
        if existing_path and existing_path.exists():
            image_path = existing_path
            from PIL import Image
            image = Image.open(image_path).convert("RGB")
            width, height = image.size
        else:
            req = Request(image_url, headers={"User-Agent": user_agent, "Accept": "image/*"})
            with urlopen(req, timeout=timeout) as response:
                mime = response.headers.get("Content-Type", "").split(";")[0].lower()
                if not mime.startswith("image/"):
                    return None
                data = response.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES or len(data) < 2048:
                return None
            from PIL import Image
            import io
            image = Image.open(io.BytesIO(data)).convert("RGB")
            width, height = image.size
            if width < 480 or height < 240:
                return None
            suffix = ".jpg" if mime in ("image/jpeg", "image/jpg") else ".png" if mime == "image/png" else ".webp" if mime == "image/webp" else ".img"
            image_path = IMAGE_DIR / f"{image_id}{suffix}"
            image_path.write_bytes(data)

        detections = []
        ocr_status = "not_available"
        try:
            import numpy as np
            engine = _get_ocr_engine()
            result, _ = engine(np.array(image))
            ocr_status = "completed"
            for detected in result or []:
                polygon, raw_text, score = detected
                xs = [float(point[0]) for point in polygon]
                ys = [float(point[1]) for point in polygon]
                cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
                clean = " ".join(str(raw_text).split())
                if not clean:
                    continue
                wave = _wave_token(clean)
                detections.append({
                    "text": clean,
                    "confidence": round(float(score), 4),
                    "bbox_pixels": [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)],
                    "center_normalized": [round(cx / width, 5), round(cy / height, 5)],
                    "wave_label_candidate": wave,
                    "possible_wave_label": wave is not None,
                    "possible_eurusd_price": bool(PRICE_RE.search(clean))
                })
        except ImportError:
            ocr_status = "dependency_missing"
        except Exception as exc:
            ocr_status = f"error:{type(exc).__name__}"

        labels = [d for d in detections if d["possible_wave_label"]]
        prices = [d for d in detections if d["possible_eurusd_price"]]
        calibration = _axis_calibration(detections)
        ocr_text = " ".join(d["text"] for d in detections)
        timeframes = sorted(set(re.findall(r"\b(?:M[1-9]|M1[0-5]|H[1-4]|D1|W1|1D|1W|4H|1H)\b", ocr_text, re.I)))
        pair_detected = bool(re.search(r"\bEUR\s?[/\-]?\s?USD\b|\bEURUSD\b", ocr_text, re.I))
        date_axis_tokens = [d for d in detections if d["center_normalized"][1] >= 0.90 and (re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", d["text"], re.I) or re.fullmatch(r"\d{1,2}", d["text"]))]
        timestamp_match = re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}(?:\s+\d{1,2}:\d{2})?", ocr_text, re.I)
        chart_candidate = pair_detected and bool(timeframes or len(labels) >= 2 or len(prices) >= 4)
        image_classification = "eurusd_chart_candidate" if chart_candidate else "non_chart_or_unrecognized"
        price_fit = calibration.get("price_from_y")
        if price_fit:
            for label in labels:
                y = label["center_normalized"][1]
                label["estimated_price_from_axis"] = round(price_fit["intercept"] + price_fit["slope"] * y, 5)

        item = {
            "schema_version": 1, "image_id": image_id, "record_id": record["record_id"],
            "source_id": record["source_id"], "article_url": record["url"], "image_url": image_url,
            "image_alt_text": record.get("chart_image_alt_text"), "chart_pair_detected": pair_detected,
            "timeframes_detected": timeframes,
            "chart_timestamp_mentioned": timestamp_match.group(0) if timestamp_match else None,
            "date_axis_tokens": [{"text": d["text"], "x_normalized": d["center_normalized"][0], "confidence": d["confidence"]} for d in date_axis_tokens],
            "extractor_version": 3, "chart_candidate": chart_candidate,
            "image_classification": image_classification,
            "local_image_path": str(image_path.relative_to(ROOT)), "image_width": width, "image_height": height,
            "collected_at": datetime.now(timezone.utc).isoformat(), "ocr_status": ocr_status,
            "ocr_detections": detections, "possible_wave_labels": labels, "possible_price_labels": prices,
            "price_axis_calibration": calibration,
            "coordinate_note": "Positions are normalized image coordinates (x,y), origin at top-left. Estimated prices are approximate and require visual verification; x is not mapped to time yet.",
            "review_status": "needs_visual_review", "training_eligible": False
        }
        with IMAGE_INDEX.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item
    except Exception:
        return None
