from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
from PIL import Image

def inspect_screenshot(path: Path, max_age_seconds: int = 30) -> dict:
    """
    Validates screenshot availability and dimensions.
    This does NOT claim visual market understanding. A vision-model adapter
    will be connected in a later step after the provider/model is selected.
    """
    if not path.exists():
        return {"status": "MISSING", "path": str(path)}
    age = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)
    if age > max_age_seconds:
        return {"status": "STALE", "age_seconds": round(age, 1), "path": str(path)}
    try:
        with Image.open(path) as img:
            return {
                "status": "IMAGE_READY",
                "width": img.width,
                "height": img.height,
                "age_seconds": round(age, 1),
                "path": str(path),
                "vision_analysis": "NOT_CONNECTED",
            }
    except Exception as exc:
        return {"status": "INVALID_IMAGE", "error": str(exc), "path": str(path)}
