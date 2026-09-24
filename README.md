# Routine Standardizer

Routine Standardizer is an early Python implementation of the pipeline in [implementation.md](implementation.md). It converts XLSX, PDF, and image timetables to the [routine JSON schema](app/schemas/routine.schema.json). Each class keeps its raw extracted text, any canonical subject match, a confidence score, and review reasons.

The catalog and embedding design is documented in [semantic_matching_plan.md](semantic_matching_plan.md).

**Current outputs require checking against the source routine.** The supplied TINT workbook has been spot checked, but the full timetable and automatic match thresholds have not been validated against labeled ground truth.

## Install

Use Python 3.13 on this machine. The default `python` is 3.14, which cannot install the current PaddlePaddle dependency.

```bash
cd /home/ass/src/routine_reader
python3.13 -m venv .venv313
.venv313/bin/python -m pip install -e .
```

The base install is enough for native XLSX and PDF files. Install `.[semantic]` for local Sentence Transformers and FAISS matching, `.[ocr]` for scanned PDFs and photos, or `.[ocr,handwriting]` for the optional TrOCR fallback.

## Run the supplied Excel workbook

The batch command accepts a directory and writes one JSON file for each supported input. `Routines/TINT` contains the workbook you named, so this command processes only that workbook:

```bash
cd /home/ass/src/routine_reader
.venv313/bin/python -m app.batch Routines/TINT --output output/TINT
```

The result is `output/TINT/Odd sem 2026-27.xlsx.json`. To process the whole dataset instead, run `.venv313/bin/python -m app.batch Routines --output output`. The batch command prints the number of classes and review items for each file and continues after per-file errors.

### Match TINT subjects with the saved catalog

The saved [TINT subject response](samples/subjects.tint.json) is loaded locally. The optional [alias overlay](samples/subjects.tint.aliases.json) adds confirmed abbreviations without changing that snapshot. Build the index once, then reuse it for conversions:

```bash
.venv313/bin/python -m pip install -e '.[semantic]'
.venv313/bin/python -m app.standardization.semantic build \
  --catalog samples/subjects.tint.json \
  --aliases samples/subjects.tint.aliases.json \
  --output artifacts/subject_index
.venv313/bin/python -m app.batch Routines/TINT \
  --output output/TINT_semantic \
  --catalog samples/subjects.tint.json \
  --aliases samples/subjects.tint.aliases.json \
  --semantic-index artifacts/subject_index
```

The result is `output/TINT_semantic/Odd sem 2026-27.xlsx.json`. Index building downloads a pretrained embedding model on first use and saves a local copy with the FAISS index. Conversions use the saved model and index without contacting the subject API or model hub. Rebuild the index when the catalog, aliases, or embedding model changes.

The JSON stores one `subject_code` field. The parser initially puts the extracted code there. When its letters and digits match a saved catalog code in order, the pipeline replaces that value with the catalog's code spelling; separator differences alone do not create a review flag. `subject_raw` retains the cell's original subject text. When an extracted code is absent from the catalog, `subject_code` retains that extracted value while `subject_name` and `subject_master_id` stay empty. The pipeline checks a separate readable name against the global saved catalog: exact name or alias, or a catalog name contained in longer cell text, then cosine search in the local embedding index. The JSON `name_lookup_status` distinguishes `name_unavailable`, `index_unavailable`, `exact_name_found`, `similar_name_found`, and `no_strong_candidate`; `cosine_similarity` and `match_candidates` show search evidence where available. The 0.68 similarity cutoff is provisional. A low score means no *strong* candidate was found in this index; it cannot prove the subject is absent. These cases remain flagged for review.

On the supplied workbook, this command currently produces 934 class records across four worksheets. It flags 713 records for review and leaves 221 without review flags. These figures measure the pipeline's own decisions, not verified accuracy. For example, `2nd year!B4` maps `PCC-CS301` to catalog subject 927 (`Data Structure & Algorithms`), while `2nd year!C153` maps `PCCDS 301` to `Introduction to Data Science` but flags the different department label for review.

Code comparison keeps only letters and digits in order, ignoring case, spaces, hyphens, underscores, and other separators. For example, `ESCS 201`, `ESCS-201`, `ESCS_201`, and `ESCS201` all become the catalog value `ESCS201` in the single code field. If several catalog records have that code and the same name, the viewer shows **Shared code · record unresolved**: the canonical name and code are available, but the record ID stays empty until its stream is known. Records with the same code but different names or types remain **Duplicate catalog code** for review. In the supplied workbook, `2nd year!J153` is the shared-code case.

The workbook contains repeated timetable blocks across four worksheets. The parser keeps department, year, semester, and section on each class; root metadata is empty when it differs across blocks. It merges repeated Excel cells across periods and flags corrected AM/PM headers. Cells with multiple subject codes remain reviewable. **Check output against the workbook before using it operationally.** Automatic matching thresholds have not been calibrated on labeled examples.

### Run the NSEC PDF dataset

The saved [NSEC subject response](samples/subjects.nsec.json) was fetched once from the supplied `college_id=1` endpoint. Its empty [alias overlay](samples/subjects.nsec.aliases.json) is separate from TINT's confirmed aliases. The two snapshots currently have the same 1,704 code/name/course/stream/semester/type records; other API fields differ. Build and use a separate index so each snapshot's hash is checked independently:

```bash
HF_HUB_OFFLINE=1 .venv313/bin/python -m app.standardization.semantic build \
  --catalog samples/subjects.nsec.json \
  --aliases samples/subjects.nsec.aliases.json \
  --output artifacts/subject_index_nsec \
  --model artifacts/subject_index/embedding_model
HF_HUB_OFFLINE=1 .venv313/bin/python -m app.batch Routines/NSEC \
  --output output/NSEC_catalog \
  --catalog samples/subjects.nsec.json \
  --aliases samples/subjects.nsec.aliases.json \
  --semantic-index artifacts/subject_index_nsec
```

`Routines/NSEC` contains 25 PDFs. The batch writes one `.pdf.json` file for each PDF under the same department folders in `output/NSEC_catalog`. The recorded run converted all 25 files, with 3,271 class records, 3,238 review items, and 72 classes without review flags. [The per-file summary](output/NSEC_catalog/summary.json) lists seven PDFs with zero parsed classes. Scanned pages use PaddleOCR and may run slowly on CPU. A JSON file with zero classes and review items means the page layout was not parsed successfully; inspect those results before use. Many digital NSEC PDFs also lack extracted subject codes or context, so their semantic suggestions remain reviewable.

To use the NSEC snapshot through the API, set `ROUTINE_SUBJECT_CATALOG=$PWD/samples/subjects.nsec.json`, `ROUTINE_SUBJECT_ALIASES=$PWD/samples/subjects.nsec.aliases.json`, and `ROUTINE_SEMANTIC_INDEX=$PWD/artifacts/subject_index_nsec` before starting Uvicorn.

## HTTP API

Start the FastAPI server:

```bash
cd /home/ass/src/routine_reader
.venv313/bin/uvicorn app.main:app --reload
```

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Returns `{"status":"ok"}`. |
| `POST /convert` | Accepts one multipart upload in the `file` field and returns a `Routine` JSON object. |
| `GET /docs` | FastAPI's interactive endpoint documentation. |

Send the named workbook to the API:

```bash
curl --fail-with-body -X POST http://127.0.0.1:8000/convert \
  -F 'file=@Routines/TINT/Odd sem 2026-27.xlsx' \
  -o tint-routine.json
```

The upload limit is 20 MB. Unsupported formats return HTTP 415; oversized files return HTTP 413; files that cannot be processed return HTTP 422. `/convert` returns JSON with routine metadata, `classes`, `review_items`, and `warnings`. The response model is defined in [app/schemas/models.py](app/schemas/models.py).

To use the TINT catalog and built index through the API, set these environment variables before starting Uvicorn:

```bash
export ROUTINE_SUBJECT_CATALOG="$PWD/samples/subjects.tint.json"
export ROUTINE_SUBJECT_ALIASES="$PWD/samples/subjects.tint.aliases.json"
export ROUTINE_SEMANTIC_INDEX="$PWD/artifacts/subject_index"
.venv313/bin/uvicorn app.main:app --reload
```

## Review case viewer

The separate React viewer in [viewer/](viewer/) opens with fictional examples of every current review cause, including the historical fuzzy-code case. It distinguishes an absent code with no readable name, an absent code with a name candidate, and an absent code with no strong name candidate. An unknown code that remains unmatched is a safe expected result, even though it still requires human review. It color-codes causes and supports search, cause, name lookup, status, and department filters. The cause cards and cause dropdown select the same filter; the name lookup dropdown narrows absent-code records to exact text, similar name, no strong candidate, unavailable name, or an unrun lookup. Click a case to see its raw text, extracted code, catalog result, review reasons, and candidate subjects. Older JSON exports without `name_lookup_status` appear as “name not checked”; rerun conversion to see the new diagnostics. It has no login or database.

```bash
cd /home/ass/src/routine_reader/viewer
npm install --include=dev
npm run dev
```

Open `http://127.0.0.1:5173/`. Use **Load routine JSON** to inspect a real output file such as `output/TINT_semantic/Odd sem 2026-27.xlsx.json`. The file stays in your browser; the viewer does not upload it to a server. **Reset demo** returns to the fictional scenarios. `npm run build` creates a static production build in `viewer/dist/`.

## Canonical subject catalog

Subject standardization needs your real subject data. The loader accepts the saved TINT API response (`ok` and `data`) or the original simple JSON list with `name`, `code`, and `aliases`. Without a catalog, every extracted class remains reviewable. The fictitious [example catalog](samples/subjects.example.json) only illustrates the simpler format.

- Batch: add `--catalog /path/to/subjects.json` and optionally `--aliases` and `--semantic-index`.
- API: set `ROUTINE_SUBJECT_CATALOG`, and optionally `ROUTINE_SUBJECT_ALIASES` and `ROUTINE_SEMANTIC_INDEX`.

Matching checks normalized subject codes against the whole catalog first. When a code is repeated, course, stream, and semester narrow it to a single catalog record. If duplicate records have the same name and type, the name/code/type are returned without choosing a record ID; the cell stays reviewable. A unique code found outside the parsed context supplies its catalog name, code, type, and catalog course/stream/semester, with a context review flag. An unknown extracted code stays unmatched instead of being replaced by a name guess. Without a code, matching uses aliases, RapidFuzz, then normalized Sentence Transformers embeddings searched with FAISS `IndexFlatIP`. Cosine similarity and the nearest alternatives are included in the JSON. Semantic suggestions remain flagged for review until thresholds are calibrated.

## OCR and model loading

XLSX files use `openpyxl` and do not invoke OCR. PDFs with a text layer use PyMuPDF first. Scanned pages and images use OpenCV for a basic table grid, then PaddleOCR on detected cell crops. For the API, set `ROUTINE_TROCR=1` to enable the TrOCR fallback; for batch, add `--handwriting`. TrOCR is attempted only when PaddleOCR returns no text or confidence below `0.7`. Its transcription remains reviewable.

The `models/` directory is empty because no custom model was trained. PaddleOCR and TrOCR use pretrained weights cached outside the project. The generated FAISS indexes and a local copy of the embedding model live under `artifacts/subject_index/` after the build command.

## Tests

```bash
.venv313/bin/python -m pip install -e '.[test]'
.venv313/bin/pytest
```
