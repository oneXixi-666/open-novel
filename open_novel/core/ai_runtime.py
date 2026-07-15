from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import threading
import time
from collections.abc import AsyncIterator
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

import httpx

from open_novel.core.workspace_registry import WorkspaceRegistryService

AIProtocol = Literal["responses", "chat_completions"]
AIRole = Literal["writing", "review"]


class SecretStore(Protocol):
    def get(self, reference: str) -> str: ...

    def set(self, reference: str, secret: str) -> None: ...

    def delete(self, reference: str) -> None: ...


class LocalSecretStore:
    """Store secrets in the local workspace database without exposing them via APIs."""

    service_name = "open-novel-ai"

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()
        self.fallback_path = db_path.with_name("open-novel-ai-secrets.json")
        self._ensure_schema()
        self._migrate_fallback_file()

    def get(self, reference: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT secret FROM ai_secrets WHERE reference = ?",
                (reference,),
            ).fetchone()
        if row is not None:
            return str(row["secret"] or "")
        secret = self._legacy_secret(reference)
        if secret:
            self.set(reference, secret)
            self._delete_legacy_secret(reference)
        return secret

    def set(self, reference: str, secret: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_secrets (reference, secret, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(reference) DO UPDATE SET
                    secret = excluded.secret,
                    updated_at = excluded.updated_at
                """,
                (reference, secret, datetime.now(UTC).isoformat()),
            )
        self._delete_legacy_secret(reference)

    def delete(self, reference: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM ai_secrets WHERE reference = ?", (reference,))
        self._delete_legacy_secret(reference)

    def _legacy_secret(self, reference: str) -> str:
        keyring = self._keyring()
        if keyring is not None:
            try:
                return str(keyring.get_password(self.service_name, reference) or "")
            except Exception:
                pass
        return str(self._read_fallback().get(reference) or "")

    def _delete_legacy_secret(self, reference: str) -> None:
        keyring = self._keyring()
        if keyring is not None:
            try:
                keyring.delete_password(self.service_name, reference)
            except Exception:
                pass
        self._delete_fallback_key(reference)

    def _keyring(self) -> Any | None:
        try:
            import keyring  # type: ignore[import-not-found]
        except ImportError:
            return None
        return keyring

    def _read_fallback(self) -> dict[str, str]:
        if not self.fallback_path.is_file():
            return {}
        try:
            payload = json.loads(self.fallback_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return (
            {str(key): str(value) for key, value in payload.items()}
            if isinstance(payload, dict)
            else {}
        )

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_secrets (
                    reference TEXT PRIMARY KEY,
                    secret TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _migrate_fallback_file(self) -> None:
        if not self.fallback_path.is_file():
            return
        values = self._read_fallback()
        if values:
            now = datetime.now(UTC).isoformat()
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO ai_secrets (reference, secret, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(reference) DO UPDATE SET
                        secret = excluded.secret,
                        updated_at = excluded.updated_at
                    """,
                    [(reference, secret, now) for reference, secret in values.items()],
                )
        self.fallback_path.unlink(missing_ok=True)

    def _delete_fallback_key(self, reference: str) -> None:
        values = self._read_fallback()
        if not self.fallback_path.is_file():
            return
        values.pop(reference, None)
        if values:
            now = datetime.now(UTC).isoformat()
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO ai_secrets (reference, secret, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(reference) DO UPDATE SET
                        secret = excluded.secret,
                        updated_at = excluded.updated_at
                    """,
                    [(item_ref, secret, now) for item_ref, secret in values.items()],
                )
        self.fallback_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class AIAccount:
    id: str
    name: str
    purpose: str
    base_url: str
    model: str
    protocol: AIProtocol
    max_context_tokens: int
    enabled: bool
    secret_ref: str
    updated_at: str

    def public_payload(self, has_api_key: bool) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "purpose": self.purpose,
            "baseUrl": self.base_url,
            "model": self.model,
            "protocol": self.protocol,
            "maxContextTokens": self.max_context_tokens,
            "enabled": self.enabled,
            "hasApiKey": has_api_key,
            "updatedAt": self.updated_at,
        }


@dataclass
class AIUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    source: str = "unavailable"

    def normalize(self) -> AIUsage:
        self.input_tokens = max(0, int(self.input_tokens))
        self.output_tokens = max(0, int(self.output_tokens))
        self.total_tokens = max(
            int(self.total_tokens),
            self.input_tokens + self.output_tokens,
        )
        self.cached_input_tokens = max(0, int(self.cached_input_tokens))
        self.reasoning_tokens = max(0, int(self.reasoning_tokens))
        return self

    def payload(self) -> dict[str, Any]:
        self.normalize()
        return {
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "totalTokens": self.total_tokens,
            "cachedInputTokens": self.cached_input_tokens,
            "reasoningTokens": self.reasoning_tokens,
            "source": self.source,
        }


@dataclass
class AICompletionResult:
    text: str
    usage: AIUsage
    account: AIAccount
    request_id: str
    cache_hit: bool = False
    compressed: bool = False
    original_estimated_tokens: int = 0
    sent_estimated_tokens: int = 0


@dataclass(frozen=True)
class AIStreamEvent:
    event: Literal["status", "token", "usage", "done", "error"]
    data: dict[str, Any]


@dataclass(frozen=True)
class CompressedPrompt:
    text: str
    original_tokens: int
    sent_tokens: int
    compressed: bool
    fingerprint: str


class AIAccountRepository:
    cache_ttl = timedelta(hours=24)

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = (db_path or WorkspaceRegistryService.default_registry_path()).resolve()
        self._ensure_schema()

    def list_accounts(self) -> list[AIAccount]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_accounts ORDER BY updated_at DESC, account_id ASC"
            ).fetchall()
        return [self._account_from_row(row) for row in rows]

    def get_account(self, account_id: str) -> AIAccount:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ai_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(account_id)
        return self._account_from_row(row)

    def save_account(
        self,
        *,
        account_id: str,
        name: str,
        purpose: str,
        base_url: str,
        model: str,
        protocol: AIProtocol,
        max_context_tokens: int,
        enabled: bool,
        secret_ref: str,
    ) -> AIAccount:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_accounts (
                    account_id, name, purpose, base_url, model, protocol,
                    max_context_tokens, enabled, secret_ref, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    name = excluded.name,
                    purpose = excluded.purpose,
                    base_url = excluded.base_url,
                    model = excluded.model,
                    protocol = excluded.protocol,
                    max_context_tokens = excluded.max_context_tokens,
                    enabled = excluded.enabled,
                    secret_ref = excluded.secret_ref,
                    updated_at = excluded.updated_at
                """,
                (
                    account_id,
                    name,
                    purpose,
                    base_url,
                    model,
                    protocol,
                    max_context_tokens,
                    int(enabled),
                    secret_ref,
                    now,
                    now,
                ),
            )
        return self.get_account(account_id)

    def delete_account(self, account_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM ai_role_bindings WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM ai_accounts WHERE account_id = ?", (account_id,))

    def bindings(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, account_id FROM ai_role_bindings ORDER BY role ASC"
            ).fetchall()
        return {str(row["role"]): str(row["account_id"]) for row in rows}

    def bind_role(self, role: AIRole, account_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_role_bindings (role, account_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(role) DO UPDATE SET
                    account_id = excluded.account_id,
                    updated_at = excluded.updated_at
                """,
                (role, account_id, datetime.now(UTC).isoformat()),
            )

    def unbind_role(self, role: AIRole) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM ai_role_bindings WHERE role = ?", (role,))

    def account_for_role(self, role: AIRole) -> AIAccount:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT a.* FROM ai_role_bindings b
                JOIN ai_accounts a ON a.account_id = b.account_id
                WHERE b.role = ? AND a.enabled = 1
                """,
                (role,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(role)
        return self._account_from_row(row)

    def read_context_cache(self, cache_key: str) -> CompressedPrompt | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ai_context_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        return CompressedPrompt(
            text=str(row["prompt_text"] or ""),
            original_tokens=int(row["original_tokens"] or 0),
            sent_tokens=int(row["sent_tokens"] or 0),
            compressed=bool(row["compressed"]),
            fingerprint=str(row["fingerprint"] or ""),
        )

    def write_context_cache(self, cache_key: str, prompt: CompressedPrompt) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_context_cache (
                    cache_key, fingerprint, prompt_text, original_tokens,
                    sent_tokens, compressed, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    prompt_text = excluded.prompt_text,
                    original_tokens = excluded.original_tokens,
                    sent_tokens = excluded.sent_tokens,
                    compressed = excluded.compressed,
                    updated_at = excluded.updated_at
                """,
                (
                    cache_key,
                    prompt.fingerprint,
                    prompt.text,
                    prompt.original_tokens,
                    prompt.sent_tokens,
                    int(prompt.compressed),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def read_result_cache(self, cache_key: str) -> tuple[str, AIUsage] | None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT response_text, usage_json FROM ai_result_cache
                WHERE cache_key = ? AND expires_at > ?
                """,
                (cache_key, now),
            ).fetchone()
        if row is None:
            return None
        usage = self._usage_from_json(str(row["usage_json"] or "{}"))
        return str(row["response_text"] or ""), usage

    def write_result_cache(self, cache_key: str, text: str, usage: AIUsage) -> None:
        now = datetime.now(UTC)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_result_cache (
                    cache_key, response_text, usage_json, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    response_text = excluded.response_text,
                    usage_json = excluded.usage_json,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (
                    cache_key,
                    text,
                    json.dumps(usage.payload(), ensure_ascii=False),
                    now.isoformat(),
                    (now + self.cache_ttl).isoformat(),
                ),
            )

    def record_usage(
        self,
        *,
        request_id: str,
        root: str,
        role: AIRole,
        action: str,
        account: AIAccount,
        status: str,
        usage: AIUsage,
        cache_hit: bool,
        latency_ms: int,
        error: str = "",
        compressed: bool = False,
        original_estimated_tokens: int = 0,
        sent_estimated_tokens: int = 0,
    ) -> None:
        normalized = usage.normalize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_usage_events (
                    request_id, root, role, action, account_id, model, protocol,
                    status, cache_hit, input_tokens, output_tokens, total_tokens,
                    cached_input_tokens, reasoning_tokens, usage_source, latency_ms,
                    error, compressed, original_estimated_tokens,
                    sent_estimated_tokens, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    root,
                    role,
                    action,
                    account.id,
                    account.model,
                    account.protocol,
                    status,
                    int(cache_hit),
                    normalized.input_tokens,
                    normalized.output_tokens,
                    normalized.total_tokens,
                    normalized.cached_input_tokens,
                    normalized.reasoning_tokens,
                    normalized.source,
                    max(0, int(latency_ms)),
                    error[:1000],
                    int(compressed),
                    max(0, int(original_estimated_tokens)),
                    max(0, int(sent_estimated_tokens)),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def usage_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ai_usage_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "requestId": str(row["request_id"]),
                "bookId": str(row["root"] or ""),
                "role": str(row["role"]),
                "action": str(row["action"]),
                "accountId": str(row["account_id"]),
                "model": str(row["model"]),
                "protocol": str(row["protocol"]),
                "status": str(row["status"]),
                "cacheHit": bool(row["cache_hit"]),
                "inputTokens": int(row["input_tokens"] or 0),
                "outputTokens": int(row["output_tokens"] or 0),
                "totalTokens": int(row["total_tokens"] or 0),
                "cachedInputTokens": int(row["cached_input_tokens"] or 0),
                "reasoningTokens": int(row["reasoning_tokens"] or 0),
                "usageSource": str(row["usage_source"] or "estimated"),
                "latencyMs": int(row["latency_ms"] or 0),
                "error": str(row["error"] or ""),
                "compressed": bool(row["compressed"]),
                "originalEstimatedTokens": int(row["original_estimated_tokens"] or 0),
                "sentEstimatedTokens": int(row["sent_estimated_tokens"] or 0),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    def usage_summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS call_count,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
                       COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                       COALESCE(SUM(cache_hit), 0) AS cache_hits
                FROM ai_usage_events
                """
            ).fetchone()
        return {
            "callCount": int(row["call_count"] or 0),
            "totalTokens": int(row["total_tokens"] or 0),
            "inputTokens": int(row["input_tokens"] or 0),
            "outputTokens": int(row["output_tokens"] or 0),
            "cachedInputTokens": int(row["cached_input_tokens"] or 0),
            "reasoningTokens": int(row["reasoning_tokens"] or 0),
            "cacheHits": int(row["cache_hits"] or 0),
        }

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_accounts (
                    account_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    purpose TEXT NOT NULL DEFAULT '',
                    base_url TEXT NOT NULL,
                    model TEXT NOT NULL,
                    protocol TEXT NOT NULL CHECK(protocol IN ('responses','chat_completions')),
                    max_context_tokens INTEGER NOT NULL DEFAULT 32768,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    secret_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            account_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(ai_accounts)").fetchall()
            }
            if "purpose" not in account_columns:
                try:
                    conn.execute(
                        "ALTER TABLE ai_accounts "
                        "ADD COLUMN purpose TEXT NOT NULL DEFAULT ''"
                    )
                except sqlite3.OperationalError as exc:
                    if "duplicate column name: purpose" not in str(exc).lower():
                        raise
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_role_bindings (
                    role TEXT PRIMARY KEY CHECK(role IN ('writing','review')),
                    account_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES ai_accounts(account_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_secrets (
                    reference TEXT PRIMARY KEY,
                    secret TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    root TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT '',
                    account_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    cache_hit INTEGER NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
                    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                    usage_source TEXT NOT NULL DEFAULT 'unavailable',
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    compressed INTEGER NOT NULL DEFAULT 0,
                    original_estimated_tokens INTEGER NOT NULL DEFAULT 0,
                    sent_estimated_tokens INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_context_cache (
                    cache_key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    prompt_text TEXT NOT NULL,
                    original_tokens INTEGER NOT NULL,
                    sent_tokens INTEGER NOT NULL,
                    compressed INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_result_cache (
                    cache_key TEXT PRIMARY KEY,
                    response_text TEXT NOT NULL,
                    usage_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_usage_created_at "
                "ON ai_usage_events(created_at DESC)"
            )

    def _account_from_row(self, row: sqlite3.Row) -> AIAccount:
        return AIAccount(
            id=str(row["account_id"]),
            name=str(row["name"]),
            purpose=str(row["purpose"] or ""),
            base_url=str(row["base_url"]),
            model=str(row["model"]),
            protocol=str(row["protocol"]),  # type: ignore[arg-type]
            max_context_tokens=int(row["max_context_tokens"] or 32768),
            enabled=bool(row["enabled"]),
            secret_ref=str(row["secret_ref"]),
            updated_at=str(row["updated_at"]),
        )

    def _usage_from_json(self, text: str) -> AIUsage:
        try:
            value = json.loads(text)
        except ValueError:
            value = {}
        return AIUsage(
            input_tokens=int(value.get("inputTokens") or 0),
            output_tokens=int(value.get("outputTokens") or 0),
            total_tokens=int(value.get("totalTokens") or 0),
            cached_input_tokens=int(value.get("cachedInputTokens") or 0),
            reasoning_tokens=int(value.get("reasoningTokens") or 0),
            source=str(value.get("source") or "unavailable"),
        )


class PromptCompressor:
    prompt_version = "workbench-v1"

    def __init__(self, repository: AIAccountRepository) -> None:
        self.repository = repository

    def compress(self, prompt: str, max_context_tokens: int) -> CompressedPrompt:
        limit = max(2048, int(max_context_tokens))
        output_reserve = max(512, min(8192, limit // 5))
        input_budget = max(1024, limit - output_reserve)
        fingerprint = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        cache_key = hashlib.sha256(
            f"{self.prompt_version}:{fingerprint}:{limit}".encode()
        ).hexdigest()
        cached = self.repository.read_context_cache(cache_key)
        if cached is not None:
            return cached
        original_tokens = estimate_tokens(prompt)
        if original_tokens <= input_budget:
            result = CompressedPrompt(
                text=prompt,
                original_tokens=original_tokens,
                sent_tokens=original_tokens,
                compressed=False,
                fingerprint=fingerprint,
            )
            self.repository.write_context_cache(cache_key, result)
            return result

        paragraphs = [item.strip() for item in re.split(r"\n{2,}", prompt) if item.strip()]
        unique: list[tuple[int, str]] = []
        seen: set[str] = set()
        for index, paragraph in enumerate(paragraphs):
            normalized = re.sub(r"\s+", "", paragraph).lower()
            key = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            unique.append((index, paragraph))

        selected: dict[int, str] = {}
        mandatory_indexes = {
            *[index for index, _ in unique[:3]],
            *[index for index, _ in unique[-8:]],
        }
        for index, paragraph in unique:
            if index in mandatory_indexes:
                selected[index] = paragraph

        candidates = sorted(
            (
                (self._priority(paragraph, index, len(paragraphs)), index, paragraph)
                for index, paragraph in unique
                if index not in mandatory_indexes
            ),
            reverse=True,
        )
        for _, index, paragraph in candidates:
            candidate_text = self._join(selected | {index: paragraph})
            if estimate_tokens(candidate_text) <= input_budget:
                selected[index] = paragraph

        compressed_text = self._join(selected)
        if estimate_tokens(compressed_text) > input_budget:
            compressed_text = self._truncate_to_budget(compressed_text, input_budget)
        result = CompressedPrompt(
            text=compressed_text,
            original_tokens=original_tokens,
            sent_tokens=estimate_tokens(compressed_text),
            compressed=True,
            fingerprint=fingerprint,
        )
        self.repository.write_context_cache(cache_key, result)
        return result

    def _priority(self, paragraph: str, index: int, total: int) -> int:
        score = index
        keywords = [
            "当前",
            "chapter",
            "章节",
            "合同",
            "草稿",
            "审稿",
            "任务上下文",
            "activeprohibitions",
            "readerpromises",
            "mustavoid",
        ]
        lowered = paragraph.lower()
        score += sum(1000 for keyword in keywords if keyword in lowered)
        if paragraph.startswith("#"):
            score += 500
        if index >= max(0, total - 12):
            score += 2000
        return score

    def _join(self, selected: dict[int, str]) -> str:
        return "\n\n".join(value for _, value in sorted(selected.items())).strip()

    def _truncate_to_budget(self, text: str, input_budget: int) -> str:
        marker = "\n\n[中间历史上下文已按账号上限压缩]\n\n"
        low = 0
        high = len(text)
        best = marker.strip()
        while low <= high:
            retained = (low + high) // 2
            head_size = retained // 3
            tail_size = retained - head_size
            candidate = text[:head_size].rstrip() + marker
            if tail_size:
                candidate += text[-tail_size:].lstrip()
            if estimate_tokens(candidate) <= input_budget:
                best = candidate
                low = retained + 1
            else:
                high = retained - 1
        return best


_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT: dict[str, Future[AICompletionResult]] = {}


class AIRuntimeService:
    def __init__(
        self,
        repository: AIAccountRepository | None = None,
        secret_store: SecretStore | None = None,
        *,
        timeout_seconds: int = 300,
    ) -> None:
        self.repository = repository or AIAccountRepository()
        self.secret_store = secret_store or LocalSecretStore(self.repository.db_path)
        self.compressor = PromptCompressor(self.repository)
        self.timeout_seconds = max(1, int(timeout_seconds))

    def settings(self) -> dict[str, Any]:
        accounts = self.repository.list_accounts()
        bindings = self.repository.bindings()
        return {
            "accounts": [
                account.public_payload(bool(self.secret_store.get(account.secret_ref)))
                for account in accounts
            ],
            "roles": {
                "writingAccountId": bindings.get("writing", ""),
                "reviewAccountId": bindings.get("review", ""),
            },
            "usageSummary": self.repository.usage_summary(),
            "usageEvents": self.repository.usage_events(limit=100),
        }

    def save_account(
        self,
        *,
        account_id: str = "",
        name: str,
        purpose: str = "",
        base_url: str,
        model: str,
        protocol: AIProtocol,
        max_context_tokens: int,
        enabled: bool,
        api_key: str | None,
    ) -> dict[str, Any]:
        normalized_id = account_id.strip() or f"account-{uuid4().hex[:12]}"
        if not name.strip():
            raise ValueError("账号名称不能为空。")
        if not base_url.strip():
            raise ValueError("Base URL 不能为空。")
        if not model.strip():
            raise ValueError("模型名称不能为空。")
        secret_ref = f"ai-account:{normalized_id}"
        if api_key is not None:
            self.secret_store.set(secret_ref, api_key.strip())
        account = self.repository.save_account(
            account_id=normalized_id,
            name=name.strip(),
            purpose=purpose.strip(),
            base_url=base_url.strip().rstrip("/"),
            model=model.strip(),
            protocol=protocol,
            max_context_tokens=max(2048, min(int(max_context_tokens), 2_000_000)),
            enabled=enabled,
            secret_ref=secret_ref,
        )
        return account.public_payload(bool(self.secret_store.get(secret_ref)))

    def delete_account(self, account_id: str) -> None:
        account = self.repository.get_account(account_id)
        self.repository.delete_account(account_id)
        self.secret_store.delete(account.secret_ref)

    def bind_role(self, role: AIRole, account_id: str) -> dict[str, str]:
        if not account_id.strip():
            self.repository.unbind_role(role)
            return {"role": role, "accountId": ""}
        account = self.repository.get_account(account_id)
        if not account.enabled:
            raise ValueError("账号已停用，不能分配给角色。")
        self.repository.bind_role(role, account.id)
        return {"role": role, "accountId": account.id}

    def bind_roles(self, writing_account_id: str, review_account_id: str) -> None:
        for account_id in {writing_account_id.strip(), review_account_id.strip()} - {""}:
            account = self.repository.get_account(account_id)
            if not account.enabled:
                raise ValueError("账号已停用，不能分配给角色。")
        self.bind_role("writing", writing_account_id)
        self.bind_role("review", review_account_id)

    def account_for_role(self, role: AIRole) -> AIAccount:
        return self.repository.account_for_role(role)

    async def probe(self, account_id: str) -> dict[str, Any]:
        account = self.repository.get_account(account_id)
        return await self._probe_account(account)

    async def probe_configuration(
        self,
        *,
        account_id: str = "",
        base_url: str,
        api_key: str | None,
        model: str,
        protocol: AIProtocol,
        max_context_tokens: int,
    ) -> dict[str, Any]:
        account, temporary_secret_ref = self._configuration_account(
            account_id=account_id,
            base_url=base_url,
            api_key=api_key,
            model=model,
            protocol=protocol,
            max_context_tokens=max_context_tokens,
        )
        try:
            return await self._probe_account(account)
        finally:
            if temporary_secret_ref:
                self.secret_store.delete(temporary_secret_ref)

    async def discover_models(
        self,
        *,
        account_id: str = "",
        base_url: str,
        api_key: str | None,
    ) -> list[str]:
        normalized_base_url = base_url.strip()
        if not normalized_base_url:
            raise ValueError("Base URL 不能为空。")
        resolved_key = self._configuration_api_key(account_id, api_key)
        headers = {
            "Accept": "application/json",
            "User-Agent": "Open-Novel/1.0",
        }
        if resolved_key:
            headers["Authorization"] = f"Bearer {resolved_key}"
            headers["X-API-Key"] = resolved_key
        timeout = httpx.Timeout(min(self.timeout_seconds, 60), connect=20)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                self._models_endpoint(normalized_base_url),
                headers=headers,
            )
        if response.status_code >= 400:
            detail = self._connection_error_detail(
                response.status_code,
                response.text,
                endpoint="/v1/models",
            )
            raise RuntimeError(
                f"模型列表接口返回 {response.status_code}："
                f"{detail}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("模型列表接口没有返回有效 JSON。") from exc
        items = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise RuntimeError("模型列表格式不正确，预期返回 data 数组。")
        models = sorted(
            {
                str(item.get("id") or "").strip()
                for item in items
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            }
        )
        if not models:
            raise RuntimeError("模型列表为空，请检查 Base URL 和 API Key。")
        return models

    async def _probe_account(self, account: AIAccount) -> dict[str, Any]:
        result = await self.complete(
            role="writing",
            prompt="hi",
            root="",
            action="账号拨测",
            bypass_cache=True,
            account_override=account,
        )
        return {
            "accountId": account.id,
            "success": True,
            "text": result.text,
            "usage": result.usage.payload(),
            "latencyMs": self._usage_event_latency(result.request_id),
        }

    def _configuration_account(
        self,
        *,
        account_id: str,
        base_url: str,
        api_key: str | None,
        model: str,
        protocol: AIProtocol,
        max_context_tokens: int,
    ) -> tuple[AIAccount, str]:
        if not base_url.strip():
            raise ValueError("Base URL 不能为空。")
        if not model.strip():
            raise ValueError("请先选择或填写模型名称。")
        temporary_secret_ref = f"ai-probe:{uuid4().hex}"
        resolved_key = self._configuration_api_key(account_id, api_key)
        if resolved_key:
            self.secret_store.set(temporary_secret_ref, resolved_key)
        return (
            AIAccount(
                id=account_id.strip() or f"probe-{uuid4().hex[:12]}",
                name="表单拨测",
                purpose="",
                base_url=base_url.strip().rstrip("/"),
                model=model.strip(),
                protocol=protocol,
                max_context_tokens=max(
                    2048, min(int(max_context_tokens), 2_000_000)
                ),
                enabled=True,
                secret_ref=temporary_secret_ref,
                updated_at=datetime.now(UTC).isoformat(),
            ),
            temporary_secret_ref,
        )

    def _configuration_api_key(
        self,
        account_id: str,
        api_key: str | None,
    ) -> str:
        if api_key is not None and api_key.strip():
            return api_key.strip()
        if not account_id.strip():
            return ""
        account = self.repository.get_account(account_id)
        return self.secret_store.get(account.secret_ref)

    async def complete(
        self,
        *,
        role: AIRole,
        prompt: str,
        root: str,
        action: str,
        bypass_cache: bool = False,
        account_override: AIAccount | None = None,
    ) -> AICompletionResult:
        result: AICompletionResult | None = None
        async for event in self.stream(
            role=role,
            prompt=prompt,
            root=root,
            action=action,
            bypass_cache=bypass_cache,
            account_override=account_override,
        ):
            if event.event == "done":
                result = event.data["result"]
            if event.event == "error":
                raise RuntimeError(str(event.data.get("message") or "AI request failed"))
        if result is None:
            raise RuntimeError("AI request finished without a result")
        return result

    def complete_sync(
        self,
        *,
        role: AIRole,
        prompt: str,
        root: str,
        action: str,
        bypass_cache: bool = False,
    ) -> AICompletionResult:
        return asyncio.run(
            self.complete(
                role=role,
                prompt=prompt,
                root=root,
                action=action,
                bypass_cache=bypass_cache,
            )
        )

    async def stream(
        self,
        *,
        role: AIRole,
        prompt: str,
        root: str,
        action: str,
        bypass_cache: bool = False,
        account_override: AIAccount | None = None,
    ) -> AsyncIterator[AIStreamEvent]:
        account = account_override or self.repository.account_for_role(role)
        compressed = self.compressor.compress(prompt, account.max_context_tokens)
        cache_key = self._result_cache_key(account, role, action, compressed)
        request_id = f"ai-{uuid4().hex}"
        started = time.perf_counter()
        if not bypass_cache:
            cached = self.repository.read_result_cache(cache_key)
            if cached is not None:
                text, _cached_usage = cached
                usage = AIUsage(source="cache")
                self._record(
                    request_id=request_id,
                    root=root,
                    role=role,
                    action=action,
                    account=account,
                    status="cached",
                    usage=usage,
                    cache_hit=True,
                    started=started,
                    compressed=compressed,
                )
                yield AIStreamEvent(
                    "status",
                    {"message": "已使用缓存结果", "accountName": account.name},
                )
                for chunk in self._chunks(text):
                    yield AIStreamEvent("token", {"text": chunk})
                yield AIStreamEvent("usage", usage.payload())
                yield AIStreamEvent(
                    "done",
                    {
                        "result": AICompletionResult(
                            text=text,
                            usage=usage,
                            account=account,
                            request_id=request_id,
                            cache_hit=True,
                            compressed=compressed.compressed,
                            original_estimated_tokens=compressed.original_tokens,
                            sent_estimated_tokens=compressed.sent_tokens,
                        )
                    },
                )
                return

        inflight_key = cache_key if not bypass_cache else f"{cache_key}:{request_id}"
        owner, inflight = self._claim_inflight(inflight_key)
        if not owner:
            try:
                result = await asyncio.wrap_future(inflight)
            except (asyncio.CancelledError, GeneratorExit):
                self._record(
                    request_id=request_id,
                    root=root,
                    role=role,
                    action=action,
                    account=account,
                    status="cancelled",
                    usage=AIUsage(source="unavailable"),
                    cache_hit=False,
                    started=started,
                    error="浏览器已断开，本次等待已取消。",
                    compressed=compressed,
                )
                raise
            except Exception as exc:
                self._record(
                    request_id=request_id,
                    root=root,
                    role=role,
                    action=action,
                    account=account,
                    status="failed",
                    usage=AIUsage(source="unavailable"),
                    cache_hit=False,
                    started=started,
                    error=str(exc),
                    compressed=compressed,
                )
                yield AIStreamEvent("error", {"message": str(exc)})
                return
            usage = AIUsage(source="deduplicated")
            self._record(
                request_id=request_id,
                root=root,
                role=role,
                action=action,
                account=account,
                status="deduplicated",
                usage=usage,
                cache_hit=True,
                started=started,
                compressed=compressed,
            )
            yield AIStreamEvent(
                "status",
                {"message": "已合并重复请求", "accountName": account.name},
            )
            for chunk in self._chunks(result.text):
                yield AIStreamEvent("token", {"text": chunk})
            yield AIStreamEvent("usage", usage.payload())
            yield AIStreamEvent(
                "done",
                {
                    "result": AICompletionResult(
                        text=result.text,
                        usage=usage,
                        account=account,
                        request_id=request_id,
                        cache_hit=True,
                        compressed=compressed.compressed,
                        original_estimated_tokens=compressed.original_tokens,
                        sent_estimated_tokens=compressed.sent_tokens,
                    )
                },
            )
            return

        parts: list[str] = []
        usage = AIUsage(source="unavailable")
        try:
            yield AIStreamEvent(
                "status",
                {
                    "message": "已开始生成",
                    "accountName": account.name,
                    "model": account.model,
                    "protocol": account.protocol,
                    "compressed": compressed.compressed,
                },
            )
            async for kind, payload in self._upstream_events(account, compressed.text):
                if kind == "token":
                    delta = str(payload.get("text") or "")
                    if delta:
                        parts.append(delta)
                        yield AIStreamEvent("token", {"text": delta})
                elif kind == "usage":
                    usage = self._usage_from_payload(payload, account.protocol)
                    yield AIStreamEvent("usage", usage.payload())
            text = "".join(parts).strip()
            if not text:
                raise RuntimeError("上游没有返回可用文本。")
            usage = self._final_usage(usage, compressed.text, text)
            result = AICompletionResult(
                text=text,
                usage=usage.normalize(),
                account=account,
                request_id=request_id,
                compressed=compressed.compressed,
                original_estimated_tokens=compressed.original_tokens,
                sent_estimated_tokens=compressed.sent_tokens,
            )
            self.repository.write_result_cache(cache_key, text, result.usage)
            self._record(
                request_id=request_id,
                root=root,
                role=role,
                action=action,
                account=account,
                status="completed",
                usage=result.usage,
                cache_hit=False,
                started=started,
                compressed=compressed,
            )
            inflight.set_result(result)
            if result.usage.source == "estimated":
                yield AIStreamEvent("usage", result.usage.payload())
            yield AIStreamEvent("done", {"result": result})
        except (asyncio.CancelledError, GeneratorExit):
            error = "浏览器已断开，本次上游请求已取消。"
            usage = self._final_usage(usage, compressed.text, "".join(parts))
            self._record(
                request_id=request_id,
                root=root,
                role=role,
                action=action,
                account=account,
                status="cancelled",
                usage=usage,
                cache_hit=False,
                started=started,
                error=error,
                compressed=compressed,
            )
            inflight.set_exception(RuntimeError(error))
            inflight.exception()
            raise
        except Exception as exc:
            usage = self._final_usage(usage, compressed.text, "".join(parts))
            self._record(
                request_id=request_id,
                root=root,
                role=role,
                action=action,
                account=account,
                status="failed",
                usage=usage,
                cache_hit=False,
                started=started,
                error=str(exc),
                compressed=compressed,
            )
            inflight.set_exception(exc)
            inflight.exception()
            yield AIStreamEvent("error", {"message": str(exc)})
        finally:
            with _INFLIGHT_LOCK:
                if _INFLIGHT.get(inflight_key) is inflight:
                    _INFLIGHT.pop(inflight_key, None)

    async def _upstream_events(
        self,
        account: AIAccount,
        prompt: str,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        url = self._endpoint(account)
        headers = {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
        }
        api_key = self.secret_store.get(account.secret_ref)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["X-API-Key"] = api_key
        body = self._request_body(account, prompt)
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(30, self.timeout_seconds))
        emitted_text = ""

        async def parsed_events(
            parsed_event_name: str,
            parsed_data_text: str,
        ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
            nonlocal emitted_text
            async for kind, payload in self._parse_upstream_event(
                account.protocol,
                parsed_event_name,
                parsed_data_text,
            ):
                if kind != "token":
                    yield kind, payload
                    continue
                text = str(payload.get("text") or "")
                if not text:
                    continue
                if text.startswith(emitted_text):
                    delta = text[len(emitted_text) :]
                elif emitted_text.startswith(text):
                    delta = ""
                else:
                    delta = text
                if delta:
                    emitted_text += delta
                    yield "token", {"text": delta}

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"上游返回 {response.status_code}：{self._error_detail(detail)}"
                    )
                event_name = ""
                data_parts: list[str] = []
                async for line in response.aiter_lines():
                    if line == "":
                        if data_parts:
                            async for item in parsed_events(
                                event_name, "\n".join(data_parts)
                            ):
                                yield item
                        event_name = ""
                        data_parts = []
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_parts.append(line[5:].strip())
                    elif line.startswith("{"):
                        data_parts.append(line)
                if data_parts:
                    async for item in parsed_events(event_name, "\n".join(data_parts)):
                        yield item

    async def _parse_upstream_event(
        self,
        protocol: AIProtocol,
        event_name: str,
        data_text: str,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        if not data_text or data_text == "[DONE]":
            return
        try:
            payload = json.loads(data_text)
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        if payload.get("error"):
            error = payload["error"]
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(str(detail or "上游返回错误。"))
        if protocol == "responses":
            kind = str(event_name or payload.get("type") or "")
            if kind == "response.output_text.delta":
                delta = str(payload.get("delta") or "")
                if delta:
                    yield "token", {"text": delta}
            if kind in {"response.completed", "response.incomplete"}:
                response = payload.get("response")
                if isinstance(response, dict):
                    text = self._responses_output_text(response.get("output"))
                    if text:
                        yield "token", {"text": text}
                    if isinstance(response.get("usage"), dict):
                        yield "usage", response["usage"]
            elif not kind:
                text = self._responses_output_text(payload.get("output"))
                if text:
                    yield "token", {"text": text}
                if isinstance(payload.get("usage"), dict):
                    yield "usage", payload["usage"]
            return
        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    text = self._chat_content_text(delta.get("content"))
                    if text:
                        yield "token", {"text": text}
                message = choice.get("message")
                if isinstance(message, dict):
                    text = self._chat_content_text(message.get("content"))
                    if text:
                        yield "token", {"text": text}
        if isinstance(payload.get("usage"), dict):
            yield "usage", payload["usage"]

    def _request_body(self, account: AIAccount, prompt: str) -> dict[str, Any]:
        if account.protocol == "responses":
            return {
                "model": account.model,
                "input": [{"role": "user", "content": prompt}],
                "stream": True,
            }
        return {
            "model": account.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "stream_options": {"include_usage": True},
        }

    def _endpoint(self, account: AIAccount) -> str:
        base = account.base_url.rstrip("/")
        if account.protocol == "responses":
            return base if base.endswith("/responses") else f"{base}/responses"
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _models_endpoint(self, base_url: str) -> str:
        base = base_url.rstrip("/")
        for suffix in ("/chat/completions", "/responses", "/models"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        return f"{base}/models"

    def _usage_from_payload(self, payload: dict[str, Any], protocol: AIProtocol) -> AIUsage:
        if protocol == "responses":
            input_details = payload.get("input_tokens_details")
            output_details = payload.get("output_tokens_details")
            return AIUsage(
                input_tokens=int(payload.get("input_tokens") or 0),
                output_tokens=int(payload.get("output_tokens") or 0),
                total_tokens=int(payload.get("total_tokens") or 0),
                cached_input_tokens=self._detail_token(input_details, "cached_tokens"),
                reasoning_tokens=self._detail_token(output_details, "reasoning_tokens"),
                source="provider",
            ).normalize()
        prompt_details = payload.get("prompt_tokens_details")
        completion_details = payload.get("completion_tokens_details")
        return AIUsage(
            input_tokens=int(payload.get("prompt_tokens") or 0),
            output_tokens=int(payload.get("completion_tokens") or 0),
            total_tokens=int(payload.get("total_tokens") or 0),
            cached_input_tokens=self._detail_token(prompt_details, "cached_tokens"),
            reasoning_tokens=self._detail_token(completion_details, "reasoning_tokens"),
            source="provider",
        ).normalize()

    def _detail_token(self, value: Any, key: str) -> int:
        if not isinstance(value, dict):
            return 0
        return int(value.get(key) or 0)

    def _chat_content_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if not isinstance(value, list):
            return ""
        return "".join(
            str(item.get("text") or "")
            for item in value
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
        )

    def _responses_output_text(self, value: Any) -> str:
        if not isinstance(value, list):
            return ""
        parts: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in {"output_text", "text"}:
                    parts.append(str(part.get("text") or ""))
        return "".join(parts)

    def _final_usage(self, usage: AIUsage, prompt: str, output: str) -> AIUsage:
        normalized = usage.normalize()
        if normalized.source == "provider":
            return normalized
        return AIUsage(
            input_tokens=estimate_tokens(prompt),
            output_tokens=estimate_tokens(output) if output else 0,
            source="estimated",
        ).normalize()

    def _result_cache_key(
        self,
        account: AIAccount,
        role: AIRole,
        action: str,
        compressed: CompressedPrompt,
    ) -> str:
        value = {
            "version": PromptCompressor.prompt_version,
            "accountId": account.id,
            "model": account.model,
            "protocol": account.protocol,
            "role": role,
            "action": action,
            "promptFingerprint": compressed.fingerprint,
            "sentPrompt": hashlib.sha256(compressed.text.encode("utf-8")).hexdigest(),
        }
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _claim_inflight(self, cache_key: str) -> tuple[bool, Future[AICompletionResult]]:
        with _INFLIGHT_LOCK:
            existing = _INFLIGHT.get(cache_key)
            if existing is not None:
                return False, existing
            future: Future[AICompletionResult] = Future()
            _INFLIGHT[cache_key] = future
            return True, future

    def _record(
        self,
        *,
        request_id: str,
        root: str,
        role: AIRole,
        action: str,
        account: AIAccount,
        status: str,
        usage: AIUsage,
        cache_hit: bool,
        started: float,
        compressed: CompressedPrompt,
        error: str = "",
    ) -> None:
        self.repository.record_usage(
            request_id=request_id,
            root=root,
            role=role,
            action=action,
            account=account,
            status=status,
            usage=usage,
            cache_hit=cache_hit,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=error,
            compressed=compressed.compressed,
            original_estimated_tokens=compressed.original_tokens,
            sent_estimated_tokens=compressed.sent_tokens,
        )

    def _usage_event_latency(self, request_id: str) -> int:
        event = next(
            (
                item
                for item in self.repository.usage_events(limit=20)
                if item["requestId"] == request_id
            ),
            None,
        )
        return int(event["latencyMs"] or 0) if event else 0

    def _chunks(self, text: str, size: int = 12) -> list[str]:
        return [text[index : index + size] for index in range(0, len(text), size)]

    def _error_detail(self, text: str) -> str:
        try:
            payload = json.loads(text)
        except ValueError:
            return text.strip()[:500] or "请求失败"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error)[:500]
            if error:
                return str(error)[:500]
        return str(payload)[:500]

    def _connection_error_detail(
        self,
        status_code: int,
        text: str,
        *,
        endpoint: str,
    ) -> str:
        if status_code == 401:
            return f"{endpoint} 已到达上游，但 API Key 未通过鉴权。请检查 Key 是否完整、未过期。"
        if status_code == 403:
            return (
                f"{endpoint} 路径正确，但上游拒绝了请求。请检查 API Key、IP 白名单、"
                "网关权限或是否要求开放模型列表；也可以直接手动填写模型 ID。"
            )
        if text.lstrip().lower().startswith("<html"):
            return "上游返回了 HTML 错误页，请检查 Base URL、网关权限和 API Key。"
        return self._error_detail(text)


def estimate_tokens(text: str) -> int:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    other = max(0, len(text) - cjk)
    return max(1, (cjk + 1) // 2 + (other + 3) // 4)
