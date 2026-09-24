"""Convert a directory of routine files to one JSON result per source file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

EXTENSIONS = {".xlsx", ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def run(source: Path, output: Path, catalog_path: Path | None,
        handwriting: bool = False, aliases_path: Path | None = None,
        semantic_index: Path | None = None) -> int:
    from app.database.catalog import Catalog
    from app.pipeline import Pipeline, UnsupportedFileError

    if not source.is_dir():
        raise ValueError(f"Dataset directory does not exist: {source}")
    if output.resolve() == source.resolve() or source.resolve() in output.resolve().parents:
        raise ValueError("Output directory must be outside the dataset directory")
    pipeline = Pipeline(Catalog.from_file(catalog_path, aliases_path),
                        handwriting_enabled=handwriting,
                        semantic_index=str(semantic_index) if semantic_index else None)
    files = sorted(path for path in source.rglob("*")
                   if path.is_file() and path.suffix.lower() in EXTENSIONS)
    if not files:
        print(f"No supported routine files found in {source}")
        return 1
    processed = failed = flagged = 0
    for path in files:
        relative = path.relative_to(source)
        destination = output / relative.with_suffix(relative.suffix + ".json")
        try:
            routine = pipeline.process(path.read_bytes())
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(routine.model_dump_json(indent=2) + "\n", encoding="utf-8")
            processed += 1
            flagged += bool(routine.review_items)
            print(f"OK     {relative} -> {destination} ({len(routine.classes)} classes, {len(routine.review_items)} review items)")
        except (UnsupportedFileError, ValueError, OSError, RuntimeError, ImportError) as exc:
            failed += 1
            print(f"ERROR  {relative}: {exc}")
    print(json.dumps({"total": len(files), "converted": processed,
                      "with_review_items": flagged, "failed": failed}))
    return 0 if failed == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Directory containing routine files")
    parser.add_argument("--output", type=Path, default=Path("output"), help="JSON output directory")
    parser.add_argument("--catalog", type=Path, help="Canonical subject catalog JSON")
    parser.add_argument("--aliases", type=Path, help="Alias overlay keyed by SubjectMasterId")
    parser.add_argument("--semantic-index", type=Path, help="Built local FAISS index directory")
    parser.add_argument("--handwriting", action="store_true", help="Enable TrOCR fallback for uncertain OCR cells")
    args = parser.parse_args()
    try:
        code = run(args.source, args.output, args.catalog, args.handwriting,
                   args.aliases, args.semantic_index)
    except (ValueError, OSError, ImportError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    parser.exit(code)


if __name__ == "__main__":
    main()
