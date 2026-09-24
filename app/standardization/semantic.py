"""Local cosine search over canonical subject names and confirmed aliases."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from app.database.catalog import Catalog, Subject

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _context(value: str | None) -> str:
    text = re.sub(r"[^a-z0-9]", "", (value or "").lower())
    return re.sub(r"(st|nd|rd|th)$", "", text) if re.fullmatch(r"\d+(st|nd|rd|th)", text) else text


def _scope(course: str | None, stream: str | None, semester: str | None) -> str:
    return "|".join((_context(course), _context(stream), _context(semester)))


class SemanticIndex:
    def __init__(self, catalog: Catalog, directory: str | Path):
        self.catalog = catalog
        self.directory = Path(directory)
        manifest_path = self.directory / "manifest.json"
        if not manifest_path.exists():
            raise RuntimeError(f"Semantic index missing at {manifest_path}; build it first")
        self.manifest = json.loads(manifest_path.read_text())
        if self.manifest["catalog_hash"] != catalog.source_hash:
            raise RuntimeError("Semantic index is stale for this catalog or alias overlay; rebuild it")
        self._model = None
        self._indexes: dict[str, tuple[object, list[str]]] = {}
        self._query_cache: dict[str, object] = {}

    @classmethod
    def build(cls, catalog: Catalog, directory: str | Path,
              model_name: str = DEFAULT_MODEL, revision: str | None = None) -> "SemanticIndex":
        import faiss
        import numpy as np
        from sentence_transformers import SentenceTransformer

        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        model = SentenceTransformer(model_name, revision=revision)
        model.save(str(target / "embedding_model"))
        texts: list[str] = []
        subject_keys: list[str] = []
        groups: dict[str, list[int]] = defaultdict(list)
        for subject in catalog.subjects:
            key = catalog.key_for(subject)
            scope = _scope(subject.course, subject.department, subject.semester)
            seen: set[str] = set()
            for label in [subject.name, *subject.aliases]:
                normalized = re.sub(r"\W+", "", label.lower())
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                index = len(texts)
                texts.append(label)
                subject_keys.append(key)
                groups[scope].append(index)
        if not texts:
            raise ValueError("Cannot build semantic index from an empty catalog")
        embeddings = np.asarray(model.encode(texts, normalize_embeddings=True,
                                             convert_to_numpy=True, show_progress_bar=False), dtype="float32")
        groups["__all__"] = list(range(len(texts)))
        manifest = {
            "catalog_hash": catalog.source_hash,
            "model_name": model_name,
            "revision": revision,
            "dimension": int(embeddings.shape[1]),
            "normalized": True,
            "scopes": {},
        }
        for scope, positions in groups.items():
            filename = hashlib.sha256(scope.encode()).hexdigest()[:16]
            index = faiss.IndexFlatIP(embeddings.shape[1])
            index.add(np.ascontiguousarray(embeddings[positions]))
            faiss.write_index(index, str(target / f"{filename}.faiss"))
            (target / f"{filename}.json").write_text(json.dumps(
                [subject_keys[position] for position in positions]))
            manifest["scopes"][scope] = filename
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return cls(catalog, target)

    def _load_scope(self, scope: str):
        import faiss

        if scope not in self._indexes:
            filename = self.manifest["scopes"].get(scope)
            if filename is None:
                return None
            index = faiss.read_index(str(self.directory / f"{filename}.faiss"))
            keys = json.loads((self.directory / f"{filename}.json").read_text())
            if index.ntotal != len(keys) or index.d != self.manifest["dimension"]:
                raise RuntimeError("Semantic index and subject map do not agree")
            self._indexes[scope] = (index, keys)
        return self._indexes[scope]

    def search(self, text: str, candidates: list[Subject], *, course: str | None,
               department: str | None, semester: str | None, top_k: int = 3) -> list[tuple[Subject, float]]:
        if not text.strip() or not candidates:
            return []
        import numpy as np
        from sentence_transformers import SentenceTransformer

        scope = _scope(course, department, semester) if course and department and semester else "__all__"
        loaded = self._load_scope(scope)
        if loaded is None:
            return []
        if self._model is None:
            model_path = self.directory / "embedding_model"
            if not model_path.exists():
                raise RuntimeError("Local embedding model is missing; rebuild the semantic index")
            self._model = SentenceTransformer(str(model_path), local_files_only=True)
        index, keys = loaded
        if text not in self._query_cache:
            self._query_cache[text] = np.asarray(self._model.encode(
                [text], normalize_embeddings=True, convert_to_numpy=True,
                show_progress_bar=False), dtype="float32")
        query = self._query_cache[text]
        scores, positions = index.search(np.ascontiguousarray(query), index.ntotal)
        allowed = {self.catalog.key_for(subject) for subject in candidates}
        best: dict[str, float] = {}
        for score, position in zip(scores[0], positions[0]):
            if position < 0:
                continue
            key = keys[int(position)]
            if key in allowed:
                best[key] = max(float(score), best.get(key, -1.0))
        ranked = sorted(best.items(), key=lambda pair: pair[1], reverse=True)[:top_k]
        return [(self.catalog.by_key[key], score) for key, score in ranked]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local FAISS subject index from a saved catalog")
    parser.add_argument("build", choices=["build"])
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--aliases", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/subject_index"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision")
    args = parser.parse_args()
    catalog = Catalog.from_file(args.catalog, args.aliases)
    result = SemanticIndex.build(catalog, args.output, args.model, args.revision)
    print(f"Indexed {len(catalog.subjects)} subjects in {len(result.manifest['scopes']) - 1} contexts at {args.output}")


if __name__ == "__main__":
    main()
