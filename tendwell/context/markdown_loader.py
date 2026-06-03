"""MarkdownContextLoader: load a directory of markdown into Documents.

Chunks each file with a configurable character window and overlap, attaches the
nearest preceding heading for citation context, and assigns stable ids so
re-indexing updates in place rather than duplicating.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from tendwell.interfaces.context_store import ContextLoader, Document

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


class MarkdownContextLoader(ContextLoader):
    """A ``ContextLoader`` that reads ``*.md`` files from a directory tree."""

    type = "markdown"

    def __init__(
        self,
        path: str,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
    ) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self._root = Path(path)
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def _headings(self, text: str) -> list[tuple[int, str]]:
        return [(m.start(), m.group(2).strip()) for m in _HEADING.finditer(text)]

    def _heading_for(self, headings: list[tuple[int, str]], offset: int) -> str | None:
        current: str | None = None
        for pos, title in headings:
            if pos <= offset:
                current = title
            else:
                break
        return current

    def _chunk_file(self, text: str, source: str) -> list[Document]:
        headings = self._headings(text)
        step = self._chunk_size - self._chunk_overlap
        documents: list[Document] = []
        index = 0
        start = 0
        length = len(text)
        while start < length:
            window = text[start : start + self._chunk_size]
            if window.strip():
                heading = self._heading_for(headings, start)
                metadata: dict[str, object] = {"path": source}
                if heading is not None:
                    metadata["heading"] = heading
                documents.append(
                    Document(
                        id=f"{source}::{index}",
                        text=window.strip(),
                        source=source,
                        metadata=metadata,
                    )
                )
                index += 1
            start += step
        return documents

    async def load(self) -> Sequence[Document]:
        if not self._root.is_dir():
            raise FileNotFoundError(f"knowledge directory not found: {self._root}")
        documents: list[Document] = []
        for path in sorted(self._root.rglob("*.md")):
            relative = path.relative_to(self._root).as_posix()
            documents.extend(self._chunk_file(path.read_text(encoding="utf-8"), relative))
        return documents
