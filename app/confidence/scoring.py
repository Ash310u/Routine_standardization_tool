from __future__ import annotations

from app.schemas.models import ClassSession, MatchSuggestion
from app.standardization.matcher import Match


def score_class(item: ClassSession, match: Match, ocr_confidence: float | None = None) -> None:
    reasons = [reason for reason in item.review_reasons if reason != "unscored"]
    item.match_method = match.method
    item.name_lookup_status = match.name_lookup_status
    item.cosine_similarity = round(match.similarity, 4) if match.similarity is not None else None
    item.match_margin = (round(match.similarity - match.runner_up_score, 4)
                         if match.similarity is not None and match.runner_up_score is not None else None)
    item.match_candidates = [MatchSuggestion(subject_master_id=subject.subject_master_id,
                                             name=subject.name, code=subject.code,
                                             subject_type=subject.subject_type,
                                             score=round(score, 4))
                             for subject, score in (match.candidates or [])]
    if match.subject:
        item.subject_name = match.subject.name
        item.subject_code = match.subject.code
        item.subject_type = match.subject.subject_type
        item.subject_master_id = match.subject.subject_master_id
        item.catalog_course = match.subject.course
        item.catalog_stream = match.subject.department
        item.catalog_semester = match.subject.semester
    else:
        if match.common_subject:
            item.subject_name = match.common_subject.name
            item.subject_code = match.common_subject.code
            item.subject_type = match.common_subject.subject_type
        reasons.append("Catalog subject record was not identified unambiguously")
    if match.context_mismatch:
        reasons.append("Matched code belongs to a different or unrecognized catalog context")
    if match.method == "unmatched_code":
        reasons.append("Extracted subject code is absent from the catalog")
        name_reason = {
            "name_unavailable": "No readable subject name was available for lookup",
            "index_unavailable": "Subject name was not checked against an embedding index",
            "exact_name_found": "Catalog name text was found, but its code conflicts with the extracted code",
            "similar_name_found": "A similar catalog name exists, but its code conflicts with the extracted code",
            "no_strong_candidate": "No strong name candidate was found in the embedding index",
        }.get(match.name_lookup_status)
        if name_reason:
            reasons.append(name_reason)
    if match.ambiguous:
        reasons.append("Multiple subjects match")
    if match.method == "semantic":
        reasons.append("Semantic match needs validation until thresholds are calibrated")
        if not all((item.course, item.department, item.semester)):
            reasons.append("Incomplete course, stream, or semester context")
    if item.source == "handwritten":
        reasons.append("Handwriting requires validation")
    if item.source == "unknown":
        reasons.append("Source text was not confirmed")
    if ocr_confidence is not None and ocr_confidence < 0.85:
        reasons.append("Low OCR confidence")
    if item.subject_code_raw and item.subject_code and _norm(item.subject_code_raw) != _norm(item.subject_code):
        reasons.append("Extracted code conflicts with canonical code")
    if (match.method != "code" and match.subject and item.subject_raw and "lab" in item.subject_raw.lower()
            and match.subject.subject_type and "lab" not in match.subject.subject_type.lower()):
        reasons.append("Extracted lab text conflicts with canonical subject type")
    if (match.method == "code" and match.subject and item.subject_raw.strip()
            and _norm(item.subject_raw) != _norm(item.subject_code_raw or "")):
        from difflib import SequenceMatcher
        import re

        from app.standardization.matcher import normalize

        # Bracketed group, room, and faculty notes are common in timetable
        # cells. Only compare a plain subject label with the catalog name.
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9 &./-]{0,59}", item.subject_raw.strip()):
            similarity = max(SequenceMatcher(None, normalize(item.subject_raw), normalize(alias)).ratio()
                             for alias in [match.subject.name, *match.subject.aliases])
            if similarity < 0.6:
                reasons.append("Extracted subject text conflicts with matched code")
    if not item.subject_raw.strip():
        reasons.append("Missing subject text")
    source_score = {"native": 1.0, "printed": ocr_confidence if ocr_confidence is not None else 0.7,
                    "handwritten": 0.55, "unknown": 0.4}[item.source]
    match_strength = (0.5 + 0.25 * max(0.0, match.similarity or 0.0)
                      if match.method == "semantic" else match.score)
    item.confidence = round(min(source_score, match_strength if match.subject else 0.49), 3)
    item.requires_review = item.confidence < 0.92 or bool(reasons)
    item.review_reasons = reasons or ([] if not item.requires_review else ["Confidence below automatic acceptance threshold"])


def _norm(text: str) -> str:
    import re

    return re.sub(r"[^A-Z0-9]", "", text.upper())
