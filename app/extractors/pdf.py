from __future__ import annotations

from app.schemas.models import Grid, RawCell


def extract_pdf(data: bytes) -> tuple[list[Grid], list[tuple[int, bytes]]]:
    import fitz

    document = fitz.open(stream=data, filetype="pdf")
    grids: list[Grid] = []
    scans: list[tuple[int, bytes]] = []
    for page_number, page in enumerate(document, 1):
        words = page.get_text("words")
        if len(words) < 8:
            scans.append((page_number, page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")))
            continue
        context = page.get_text("text")
        tables = page.find_tables()
        for table in tables.tables:
            content = table.extract()
            # Some PDF tables have irregular or merged rows. PyMuPDF can
            # return fewer bounding boxes than the extracted cell values.
            # Keep the text and omit unreliable coordinates in that case.
            aligned_boxes = (len(table.cells) == len(content) * table.col_count
                             and all(len(values) == table.col_count for values in content))
            rows = []
            for r, values in enumerate(content, 1):
                cells = []
                for c, value in enumerate(values, 1):
                    box = table.cells[(r - 1) * table.col_count + c - 1] if aligned_boxes else None
                    bbox = tuple(box) if box else None
                    cells.append(RawCell(text=value or "", row=r, column=c, page=page_number, bbox=bbox))
                rows.append(cells)
            grids.append(Grid(rows=rows, page=page_number, context_text=context))
        if not tables.tables:
            grids.append(_grid_from_words(words, page_number, context))
    document.close()
    return grids, scans


def _grid_from_words(words: list[tuple], page: int, context: str) -> Grid:
    """Recover simple borderless tables from native word coordinates."""
    from app.parsers.text import parse_time_range

    lines: list[list[tuple]] = []
    for word in sorted(words, key=lambda w: (round(w[1] / 5), w[0])):
        center = (word[1] + word[3]) / 2
        target = next((line for line in lines if abs((line[0][1] + line[0][3]) / 2 - center) <= 5), None)
        if target is None:
            lines.append([word])
        else:
            target.append(word)
    lines.sort(key=lambda line: min(w[1] for w in line))
    for line in lines:
        line.sort(key=lambda w: w[0])
    header = None
    for index, line in enumerate(lines):
        candidates = []
        for start in range(len(line)):
            for end in range(start + 1, min(start + 5, len(line)) + 1):
                text = " ".join(w[4] for w in line[start:end])
                if parse_time_range(text):
                    candidates.append((line[start][0], line[end - 1][2], text))
        nonoverlap = []
        for item in sorted(candidates, key=lambda x: x[0]):
            if not nonoverlap or item[0] >= nonoverlap[-1][1] - 2:
                nonoverlap.append(item)
        if len(nonoverlap) >= 2:
            header = (index, nonoverlap)
            break
    if header is None:
        return Grid(rows=[], page=page, context_text=context)
    index, periods = header
    centers = [(a + b) / 2 for a, b, _ in periods]
    boundaries = [(a + b) / 2 for a, b in zip(centers, centers[1:])]
    rows = []
    header_cells = [RawCell(text="Day", row=1, column=1, page=page)]
    header_cells.extend(RawCell(text=value, row=1, column=col + 2, page=page)
                        for col, (_, _, value) in enumerate(periods))
    rows.append(header_cells)
    for row_number, line in enumerate(lines[index + 1:], 2):
        buckets: list[list[tuple]] = [[] for _ in range(len(periods) + 1)]
        for word in line:
            x = (word[0] + word[2]) / 2
            if x < centers[0] - 20:
                bucket = 0
            else:
                bucket = 1 + sum(x > boundary for boundary in boundaries)
            buckets[bucket].append(word)
        row = []
        for col, bucket in enumerate(buckets, 1):
            bbox = ((min(w[0] for w in bucket), min(w[1] for w in bucket),
                     max(w[2] for w in bucket), max(w[3] for w in bucket)) if bucket else None)
            row.append(RawCell(text=" ".join(w[4] for w in bucket), row=row_number,
                               column=col, page=page, bbox=bbox))
        rows.append(row)
    return Grid(rows=rows, page=page, context_text=context)
