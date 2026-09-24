from __future__ import annotations

import re

from app.parsers.text import CODE_RE, day_of, extract_metadata, parse_class_text, parse_time_range_checked
from app.schemas.models import ClassSession, Grid, ReviewItem, Routine


def parse_grids(grids: list[Grid]) -> Routine:
    routine = Routine()
    contexts: list[Routine] = []
    for grid in grids:
        before = len(routine.classes)
        contexts.extend(parse_grid(grid, routine))
        if len(routine.classes) == before:
            routine.review_items.append(ReviewItem(
                reason="No timetable structure recognized on this page or sheet",
                raw_text=grid.context_text[:1000] or None, page=grid.page))
    for field in ("college", "course", "department", "year", "semester", "section", "room", "version", "date"):
        values = {getattr(context, field) for context in contexts if getattr(context, field) is not None}
        if len(values) == 1 and all(getattr(context, field) is not None for context in contexts):
            setattr(routine, field, next(iter(values)))
        elif len(values) > 1 and field in ("course", "department", "semester", "section"):
            routine.warnings.append(f"Multiple {field} values; use each class's context")
    if not routine.classes and not routine.review_items:
        routine.review_items.append(ReviewItem(reason="No timetable classes could be located; inspect the source document"))
    return routine


def parse_grid(grid: Grid, routine: Routine) -> list[Routine]:
    rows = grid.rows
    headers: list[tuple[int, list[tuple[str, str] | None], list[bool]]] = []
    for index, row in enumerate(rows):
        checked = [parse_time_range_checked(cell.text) for cell in row]
        periods = [item[0] for item in checked]
        if sum(period is not None for period in periods) >= 2:
            headers.append((index, periods, [item[1] for item in checked]))
    contexts: list[Routine] = []
    for block, (header_index, periods, repaired) in enumerate(headers):
        previous_header = headers[block - 1][0] if block else -1
        next_header = headers[block + 1][0] if block + 1 < len(headers) else len(rows)
        context = Routine()
        extract_metadata(grid.context_text, context)
        for row in rows[previous_header + 1:header_index]:
            parts = list(dict.fromkeys(cell.text for cell in row if cell.text.strip()))
            for part in parts:
                extract_metadata(part, context)
        region = rows[header_index + 1:next_header]
        day_col = max(range(min(4, len(periods))),
                      key=lambda col: sum(col < len(row) and day_of(row[col].text) is not None for row in region),
                      default=0)
        if not any(day_col < len(row) and day_of(row[day_col].text) for row in region):
            continue
        contexts.append(context)
        current_day = None
        for row in region:
            if day_col >= len(row):
                continue
            day = day_of(row[day_col].text)
            if day:
                current_day = day
            elif grid.source_name is not None or row[day_col].text.strip():
                current_day = None
            if current_day is None:
                continue
            col = 0
            while col < min(len(periods), len(row)):
                period = periods[col]
                if col == day_col or period is None:
                    col += 1
                    continue
                cell = row[col]
                start_col = col
                last = col
                if grid.source_name is not None and cell.cell_ref:
                    while (last + 1 < min(len(periods), len(row)) and periods[last + 1] is not None
                           and row[last + 1].cell_ref == cell.cell_ref):
                        last += 1
                col = last + 1
                value = cell.text.strip()
                if not value or re.fullmatch(r"[-–—/]|break|lunch|recess|free", value, re.I):
                    continue
                subject, code, faculty, room = parse_class_text(value)
                if not subject and not code:
                    continue
                raw_codes = {re.sub(r"[^A-Z0-9]", "", match.upper()) for match in CODE_RE.findall(value)}
                reasons = []
                if len(raw_codes) > 1:
                    reasons.append("Cell contains multiple subject codes")
                if any(repaired[start_col:last + 1]):
                    reasons.append("Time header required AM/PM correction")
                routine.classes.append(ClassSession(
                    day=current_day, start_time=period[0], end_time=periods[last][1],
                    subject_raw=subject or code or value, subject_code_raw=code,
                    college=context.college, course=context.course,
                    department=context.department, year=context.year,
                    semester=context.semester, section=context.section,
                    faculty_raw=faculty, room=room or context.room,
                    source=cell.source, confidence=0, page=cell.page,
                    cell_ref=cell.cell_ref, bbox=cell.bbox, review_reasons=reasons,
                ))
    return contexts
