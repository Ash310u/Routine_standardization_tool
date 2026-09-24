from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


@dataclass
class OCRResult:
    text: str
    confidence: float
    source: str = "printed"
    alternatives: list[str] | None = None


class OCREngine:
    """Load models once per worker, only when a scan needs them."""

    def __init__(self, handwriting_enabled: bool = False):
        self.handwriting_enabled = handwriting_enabled
        self._printed = None
        self._trocr = None

    def read(self, image: Image.Image) -> OCRResult:
        if self._printed is None:
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise RuntimeError("Scan OCR needs the ocr extra: pip install -e '.[ocr]'") from exc
            self._printed = PaddleOCR(use_doc_orientation_classify=False,
                                      use_doc_unwarping=False, use_textline_orientation=False,
                                      enable_mkldnn=False)
        import numpy as np

        predictions = self._printed.predict(np.asarray(image.convert("RGB")))
        pieces, scores = [], []
        for prediction in predictions:
            data = prediction.json
            data = data.get("res", data)
            pieces.extend(str(x) for x in data.get("rec_texts", []) if x)
            scores.extend(float(x) for x in data.get("rec_scores", []))
        text = "\n".join(pieces)
        confidence = min(scores) if scores else 0.0
        if self.handwriting_enabled and (confidence < 0.7 or not text.strip()):
            handwritten = self._read_handwriting(image)
            if handwritten:
                return OCRResult(handwritten, min(confidence, 0.55), "handwritten", [text] if text else [])
        return OCRResult(text, confidence)

    def _read_handwriting(self, image: Image.Image) -> str:
        if self._trocr is None:
            try:
                from transformers import TrOCRProcessor, VisionEncoderDecoderModel
            except ImportError as exc:
                raise RuntimeError("Handwriting OCR needs the handwriting extra") from exc
            name = "microsoft/trocr-small-handwritten"
            self._trocr = (TrOCRProcessor.from_pretrained(name),
                           VisionEncoderDecoderModel.from_pretrained(name).eval())
        processor, model = self._trocr
        import torch

        with torch.no_grad():
            pixels = processor(image.convert("RGB"), return_tensors="pt").pixel_values
            tokens = model.generate(pixels)
        return processor.batch_decode(tokens, skip_special_tokens=True)[0].strip()
