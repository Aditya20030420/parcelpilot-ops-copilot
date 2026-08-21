"""PDF ingestion + lexical (BM25) retrieval over the document pack.

Design choices:
- BM25 (not vector embeddings). The corpus is small (~6 policy/contract PDFs) and the
  queries are keyword-heavy ("cancellation fee", "service credit", account names). BM25
  is dependency-light, deterministic, needs no embedding API, and is easy to explain.
  A vector store is a natural upgrade once the corpus grows (see product note).
- Every chunk carries its source's authority metadata so results can be ranked by trust
  and the agent can cite where an answer came from.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader
from rank_bm25 import BM25Okapi

from .registry import DocMeta, meta_for_filename


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    tier: str
    authority: int
    status: str
    customer_scope: str | None
    page: int
    text: str


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float  # BM25 relevance blended with a small authority prior


_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _split_page(text: str, max_chars: int = 900) -> list[str]:
    """Split a page into paragraph-ish chunks, keeping them under max_chars."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            # A single huge paragraph gets hard-wrapped.
            while len(p) > max_chars:
                chunks.append(p[:max_chars])
                p = p[max_chars:]
            buf = p
    if buf:
        chunks.append(buf)
    return chunks or ([text.strip()] if text.strip() else [])


class DocumentStore:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self.docs: dict[str, DocMeta] = {}
        self._bm25: BM25Okapi | None = None
        self._corpus_tokens: list[list[str]] = []

    def load_dir(self, data_dir: Path) -> None:
        pdfs = sorted(data_dir.glob("*.pdf"))
        for pdf in pdfs:
            self._load_pdf(pdf)
        self._build_index()

    def _load_pdf(self, path: Path) -> None:
        meta = meta_for_filename(path.stem)
        self.docs[meta.doc_id] = meta
        try:
            reader = PdfReader(str(path))
        except Exception as exc:  # noqa: BLE001 - corrupt/locked PDF shouldn't crash startup
            print(f"[ingest] failed to read {path.name}: {exc}")
            return
        for page_no, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            for i, piece in enumerate(_split_page(text)):
                self.chunks.append(
                    Chunk(
                        chunk_id=f"{meta.doc_id}#p{page_no}-{i}",
                        doc_id=meta.doc_id,
                        title=meta.title,
                        tier=meta.tier,
                        authority=meta.authority,
                        status=meta.status,
                        customer_scope=meta.customer_scope,
                        page=page_no,
                        text=piece,
                    )
                )

    def _build_index(self) -> None:
        self._corpus_tokens = [_tokenize(c.text) for c in self.chunks]
        if self._corpus_tokens:
            self._bm25 = BM25Okapi(self._corpus_tokens)

    @property
    def ready(self) -> bool:
        return self._bm25 is not None and bool(self.chunks)

    def search(
        self,
        query: str,
        top_k: int = 5,
        customer: str | None = None,
        include_deprecated: bool = False,
    ) -> list[RetrievedChunk]:
        """Return top chunks ranked by BM25 relevance blended with source authority.

        `customer` scopes contract docs: a customer-specific agreement is only surfaced
        when the query is about that customer, so we never apply Northstar's terms to
        LumenWorks. Deprecated sources are excluded by default.
        """
        if not self.ready:
            return []
        assert self._bm25 is not None
        scores = self._bm25.get_scores(_tokenize(query))
        ranked: list[RetrievedChunk] = []
        for chunk, base in zip(self.chunks, scores):
            if chunk.status == "deprecated" and not include_deprecated:
                continue
            # A customer contract is only relevant to its own account.
            if chunk.customer_scope and customer and chunk.customer_scope.lower() != customer.lower():
                continue
            if chunk.customer_scope and not customer:
                # No customer in context: down-weight contract text so it doesn't
                # masquerade as general policy, but keep it retrievable.
                base *= 0.4
            # Authority prior: small, additive nudge so that when two chunks are
            # comparably relevant, the more authoritative source ranks higher.
            blended = float(base) + (chunk.authority / 50.0) * 0.75
            if base <= 0 and not (chunk.customer_scope and customer):
                continue
            ranked.append(RetrievedChunk(chunk=chunk, score=blended))
        ranked.sort(key=lambda r: r.score, reverse=True)
        return ranked[:top_k]

    def stats(self) -> dict:
        return {
            "documents": [
                {"doc_id": m.doc_id, "title": m.title, "tier": m.tier,
                 "status": m.status, "customer_scope": m.customer_scope}
                for m in self.docs.values()
            ],
            "chunks": len(self.chunks),
        }
