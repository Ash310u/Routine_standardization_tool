# Semantic subject matching plan

## Current code-first rule

The implemented matcher follows the later requirement to make an extracted subject code authoritative: it looks up normalized codes in the full saved catalog before name matching. Context resolves duplicate codes; a unique code outside the parsed context supplies the catalog name and metadata with a review flag. An unknown extracted code remains unmatched. The earlier context-first sequence below records the original design, but this code-first rule takes precedence.

## Goal and boundary

After a timetable cell is read, match its raw subject text to one canonical subject from the saved TINT catalog and return its name, code, and matching evidence in the existing `/convert` JSON response. The input remains Excel, PDF, or image; printed OCR and TrOCR remain responsible only for transcription. This phase needs no PostgreSQL, remote vector database, Vision LLM, or additional calls to the TINT API.

Source data: `samples/subjects.tint.json`, a saved response with `ok: true` and 1,704 records in `data`. It is the source of truth for canonical subjects until explicitly refreshed. The implementation must not fetch the API during indexing or conversion.

## Catalog fields

| API field | Use |
| --- | --- |
| `SubjectMasterId` | Stable subject identity and link from each vector to its catalog record. |
| `Name` | Canonical display name and primary embedding text. |
| `Code` | Direct normalized code match; retain the original code in output. |
| `Course`, `Stream`, `Semester` | Candidate scope before fuzzy or vector matching. |
| `SubjectType` | Evidence when distinguishing lab, theory, and elective subjects; do not exclude a candidate unless the extracted type is reliable. |
| Other fields | Retain in the raw snapshot; they are not needed for matching now. |

The snapshot has unique `SubjectMasterId` values. Many codes repeat globally and three codes repeat even within the same `(Course, Stream, Semester)` scope. A code alone must therefore never imply a unique subject when multiple scoped records remain.

## Implementation sequence

### 1. Adapt and validate the local catalog

- Add a loader for the API's `{ "ok": true, "data": [...] }` shape. Map records into a typed canonical subject model with `SubjectMasterId`, name, code, course, stream, semester, and subject type. Keep the existing simple catalog format usable if practical.
- Normalize comparison keys for codes and context (spacing, case, punctuation, and ordinal semester forms) while preserving original display values.
- Validate required fields and IDs. Report duplicate scoped codes and duplicate normalized names as catalog diagnostics; do not silently discard records.
- Add a separate local alias overlay keyed by `SubjectMasterId` for abbreviations and confirmed corrections. Preserve the downloaded API snapshot unchanged.

### 2. Make routine context trustworthy

- Pass course, stream, and semester from the relevant page or worksheet to each parsed class. The current single document-level metadata block is insufficient for multi-sheet workbooks such as the TINT XLSX.
- Preserve extracted subject codes separately from names and faculty initials. Fix cell parsing that currently strips some codes into unrelated text.
- When context is missing or conflicting, keep candidates broad but require review; never auto-accept a match based on an assumed semester.

### 3. Build local embeddings and FAISS indexes

- Choose and pin a small English Sentence Transformers model after checking it on real routine labels. Load it once per worker; no model training is required.
- Embed each canonical `Name` and each confirmed alias separately. Store an ordered vector-to-`SubjectMasterId` map. Do not rely on embeddings for exact subject codes.
- L2-normalize all catalog vectors and query vectors. Use FAISS `IndexFlatIP`, whose inner-product score is cosine similarity for normalized vectors.
- Build one exact index per `(Course, Stream, Semester)` scope so context filtering happens before vector ranking. Keep a reviewed fallback path for incomplete context.
- Save generated indexes, ID maps, and a manifest containing the catalog hash, alias hash, model ID/revision, embedding dimension, and normalization settings. Rebuild if any of these change. Generated artifacts can live under `artifacts/subject_index/`; no database server is needed.

### 4. Add the hybrid matcher

For each extracted class, use this order:

1. Filter candidates by confirmed course, stream, and semester.
2. Try normalized exact code matching. If a code maps to multiple subjects, retain all candidates and mark ambiguity.
3. Try exact canonical name or alias matching.
4. Try RapidFuzz for spelling and OCR variation.
5. Embed the remaining raw subject text and retrieve the top candidates from the scoped FAISS index.

Group alias hits by `SubjectMasterId`, then compare the best and second-best *subjects*, not just the best two alias vectors. Return the matching method, cosine score when used, runner-up score or score gap, and top suggestions. Reject empty or clearly non-subject cells before searching.

### 5. Connect matching to confidence and JSON

- Extend each class result with optional `subject_master_id`, `match_method`, `cosine_similarity`, and candidate suggestions while retaining `subject_raw`, `subject_name`, and `subject_code`.
- Keep cosine similarity separate from overall confidence. Combine match evidence with OCR confidence, code/name conflicts, context completeness, and ambiguity. TrOCR text follows the same matcher and remains reviewable when its transcription is uncertain.
- Auto-accept only after score and runner-up-gap thresholds are calibrated on labeled examples. Expose thresholds as configuration; low scores, close competitors, and duplicate codes go to `requires_review`.

### 6. Integrate without new services

- Build or refresh indexes from the saved JSON using an explicit local command. Conversion requests never call the subject API.
- Load the embedding model and indexes once when the API worker starts or on first semantic match. Reuse them across `/convert` requests and batch files.
- If the semantic extra or index is unavailable, return a clear configuration error or keep the result reviewable through code/alias/fuzzy matching, according to the configured mode. Do not silently claim a cosine match.
- Document installation, index build, catalog update, and API startup in `README.md` once implemented.

## Verification and acceptance criteria

- Use a small labeled set from actual routines, including exact codes, aliases such as `DSA`, OCR errors, elective variants, labs, duplicate codes, and unknown subjects.
- Check top-1 accuracy, top-3 coverage, auto-accept rate, review rate, and especially false automatic acceptance. Calibrate thresholds from these results rather than choosing a permanent number in advance.
- Confirm that a known CSE semester subject maps to the correct `SubjectMasterId`, name, and code; a subject from another semester cannot auto-match; ambiguous scoped codes are reviewed; and an unknown string remains unmatched.
- Confirm that the API returns the same schema for XLSX, PDF, and image inputs and makes no request to the TINT API during conversion.

## Existing project touchpoints

- `app/database/catalog.py`: catalog adapter and scoped candidate lookup.
- `app/standardization/matcher.py`: hybrid match order and evidence.
- New `app/standardization/semantic.py` and local index builder: embeddings, FAISS, manifest, and search.
- `app/parsers/grid.py` and metadata models: per-worksheet/page context.
- `app/confidence/scoring.py` and `app/schemas/models.py`: match evidence, confidence, and review output.
- `app/pipeline.py` and `app/main.py`: one-time model/index loading and reuse.
- `pyproject.toml`: the `semantic` extra is already declared but currently has no implementation behind it.
