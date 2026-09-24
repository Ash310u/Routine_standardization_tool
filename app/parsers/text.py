from __future__ import annotations

import re
from datetime import datetime

from app.schemas.models import Routine

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DAY_ALIASES = {name.lower(): name for name in DAY_NAMES}
DAY_ALIASES.update({name[:3].lower(): name for name in DAY_NAMES})
DAY_ALIASES.update({"mo": "Monday", "tu": "Tuesday", "we": "Wednesday", "th": "Thursday", "fr": "Friday", "sa": "Saturday", "su": "Sunday"})
TIME_RE = re.compile(r"(?<!\d)(\d{1,2})(?:[:.]([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)?(?!\d)", re.I)
RANGE_RE = re.compile(r"(\d{1,2}(?:[:.]\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)\s*(?:-|–|—|to)\s*(\d{1,2}(?:[:.]\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)", re.I)
CODE_RE = re.compile(r"\b[A-Z]{2,8}(?:[- _]*[A-Z]{1,6}){0,2}[- _]*\d{2,4}(?:[- _]*[A-Z])?\b", re.I)
ROOM_RE = re.compile(r"\b(?:room|rm|lab)\s*[:#-]?\s*([A-Z]{0,3}[- ]?\d{2,4}[A-Z]?)\b", re.I)


def day_of(text: str) -> str | None:
    cleaned = re.sub(r"[^a-z]", "", text.lower())
    return DAY_ALIASES.get(cleaned)


def parse_time_range(text: str) -> tuple[str, str] | None:
    parsed, _ = parse_time_range_checked(text)
    return parsed


def parse_time_range_checked(text: str) -> tuple[tuple[str, str] | None, bool]:
    match = RANGE_RE.search(text)
    if not match:
        return None, False
    first, second = match.groups()
    meridiem = re.search(r"([ap])\.?m\.?", second, re.I)
    if meridiem and not re.search(r"[ap]\.?m\.?,?", first, re.I):
        first += meridiem.group(0)
    times = [normalize_time(piece) for piece in (first, second)]
    if None in times:
        return None, False
    start, end = times
    if 0 < _minutes(end) - _minutes(start) <= 180:
        return (start, end), False
    # Some workbook headers contain inconsistent AM/PM markers. Repair only
    # when a single toggle yields a plausible daytime teaching period.
    candidates = []
    for change_start, change_end in ((True, False), (False, True), (True, True)):
        a = _toggle_meridiem(start) if change_start and re.search(r"[ap]\.?m", first, re.I) else start
        b = _toggle_meridiem(end) if change_end and re.search(r"[ap]\.?m", second, re.I) else end
        duration = _minutes(b) - _minutes(a)
        if 15 <= duration <= 180 and 7 <= int(a[:2]) <= 18 and 7 <= int(b[:2]) <= 19:
            candidates.append((abs(duration - 55), a, b))
    if candidates:
        _, a, b = min(candidates)
        return (a, b), True
    return None, False


def _minutes(value: str) -> int:
    return int(value[:2]) * 60 + int(value[3:])


def _toggle_meridiem(value: str) -> str:
    hour = (int(value[:2]) + 12) % 24
    return f"{hour:02d}{value[2:]}"


def normalize_time(text: str) -> str | None:
    match = TIME_RE.search(text.strip())
    if not match:
        return None
    hour, minute, ampm = match.groups()
    h = int(hour)
    m = int(minute or 0)
    if ampm:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ampm.lower().startswith("p") else 0)
    if h > 23:
        return None
    return f"{h:02d}:{m:02d}"


def extract_metadata(text: str, routine: Routine) -> None:
    if routine.college is None:
        first_line = re.sub(r"\s+", " ", text.strip().splitlines()[0]).strip() if text.strip() else ""
        if (len(first_line) >= 8 and first_line == first_line.upper()
                and re.search(r"\b(?:COLLEGE|INSTITUTE|UNIVERSITY|INTERNATIONAL|SCHOOL|ENGINEERING)\b", first_line)
                and not re.search(r"\b(?:ROUTINE|SEMESTER|DEPARTMENT)\b", first_line, re.I)):
            routine.college = first_line
    course_match = re.search(r"\b(M\.?Tech|B\.?Tech|MBA|BCA|BBA)\b", text, re.I)
    if routine.course is None and course_match:
        course = course_match.group(1).replace(".", "").lower()
        routine.course = {"mtech": "M.Tech", "btech": "B.Tech", "mba": "MBA", "bca": "BCA", "bba": "BBA"}[course]
    labels = {
        "department": r"(?:department|dept\.?|branch)",
        "year": r"year",
        "semester": r"sem(?:ester)?\.?(?!\s+routine)",
        "section": r"sec(?:tion)?\.?",
        "room": r"(?:classroom|room)",
        "version": r"(?:version|ver\.?|revision)",
    }
    next_label = r"(?:department|dept\.?|branch|year|semester|sem\.?|section|sec\.?|classroom|room|version|ver\.?|revision)"
    for field, label in labels.items():
        if getattr(routine, field) is not None:
            continue
        pattern = rf"\b{label}\s*[:\-]\s*(.*?)(?=\s+{next_label}\s*[:\-]|[\n|]|$)"
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        value = match.group(1).strip(" :-")
        if field in ("year", "semester"):
            ordinal = re.match(r"(?:\d{1,2}(?:st|nd|rd|th)?|[IVX]{1,4})\b", value, re.I)
            value = ordinal.group() if ordinal else ""
        elif field == "section":
            value = re.match(r"[A-Z0-9+ -]{1,15}", value, re.I).group().strip() if value else ""
        elif field == "version":
            value = re.match(r"[A-Z0-9.\-]+", value, re.I).group() if value else ""
        if value:
            setattr(routine, field, value)
    if routine.date is None:
        match = re.search(r"\b(?:date|effective from)\s*[:\-]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})", text, re.I)
        if match:
            value = match.group(1).replace("/", "-")
            for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
                try:
                    routine.date = datetime.strptime(value, fmt).date()
                    break
                except ValueError:
                    pass


def parse_class_text(text: str) -> tuple[str, str | None, str | None, str | None]:
    clean = re.sub(r"\s+", " ", text).strip()
    code_match = CODE_RE.search(clean)
    code = code_match.group().upper() if code_match else None
    if code_match:
        clean = (clean[:code_match.start()] + " " + clean[code_match.end():]).strip(" -,")
    room_match = ROOM_RE.search(clean)
    room = room_match.group(1).replace(" ", "").upper() if room_match else None
    if room_match:
        clean = (clean[:room_match.start()] + " " + clean[room_match.end():]).strip()
    faculty = None
    initial = re.match(r"^\s*[\[(]([A-Z]{2,5}\d?(?:\s*[+,/]\s*[A-Z]{2,5}\d?)*)[\])]", clean)
    if initial:
        faculty = initial.group(1).strip()
        clean = clean[initial.end():].strip(" -(),")
    trailing = re.search(r"\s*[\[(]([A-Z]{2,5}\d?(?:\s*[+,/]\s*[A-Z]{2,5}\d?)*)[\])]\s*$", clean)
    if trailing and faculty is None:
        faculty = trailing.group(1).strip()
        clean = clean[:trailing.start()].strip()
    match = re.search(r"(?:faculty|fac|teacher)\s*[:\-]\s*([A-Z_., /-]+)$", clean, re.I)
    if match:
        faculty = match.group(1).strip()
        clean = clean[:match.start()].strip(" -(),")
    elif "\n" in text:
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        if len(lines) > 1 and re.fullmatch(r"[A-Z]{2,5}(?:[_ ,/][A-Z0-9]{1,5})*", lines[-1]):
            faculty = lines[-1]
            clean = clean.removesuffix(faculty).strip(" -(),")
    clean = re.sub(r"\(\s*\)|\[\s*\]", "", clean).strip(" -(),")
    if clean.startswith("(") and clean.endswith(")"):
        clean = clean[1:-1].strip()
    return clean, code, faculty, room
