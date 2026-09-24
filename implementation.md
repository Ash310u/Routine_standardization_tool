# Routine Standardization Tool --- Implementation Plan

## 1. Goal

Build a Python-based system that converts college routines from **Excel,
digital PDF, scanned PDF, or images** into one standardized JSON format.

The system should: - Extract college/routine metadata. - Understand
timetable rows, columns, times, days, and merged periods. - Extract
subject, subject code, faculty initials, classroom, and other cell
content. - Handle occasional handwritten additions or corrections. -
Standardize inconsistent subject names against the college's canonical
subject database. - Assign confidence scores and send uncertain cases
for human validation.

The target is not to force 100% automatic extraction. High-confidence
data is accepted automatically; uncertain cases are flagged for review.

------------------------------------------------------------------------

## 2. Core Architecture

``` text
INPUT
 │
 ├── Excel (.xlsx)
 │      └── openpyxl
 │
 ├── Digital PDF
 │      └── PyMuPDF
 │
 └── Scan / Image / Scanned PDF
        └── OpenCV → PaddleOCR
                    │
                    └── suspicious handwriting → TrOCR
                                      │
                                      ▼
                              RAW ROUTINE DATA
                                      │
                                      ▼
                         SUBJECT STANDARDIZATION
                                      │
                Alias → RapidFuzz → Embeddings → FAISS
                                      │
                                      ▼
                              CONFIDENCE ENGINE
                                /           \
                              High          Low
                               │             │
                            Accept       Human Review
                               │             │
                               └──────┬──────┘
                                      ▼
                             STANDARD JSON
```

------------------------------------------------------------------------

## 3. Main Python Components

  -------------------------------------------------------------------------
  Component               Framework / Library     Responsibility
  ----------------------- ----------------------- -------------------------
  API                     FastAPI                 Upload files and expose
                                                  conversion endpoints

  Excel parser            openpyxl                Read cells, merged cells,
                                                  metadata, and timetable
                                                  structure

  PDF parser              PyMuPDF                 Read native PDF text,
                                                  coordinates, and pages

  Image preprocessing     OpenCV                  Deskew, perspective
                                                  correction, denoise,
                                                  detect table lines/cells

  Primary OCR             PaddleOCR               Recognize normal printed
                                                  timetable text

  Handwriting fallback    TrOCR                   Recognize isolated
                                                  handwritten text regions

  Text normalization      Python / Regex          Clean OCR output and
                                                  normalize codes/names

  Fuzzy matching          RapidFuzz               Handle spelling/OCR/name
                                                  variations

  Semantic matching       SentenceTransformers    Compare semantically
                                                  similar subject names

  Vector search           FAISS                   Search canonical
                                                  subject/alias embeddings

  Schema validation       Pydantic                Validate extracted JSON

  Database                PostgreSQL              Subjects, aliases,
                                                  faculty references,
                                                  corrections, processing
                                                  history

  Optional fallback       Vision LLM API          Interpret highly
                                                  ambiguous
                                                  handwritten/overwritten
                                                  cells
  -------------------------------------------------------------------------

------------------------------------------------------------------------

## 4. TrOCR

**TrOCR (Transformer-based Optical Character Recognition)** is a
pretrained Microsoft transformer model for recognizing printed and
handwritten text from images.

We do **not train TrOCR ourselves**. The pretrained model is downloaded
and hosted locally using Python/Hugging Face Transformers. It is used
only as a fallback when normal OCR cannot confidently read a suspicious
handwritten timetable region.

Example:

``` text
Timetable Cell
      ↓
PaddleOCR
      ↓
Low confidence / suspicious handwriting
      ↓
Crop handwritten region
      ↓
TrOCR
      ↓
"Tutorial"
```

TrOCR's responsibility is **transcription**, not timetable reasoning.
Crossed-out text, replacements, and ambiguous edits should remain
reviewable or optionally be sent to a vision model.

------------------------------------------------------------------------

## 5. Standard JSON Schema

Define the output format before building extraction.

Example:

``` json
{
  "college": "Example College",
  "department": "CSE",
  "year": "2nd",
  "semester": "3rd",
  "section": "A",
  "room": "A504",
  "version": "V1",
  "date": "2026-07-22",
  "classes": [
    {
      "day": "Monday",
      "start_time": "09:20",
      "end_time": "10:10",
      "subject_raw": "DSA",
      "subject_name": "Data Structures and Algorithms",
      "subject_code": "PCC-CS301",
      "faculty_raw": "IT_CB",
      "room": "A504",
      "source": "printed",
      "confidence": 0.96,
      "requires_review": false
    }
  ]
}
```

Always preserve the raw extracted value alongside the standardized
value.

------------------------------------------------------------------------

# 6. Step-by-Step Implementation

## Phase 1 --- Project Foundation

### Implement

1.  Create Python project.
2.  Create FastAPI application.
3.  Define Pydantic models for routine metadata and classes.
4.  Create standardized JSON schema.
5.  Create file-upload endpoint.
6.  Detect uploaded file type.

### Initial structure

``` text
routine-standardizer/
│
├── app/
│   ├── main.py
│   ├── schemas/
│   ├── extractors/
│   ├── ocr/
│   ├── parsers/
│   ├── standardization/
│   ├── confidence/
│   └── database/
│
├── models/
├── tests/
├── samples/
├── Dockerfile
└── requirements.txt
```

------------------------------------------------------------------------

## Phase 2 --- Excel Extraction

Use `openpyxl`.

### Extract

-   College name
-   Department
-   Year
-   Semester
-   Section
-   Room
-   Version/date if available
-   Time columns
-   Day rows
-   Cell values
-   Merged cells

### Flow

``` text
XLSX
 ↓
openpyxl
 ↓
Worksheet structure
 ↓
Header metadata
 ↓
Timetable cells
 ↓
Raw JSON
```

Do not convert Excel to an image and OCR it when the original workbook
is available.

------------------------------------------------------------------------

## Phase 3 --- Digital PDF Extraction

Use `PyMuPDF`.

### Implement

1.  Open PDF.
2.  Extract words/text blocks with coordinates.
3.  Detect whether usable native text exists.
4.  Identify header metadata.
5.  Reconstruct timetable positions using coordinates.
6.  Produce raw structured data.

### Flow

``` text
PDF
 ↓
PyMuPDF
 ↓
Native text available?
 ↓ YES
Coordinate-based extraction
 ↓
Raw JSON
```

If usable text is unavailable, send the page to the scanned-document
pipeline.

------------------------------------------------------------------------

## Phase 4 --- Scan/Image Preprocessing

Use `OpenCV`.

### Implement

1.  Render scanned PDF pages to images.
2.  Correct rotation/skew.
3.  Correct perspective when the routine is photographed.
4.  Reduce noise.
5.  Detect the main timetable region.
6.  Detect horizontal and vertical table lines.
7.  Determine rows and columns.
8.  Identify merged cells.
9.  Crop individual timetable cells.

### Intermediate representation

``` python
Cell(
    row=2,
    column=3,
    bbox=(x1, y1, x2, y2),
    image=cell_image
)
```

Table structure and OCR should be treated as separate problems.

------------------------------------------------------------------------

## Phase 5 --- Primary OCR

Use `PaddleOCR`.

### Flow

``` text
Cell image
 ↓
PaddleOCR
 ↓
Text + confidence
```

Store:

``` json
{
  "raw_text": "DSA PCC-CS301 IT_CB",
  "ocr_confidence": 0.94
}
```

Normal printed cells should finish here without invoking TrOCR or an
LLM.

------------------------------------------------------------------------

## Phase 6 --- Handwriting Fallback

Use `TrOCR`.

### Trigger conditions

A cell can be flagged when: - PaddleOCR confidence is low. - OCR returns
no useful text. - Unexpected characters appear. - A handwritten region
is detected. - Printed and handwritten content appear to overlap. - A
possible strike-through/correction is detected.

### Flow

``` text
Suspicious cell
 ↓
Preprocess/crop handwritten region
 ↓
TrOCR
 ↓
Candidate transcription
 ↓
Validate against known timetable vocabulary
```

Example:

``` text
TrOCR → "D5A"

Known semester subjects:
DSA
DBMS
CO
Math-III

Matching → DSA
```

Do not blindly trust TrOCR output. Pass it through the same validation
and confidence system as other OCR output.

------------------------------------------------------------------------

## Phase 7 --- Parse Cell Meaning

Convert OCR text into fields.

Example input:

``` text
DSA (PCC-CS301)
IT2A, IT_CB
```

Target:

``` json
{
  "subject_raw": "DSA",
  "subject_code_raw": "PCC-CS301",
  "faculty_raw": ["IT_CB"]
}
```

Use: - Regular expressions for known code formats. - Known faculty
initials. - Known room formats. - College-specific parsing rules. - Cell
position for day/time.

------------------------------------------------------------------------

## Phase 8 --- Subject Standardization

This is separate from OCR.

### Matching order

``` text
Extracted subject
       ↓
Normalize text
       ↓
Exact subject-code match
       ↓
Exact alias match
       ↓
RapidFuzz
       ↓
SentenceTransformer embedding
       ↓
FAISS cosine similarity search
       ↓
Best canonical subject
```

### Example

``` text
OCR: "Data Struct."
             ↓
Normalize
             ↓
Alias/Fuzzy search
             ↓
Embedding search
             ↓
PCC-CS301
Data Structures and Algorithms
```

### Context filtering

Before semantic search, reduce candidates using:

``` text
College
 ↓
Department
 ↓
Year
 ↓
Semester
 ↓
Available subjects
```

Do not search the complete subject database when the routine context
already narrows the possible subjects.

------------------------------------------------------------------------

## Phase 9 --- Alias and Correction Database

Store common variations.

Example:

``` text
PCC-CS301
│
├── DSA
├── D.S.A
├── Data Structure
├── Data Structures
├── Data Struct.
└── DS & Algo
```

When a human corrects an extraction, save useful corrections as aliases
or OCR mappings where appropriate.

This improves future accuracy without retraining OCR models.

------------------------------------------------------------------------

## Phase 10 --- Confidence Engine

Calculate confidence using multiple signals.

Possible signals:

``` text
OCR confidence
Subject-code validity
Alias match
Fuzzy similarity
Embedding similarity
Subject available in semester
Faculty exists
Room format validity
Day/time validity
Handwriting detected
Conflicting OCR outputs
```

Initial policy:

``` text
HIGH confidence
→ automatically accept

MEDIUM confidence
→ additional validation / optional vision check

LOW confidence
→ human review
```

Thresholds must be calibrated using real routine data rather than
assumed permanently.

------------------------------------------------------------------------

## Phase 11 --- Human Validation

Build a small review interface.

For uncertain entries show:

``` text
Original cell image

Extracted:
D5A

Suggested:
DSA
Data Structures and Algorithms
PCC-CS301

Confidence: LOW

[Accept]
[Correct]
```

Store accepted corrections for future matching.

------------------------------------------------------------------------

## Phase 12 --- Optional Vision LLM

A vision LLM should be a final fallback, not the primary extractor.

Use it when: - Printed content is crossed out and handwriting replaces
it. - Handwriting overlaps printed text. - TrOCR and PaddleOCR disagree
strongly. - It is necessary to determine which text is currently active.

Preferred flow:

``` text
PaddleOCR
    ↓
TrOCR
    ↓
Database validation
    ↓
Still uncertain?
    ↓
Vision LLM
    ↓
Still uncertain?
    ↓
Human review
```

For cost optimization, send only the suspicious cell/crop rather than
the complete routine whenever possible.

------------------------------------------------------------------------

# 7. Processing Strategy

Do not execute every model for every document.

``` text
                         FILE
                          │
              ┌───────────┴───────────┐
              ↓                       ↓
            XLSX                  PDF/Image
              ↓                       ↓
          openpyxl             Digital PDF?
                                  /       \
                                YES        NO
                                 ↓          ↓
                             PyMuPDF    OpenCV + OCR
                                            │
                                            ↓
                                         Parser
                                            │
                                      Suspicious?
                                       /       \
                                     NO         YES
                                     ↓           ↓
                                   DONE        TrOCR
                                                 │
                                           uncertain?
                                            /      \
                                          NO        YES
                                          ↓          ↓
                                        DONE    Vision LLM
                                                     │
                                                uncertain?
                                                     ↓
                                               Human Review
```

This keeps compute and API usage low.

------------------------------------------------------------------------

# 8. Suggested Infrastructure

## Initial Development / Production

``` text
Linux server
4–8 vCPU
16 GB RAM
~50 GB SSD
No dedicated GPU initially
```

Run: - FastAPI - PyMuPDF - openpyxl - OpenCV - PaddleOCR - TrOCR
Small/Base - SentenceTransformers - FAISS

PostgreSQL can run on the same server initially or separately.

A GPU should only be added after benchmarking real workloads and
determining that CPU inference is too slow.

------------------------------------------------------------------------

# 9. Model Loading

Models should load once when the worker starts.

``` text
Application startup
       ↓
Load PaddleOCR
Load TrOCR
Load SentenceTransformer
Load FAISS index
       ↓
Keep models in memory
       ↓
Process many routines
```

Do not reload models for every timetable or cell.

------------------------------------------------------------------------

# 10. Optimization Rules

1.  Use native Excel data instead of OCR whenever possible.
2.  Use native PDF text before OCR.
3.  OCR only scans/images.
4.  Crop the timetable before heavy image processing.
5.  Process cells instead of repeatedly processing the complete page.
6.  Invoke TrOCR only for suspicious handwritten regions.
7.  Start with TrOCR Small and benchmark before moving to larger models.
8.  Filter subjects by college/department/semester before semantic
    matching.
9.  Precompute canonical subject embeddings.
10. Keep the FAISS index in memory.
11. Use the vision LLM only for genuinely ambiguous cases.
12. Batch administrative uploads; real-time millisecond latency is
    unnecessary.

------------------------------------------------------------------------

# 11. Accuracy Measurement

Measure accuracy at the **field/cell level**, not only the document
level.

Track separately:

``` text
Metadata extraction accuracy
Day/time extraction accuracy
Table/cell detection accuracy
Printed OCR accuracy
Handwriting recognition accuracy
Subject-code accuracy
Subject-standardization accuracy
Faculty extraction accuracy
Room extraction accuracy
Automatic acceptance rate
Human-review rate
False automatic acceptance rate
```

A routine that is 99% correct can still contain one operationally
important wrong class, so uncertain values must remain reviewable.

------------------------------------------------------------------------

# 12. Recommended Build Order

``` text
1. JSON schema
       ↓
2. FastAPI/file input
       ↓
3. Excel → JSON
       ↓
4. Digital PDF → JSON
       ↓
5. OpenCV scan preprocessing
       ↓
6. Table/cell detection
       ↓
7. PaddleOCR
       ↓
8. Cell parser
       ↓
9. Subject alias + RapidFuzz matching
       ↓
10. SentenceTransformer + FAISS
       ↓
11. TrOCR handwriting fallback
       ↓
12. Confidence engine
       ↓
13. Human validation
       ↓
14. Optional Vision LLM
       ↓
15. Benchmark + optimize
```

------------------------------------------------------------------------

# 13. Final Principle

The system should not depend on one model to understand the entire
routine.

``` text
openpyxl / PyMuPDF
→ understand digital files

OpenCV
→ understand document/table geometry

PaddleOCR
→ read normal printed text

TrOCR
→ read isolated handwriting

RapidFuzz + embeddings
→ standardize inconsistent subject names

Confidence engine
→ determine uncertainty

Vision LLM
→ handle exceptional ambiguous visual edits

Human validation
→ resolve remaining uncertain cases
```

The goal is therefore not **"AI reads every routine perfectly."**

The goal is:

> **Automatically process high-confidence routine data, detect
> uncertainty reliably, and require human intervention only where the
> system cannot safely determine the intended value.**
