from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from open_novel.core.project import ProjectService
from open_novel.core.text_support import important_terms, text_supports_claim


class KnowledgeChunk(BaseModel):
    id: str
    source: str
    title: str = ""
    text: str
    terms: list[str] = Field(default_factory=list)
    contentHash: str = ""
    chapterIds: list[str] = Field(default_factory=list)
    characterIds: list[str] = Field(default_factory=list)
    timeScopes: list[str] = Field(default_factory=list)


class KnowledgeIndex(BaseModel):
    schemaVersion: int = 1
    chunks: list[KnowledgeChunk] = Field(default_factory=list)


class KnowledgeSearchResult(BaseModel):
    id: str
    source: str
    title: str = ""
    excerpt: str
    score: int
    matchedTerms: list[str] = Field(default_factory=list)
    matchReasons: list[str] = Field(default_factory=list)
    enteredContext: bool = False


class KnowledgeBaseService:
    index_path = "knowledge/index.json"
    sources_dir = "knowledge/sources"
    chunks_dir = "knowledge/chunks"

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def read_index(self, root: Path) -> KnowledgeIndex:
        if not self.project_service.file_exists(root, self.index_path):
            return KnowledgeIndex()
        return KnowledgeIndex.model_validate_json(
            self.project_service.read_text(root, self.index_path)
        )

    def rebuild_index(self, root: Path) -> KnowledgeIndex:
        chunks: list[KnowledgeChunk] = []
        seen_hashes: set[str] = set()
        source_paths = [
            path
            for path in self.project_service.list_paths(root, self.sources_dir)
            if Path(path).suffix.lower() in {".md", ".txt"}
        ]
        for relative_source in source_paths:
            text = self.project_service.read_text(root, relative_source)
            for chunk in self._chunks_from_source(relative_source, text):
                if chunk.contentHash in seen_hashes:
                    continue
                seen_hashes.add(chunk.contentHash)
                chunks.append(chunk)

        index = KnowledgeIndex(chunks=chunks)
        self.project_service.write_text(
            root,
            self.index_path,
            json.dumps(index.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        self._write_chunk_files(root, index)
        return index

    def search(
        self,
        root: Path,
        terms: set[str],
        limit: int = 4,
        auto_rebuild: bool = True,
        source: str = "",
        chapter_id: str = "",
        character_id: str = "",
        time_scope: str = "",
    ) -> list[KnowledgeSearchResult]:
        index = self.read_index(root)
        if (
            auto_rebuild
            and not index.chunks
            and self.project_service.list_paths(root, self.sources_dir)
        ):
            index = self.rebuild_index(root)

        normalized_terms = {term for term in terms if len(term) >= 2}
        if not normalized_terms:
            return []

        decorated: list[tuple[int, int, KnowledgeSearchResult]] = []
        for index_number, chunk in enumerate(index.chunks):
            if source and source not in chunk.source:
                continue
            if chapter_id and chapter_id not in chunk.chapterIds:
                continue
            if character_id and character_id not in chunk.characterIds:
                continue
            if time_scope and time_scope not in chunk.timeScopes:
                continue
            score, matched = self._score_chunk(chunk, normalized_terms)
            if score <= 0:
                continue
            decorated.append(
                (
                    score,
                    index_number,
                    KnowledgeSearchResult(
                        id=chunk.id,
                        source=chunk.source,
                        title=chunk.title,
                        excerpt=chunk.text[:1200],
                        score=score,
                        matchedTerms=matched,
                        matchReasons=self._match_reasons(
                            chunk,
                            matched,
                            source=source,
                            chapter_id=chapter_id,
                            character_id=character_id,
                            time_scope=time_scope,
                        ),
                    ),
                )
            )
        decorated.sort(key=lambda item: (-item[0], item[1]))
        return [result for _, _, result in decorated[: max(0, limit)]]

    def context_data(self, root: Path, terms: set[str], limit: int = 4) -> dict[str, Any]:
        results = self.search(root, terms, limit=limit)
        return {
            "schemaVersion": 1,
            "results": [
                {
                    **result.model_dump(mode="json"),
                    "enteredContext": True,
                    "_contextPriority": {
                        "score": min(100, result.score),
                        "reasons": ["knowledge_match", *result.matchReasons],
                    },
                }
                for result in results
            ],
        }

    def _chunks_from_source(self, source: str, text: str) -> list[KnowledgeChunk]:
        title = self._title_from_text(source, text)
        blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
        merged: list[str] = []
        current = ""
        for block in blocks:
            candidate = f"{current}\n\n{block}".strip() if current else block
            if len(candidate) <= 1400:
                current = candidate
                continue
            if current:
                merged.append(current)
            current = block
        if current:
            merged.append(current)

        chunks: list[KnowledgeChunk] = []
        for index, chunk_text in enumerate(merged):
            chunk_id = f"{self._safe_id(source)}-{index + 1:03d}"
            terms = sorted(set(important_terms(chunk_text)))
            metadata = self._metadata(source, chunk_text)
            chunks.append(
                KnowledgeChunk(
                    id=chunk_id,
                    source=source,
                    title=title,
                    text=chunk_text,
                    terms=terms,
                    contentHash=hashlib.sha256(
                        "".join(chunk_text.split()).encode("utf-8")
                    ).hexdigest(),
                    **metadata,
                )
            )
        return chunks

    def _write_chunk_files(self, root: Path, index: KnowledgeIndex) -> None:
        for chunk in index.chunks:
            self.project_service.write_text(
                root,
                f"{self.chunks_dir}/{chunk.id}.json",
                json.dumps(chunk.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            )

    def _score_chunk(self, chunk: KnowledgeChunk, terms: set[str]) -> tuple[int, list[str]]:
        body = json.dumps(chunk.model_dump(mode="json"), ensure_ascii=False)
        matched = sorted(term for term in terms if term in body or text_supports_claim(body, term))
        if not matched:
            return 0, []
        exact_hits = sum(1 for term in matched if term in chunk.terms or term in chunk.text)
        score = min(100, len(matched) * 10 + exact_hits * 5)
        return score, matched[:12]

    def _metadata(self, source: str, text: str) -> dict[str, list[str]]:
        chapter_ids = sorted(set(re.findall(r"(?:chapter:|第\s*)(\d{1,4})(?:\s*章)?", text, re.I)))
        character_ids = sorted(
            set(re.findall(r"(?:character:|人物[:：])\s*([\w\u4e00-\u9fff-]{2,40})", text, re.I))
        )
        time_scopes = sorted(
            set(re.findall(r"(?:time:|时间[:：])\s*([^\n，,。；;]{2,40})", text, re.I))
        )
        source_chapter = re.search(r"(?:chapter-|chapters/)(\d{1,4})", source, re.I)
        if source_chapter:
            chapter_ids.append(source_chapter.group(1).zfill(3))
        return {
            "chapterIds": sorted(set(item.zfill(3) for item in chapter_ids)),
            "characterIds": character_ids,
            "timeScopes": time_scopes,
        }

    def _match_reasons(
        self,
        chunk: KnowledgeChunk,
        matched: list[str],
        *,
        source: str,
        chapter_id: str,
        character_id: str,
        time_scope: str,
    ) -> list[str]:
        reasons = [f"命中关键词：{term}" for term in matched[:3]]
        if source:
            reasons.append("来源范围匹配")
        if chapter_id:
            reasons.append(f"章节范围匹配：{chapter_id}")
        if character_id:
            reasons.append(f"人物范围匹配：{character_id}")
        if time_scope:
            reasons.append(f"时间范围匹配：{time_scope}")
        return reasons

    def _title_from_text(self, source: str, text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
            if stripped:
                return stripped[:80]
        return Path(source).stem

    def _safe_id(self, value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-").lower()
        return safe or "knowledge"
