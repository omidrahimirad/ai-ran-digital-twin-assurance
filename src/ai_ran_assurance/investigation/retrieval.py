"""Small deterministic lexical retrieval for project-created engineering knowledge."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer

from ai_ran_assurance.investigation.models import RetrievedKnowledge


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    source_path: str
    heading: str
    text: str


def _chunk_id(source_path: str, heading: str, index: int, text: str) -> str:
    material = f"{source_path}\n{heading}\n{index}\n{text}".encode()
    return f"kb-{hashlib.sha256(material).hexdigest()[:12]}"


def chunk_markdown(text: str, source_path: str) -> list[KnowledgeChunk]:
    """Split Markdown at headings with stable IDs and deterministic source ordering."""
    chunks: list[KnowledgeChunk] = []
    heading = "Document"
    body: list[str] = []

    def append_chunk() -> None:
        content = "\n".join(body).strip()
        if not content:
            return
        index = len(chunks)
        chunks.append(
            KnowledgeChunk(
                chunk_id=_chunk_id(source_path, heading, index, content),
                source_path=source_path,
                heading=heading,
                text=content,
            )
        )

    for raw_line in text.splitlines():
        match = re.match(r"^#{1,3}\s+(.+?)\s*$", raw_line)
        if match:
            append_chunk()
            heading = match.group(1)
            body = []
        else:
            body.append(raw_line)
    append_chunk()
    return chunks


def load_knowledge(paths: list[Path], *, source_root: Path | None = None) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for path in sorted(paths, key=lambda item: item.as_posix()):
        root = source_root or path.parent
        try:
            source_path = path.relative_to(root).as_posix()
        except ValueError:
            source_path = path.name
        chunks.extend(chunk_markdown(path.read_text(encoding="utf-8"), source_path))
    return chunks


class LexicalRetriever:
    """Deterministic TF-IDF retrieval with no external service or hidden state."""

    def __init__(self, chunks: list[KnowledgeChunk]) -> None:
        self._chunks = sorted(chunks, key=lambda item: item.chunk_id)

    @classmethod
    def from_paths(cls, paths: list[Path], *, source_root: Path | None = None) -> LexicalRetriever:
        return cls(load_knowledge(paths, source_root=source_root))

    def retrieve(self, query: str, *, top_k: int) -> list[RetrievedKnowledge]:
        if top_k < 0 or top_k > 12:
            raise ValueError("top_k must be between 0 and 12")
        cleaned = query.strip()
        if not cleaned or not self._chunks or top_k == 0:
            return []
        documents = [f"{item.heading} {item.text}" for item in self._chunks]
        matrix = TfidfVectorizer(lowercase=True, stop_words="english").fit_transform(
            documents + [cleaned]
        )
        scores = (matrix[:-1] @ matrix[-1].T).toarray().ravel()
        ranked = sorted(
            (
                (float(score), chunk)
                for score, chunk in zip(scores, self._chunks, strict=True)
                if score > 0
            ),
            key=lambda pair: (-pair[0], pair[1].chunk_id),
        )[:top_k]
        return [
            RetrievedKnowledge(
                chunk_id=chunk.chunk_id,
                source_path=chunk.source_path,
                heading=chunk.heading,
                text=chunk.text,
                relevance_score=round(min(score, 1.0), 6),
            )
            for score, chunk in ranked
        ]
