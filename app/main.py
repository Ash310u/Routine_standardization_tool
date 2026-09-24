from __future__ import annotations

import os

from fastapi import FastAPI, File, HTTPException, UploadFile

from app.database.catalog import Catalog
from app.pipeline import Pipeline, UnsupportedFileError
from app.schemas.models import Routine

app = FastAPI(title="Routine Standardizer", version="0.1.0")
pipeline = Pipeline(Catalog.from_file(os.getenv("ROUTINE_SUBJECT_CATALOG"),
                                     os.getenv("ROUTINE_SUBJECT_ALIASES")),
                    handwriting_enabled=os.getenv("ROUTINE_TROCR", "0") == "1",
                    semantic_index=os.getenv("ROUTINE_SEMANTIC_INDEX"))
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/convert", response_model=Routine)
async def convert(file: UploadFile = File(...)) -> Routine:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File exceeds 20 MB limit")
    try:
        return pipeline.process(data)
    except UnsupportedFileError as exc:
        raise HTTPException(415, str(exc)) from exc
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
