from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image

from app.ocr.engine import OCREngine
from app.schemas.models import Grid, RawCell


def extract_image(data: bytes, engine: OCREngine, page: int = 1) -> list[Grid]:
    import cv2

    image = Image.open(BytesIO(data)).convert("RGB")
    rgb = np.asarray(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 31, 12)
    height, width = gray.shape
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, height // 35))))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, width // 35), 1)))
    xs = _line_positions(vertical, axis=0, minimum=max(20, height // 8))
    ys = _line_positions(horizontal, axis=1, minimum=max(20, width // 8))
    if len(xs) < 3 or len(ys) < 3:
        return []
    # OCR cell interiors individually; border strokes are excluded.
    rows = []
    for r, (top, bottom) in enumerate(zip(ys, ys[1:]), 1):
        if bottom - top < 12:
            continue
        cells = []
        for c, (left, right) in enumerate(zip(xs, xs[1:]), 1):
            if right - left < 12:
                continue
            crop = image.crop((left + 2, top + 2, right - 2, bottom - 2))
            result = engine.read(crop)
            cells.append(RawCell(text=result.text, row=r, column=c, page=page,
                                 bbox=(left, top, right, bottom), source=result.source,
                                 ocr_confidence=result.confidence,
                                 alternatives=result.alternatives or []))
        rows.append(cells)
    return [Grid(rows=rows, page=page)]


def _line_positions(mask: np.ndarray, axis: int, minimum: int) -> list[int]:
    counts = np.count_nonzero(mask, axis=axis)
    indices = np.flatnonzero(counts >= minimum)
    groups = []
    for value in indices:
        if not groups or value > groups[-1][-1] + 1:
            groups.append([int(value)])
        else:
            groups[-1].append(int(value))
    return [int(np.median(group)) for group in groups]
