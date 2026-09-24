from __future__ import annotations

import io
import zipfile

from app.confidence.scoring import score_class
from app.database.catalog import Catalog
from app.extractors.excel import extract_excel
from app.extractors.image import extract_image
from app.extractors.pdf import extract_pdf
from app.ocr.engine import OCREngine
from app.parsers.grid import parse_grids
from app.schemas.models import Grid, ReviewItem, Routine
from app.standardization.matcher import match_subject
from app.standardization.semantic import SemanticIndex


class UnsupportedFileError(ValueError):
    pass


def detect_file_type(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "[Content_Types].xml" in archive.namelist() and any(
                    name.startswith("xl/workbook") for name in archive.namelist()
                ):
                    return "xlsx"
        except zipfile.BadZipFile:
            pass
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        return "image"
    except Exception:
        raise UnsupportedFileError("Expected XLSX, PDF, or a supported image") from None


class Pipeline:
    def __init__(self, catalog: Catalog | None = None, *, handwriting_enabled: bool = False,
                 semantic_index: str | None = None):
        self.catalog = catalog or Catalog([])
        self.ocr = OCREngine(handwriting_enabled=handwriting_enabled)
        self.semantic = SemanticIndex(self.catalog, semantic_index) if semantic_index else None

    def process(self, data: bytes) -> Routine:
        kind = detect_file_type(data)
        grids: list[Grid] = []
        warnings: list[str] = []
        if kind == "xlsx":
            grids = extract_excel(data)
        elif kind == "pdf":
            grids, scans = extract_pdf(data)
            for page, image_data in scans:
                found = extract_image(image_data, self.ocr, page)
                if not found:
                    warnings.append(f"Scanned page {page}: table grid could not be detected")
                grids.extend(found)
        else:
            grids = extract_image(data, self.ocr)
            if not grids:
                warnings.append("Image table grid could not be detected")
        routine = parse_grids(grids)
        routine.warnings.extend(warnings)
        if not self.catalog.subjects:
            routine.warnings.append("No canonical subject catalog configured; all classes require review")
        cells = {(c.page, c.cell_ref, c.bbox): c for grid in grids for row in grid.rows for c in row}
        for item in routine.classes:
            matched = match_subject(item.subject_raw, item.subject_code, self.catalog,
                                    college=item.college, department=item.department,
                                    year=item.year, semester=item.semester,
                                    course=item.course, semantic=self.semantic)
            raw_cell = cells.get((item.page, item.cell_ref, item.bbox))
            score_class(item, matched, raw_cell.ocr_confidence if raw_cell else None)
            if item.requires_review:
                routine.review_items.append(ReviewItem(
                    reason="; ".join(item.review_reasons), raw_text=raw_cell.text if raw_cell else item.subject_raw,
                    page=item.page, cell_ref=item.cell_ref, bbox=item.bbox))
        return routine
