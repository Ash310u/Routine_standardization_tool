from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.database.catalog import Catalog, Subject

if TYPE_CHECKING:
    from app.standardization.semantic import SemanticIndex


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


@dataclass
class Match:
    subject: Subject | None
    score: float
    method: str
    ambiguous: bool = False
    similarity: float | None = None
    runner_up_score: float | None = None
    candidates: list[tuple[Subject, float]] | None = None
    context_mismatch: bool = False
    common_subject: Subject | None = None


def _duplicate_code_match(subjects: list[Subject]) -> Match:
    common = (subjects[0] if len({(subject.name.strip().casefold(), subject.subject_type)
                                  for subject in subjects}) == 1 else None)
    return Match(None, 0, "duplicate_code", True,
                 candidates=[(subject, 1) for subject in subjects[:3]], common_subject=common)


def match_subject(raw: str, code: str | None, catalog: Catalog, *, college: str | None,
                  department: str | None, year: str | None, semester: str | None,
                  course: str | None = None, semantic: "SemanticIndex | None" = None) -> Match:
    from rapidfuzz import fuzz

    candidates = catalog.candidates(college=college, department=department, year=year,
                                    semester=semester, course=course)
    if code:
        global_matches = catalog.code_matches(code)
        if not global_matches:
            return Match(None, 0, "unmatched_code")
        scoped = [subject for subject in global_matches if subject in candidates]
        if len(scoped) == 1:
            return Match(scoped[0], 1, "code")
        if len(scoped) > 1:
            return _duplicate_code_match(scoped)
        if len(global_matches) == 1:
            return Match(global_matches[0], 1, "code", context_mismatch=True)
        # A revision class may use a subject from another semester. A unique
        # stream/code pair can still identify it, while the context conflict
        # stays visible for review.
        for relaxed in (
            catalog.candidates(college=college, department=department, year=year,
                               semester=None, course=course),
            catalog.candidates(college=college, department=None, year=year,
                               semester=semester, course=course),
        ):
            matches = [subject for subject in global_matches if subject in relaxed]
            if len(matches) == 1:
                return Match(matches[0], 1, "code", context_mismatch=True)
        return _duplicate_code_match(global_matches)
    if not candidates:
        return Match(None, 0, "no_catalog_candidates")
    needle = normalize(raw)
    if not needle:
        return Match(None, 0, "empty_subject")
    if re.search(r"extended research hours|college activity", raw, re.I):
        return Match(None, 0, "non_subject_activity")
    exact = [s for s in candidates if any(normalize(alias) == needle for alias in [s.name, *s.aliases])]
    if len(exact) == 1:
        return Match(exact[0], 0.98, "alias")
    if len(exact) > 1:
        return Match(None, 0, "ambiguous_alias", True, candidates=[(s, 1) for s in exact[:3]])
    ranked = sorted(((max(fuzz.ratio(needle, normalize(alias)) for alias in [s.name, *s.aliases]) / 100, s)
                     for s in candidates), key=lambda pair: pair[0], reverse=True)
    if not ranked:
        return Match(None, 0, "no_match")
    best_score, best = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else None
    suggestions = [(subject, score) for score, subject in ranked[:3]]
    if best_score >= 0.90 and (second_score is None or best_score - second_score >= 0.08):
        return Match(best, best_score, "fuzzy", candidates=suggestions, runner_up_score=second_score)
    if semantic is not None:
        hits = semantic.search(raw, candidates, course=course, department=department,
                               semester=semester, top_k=3)
        if hits:
            similarity = hits[0][1]
            runner_up = hits[1][1] if len(hits) > 1 else None
            ambiguous = runner_up is not None and similarity - runner_up < 0.07
            selected = hits[0][0] if similarity >= 0.68 and not ambiguous else None
            return Match(selected, similarity, "semantic", ambiguous, similarity,
                         runner_up, hits)
    if best_score < 0.84:
        return Match(None, best_score, "weak_fuzzy", candidates=suggestions)
    ambiguous = second_score is not None and best_score - second_score < 0.10
    return Match(best if not ambiguous else None, best_score, "fuzzy", ambiguous,
                 runner_up_score=second_score, candidates=suggestions)
