from __future__ import annotations

import json
import hashlib
from pathlib import Path

from pydantic import BaseModel, Field


class Subject(BaseModel):
    name: str
    code: str
    aliases: list[str] = Field(default_factory=list)
    subject_master_id: int | None = None
    course: str | None = None
    subject_type: str | None = None
    college: str | None = None
    department: str | None = None
    year: str | None = None
    semester: str | None = None


class Catalog:
    def __init__(self, subjects: list[Subject], source_hash: str | None = None):
        self.subjects = subjects
        self.source_hash = source_hash or hashlib.sha256(
            json.dumps([s.model_dump() for s in subjects], sort_keys=True).encode()
        ).hexdigest()
        self.by_key: dict[str, Subject] = {}
        self.by_code: dict[str, list[Subject]] = {}
        self._keys_by_identity: dict[int, str] = {}
        for index, subject in enumerate(subjects):
            key = str(subject.subject_master_id) if subject.subject_master_id is not None else f"simple:{index}"
            if key in self.by_key:
                raise ValueError(f"Duplicate subject identity: {key}")
            self.by_key[key] = subject
            self._keys_by_identity[id(subject)] = key
            self.by_code.setdefault(_code_key(subject.code), []).append(subject)

    def key_for(self, subject: Subject) -> str:
        return self._keys_by_identity[id(subject)]

    def code_matches(self, code: str) -> list[Subject]:
        return self.by_code.get(_code_key(code), [])

    @classmethod
    def from_file(cls, path: str | Path | None, aliases_path: str | Path | None = None) -> "Catalog":
        if not path:
            return cls([])
        raw = Path(path).read_bytes()
        data = json.loads(raw)
        aliases_raw = Path(aliases_path).read_bytes() if aliases_path else b"{}"
        aliases = json.loads(aliases_raw)
        if not isinstance(aliases, dict):
            raise ValueError("Alias overlay must be an object keyed by SubjectMasterId")
        if isinstance(data, dict):
            if data.get("ok") is not True or not isinstance(data.get("data"), list):
                raise ValueError("Expected a successful subject API response with a data list")
            subjects = [Subject(
                subject_master_id=item["SubjectMasterId"],
                name=item["Name"], code=item["Code"],
                course=item["Course"], department=item["Stream"],
                semester=item["Semester"], subject_type=item["SubjectType"],
                aliases=aliases.get(str(item["SubjectMasterId"]), []),
            ) for item in data["data"]]
        elif isinstance(data, list):
            subjects = [Subject.model_validate(item) for item in data]
        else:
            raise ValueError("Subject catalog must be a list or API response object")
        digest = hashlib.sha256(raw + b"\0" + aliases_raw).hexdigest()
        return cls(subjects, digest)

    def candidates(self, *, college: str | None = None, department: str | None = None,
                   year: str | None = None, semester: str | None = None,
                   course: str | None = None) -> list[Subject]:
        result = []
        for subject in self.subjects:
            if all(not getattr(subject, field) or not value or
                   _same(getattr(subject, field), value)
                   for field, value in (("college", college), ("department", department),
                                        ("year", year), ("semester", semester), ("course", course))):
                result.append(subject)
        return result


def _same(left: str, right: str) -> bool:
    import re

    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower()).removesuffix("st").removesuffix("nd").removesuffix("rd").removesuffix("th")

    return norm(left) == norm(right)


def _code_key(code: str) -> str:
    import re

    return re.sub(r"[^A-Z0-9]", "", code.upper())
