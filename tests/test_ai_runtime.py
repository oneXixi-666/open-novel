from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import open_novel.core.ai_runtime as ai_runtime_module
from open_novel.core.ai_runtime import (
    _INFLIGHT,
    AIAccountRepository,
    AIRuntimeService,
    LocalSecretStore,
    PromptCompressor,
)


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, reference: str) -> str:
        return self.values.get(reference, "")

    def set(self, reference: str, secret: str) -> None:
        self.values[reference] = secret

    def delete(self, reference: str) -> None:
        self.values.pop(reference, None)


def _runtime(tmp_path) -> AIRuntimeService:
    return AIRuntimeService(
        AIAccountRepository(tmp_path / "workspace.sqlite3"),
        MemorySecretStore(),
    )


def _account(runtime: AIRuntimeService, protocol: str = "responses") -> str:
    account = runtime.save_account(
        name=f"{protocol} account",
        base_url="https://api.example.com/v1",
        api_key="secret",
        model="test-model",
        protocol=protocol,
        max_context_tokens=4096,
        enabled=True,
    )
    runtime.bind_roles(account["id"], account["id"])
    return account["id"]


def test_repository_concurrent_legacy_schema_upgrade_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "workspace.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE ai_accounts (
                account_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                model TEXT NOT NULL,
                protocol TEXT NOT NULL,
                max_context_tokens INTEGER NOT NULL DEFAULT 32768,
                enabled INTEGER NOT NULL DEFAULT 1,
                secret_ref TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    worker_count = 16
    barrier = threading.Barrier(worker_count)

    def initialize_repository(_: int) -> None:
        barrier.wait()
        AIAccountRepository(db_path)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        list(executor.map(initialize_repository, range(worker_count)))

    with sqlite3.connect(db_path) as conn:
        columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(ai_accounts)")
        }
    assert "purpose" in columns


def test_ai_accounts_bind_roles_and_preserve_secrets(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    account_id = _account(runtime)

    runtime.save_account(
        account_id=account_id,
        name="renamed",
        purpose="悬疑推理与严格审稿",
        base_url="https://api.example.com/v1",
        api_key=None,
        model="test-model-2",
        protocol="chat_completions",
        max_context_tokens=8192,
        enabled=True,
    )
    settings = runtime.settings()

    assert settings["accounts"][0]["name"] == "renamed"
    assert settings["accounts"][0]["purpose"] == "悬疑推理与严格审稿"
    assert settings["accounts"][0]["protocol"] == "chat_completions"
    assert settings["accounts"][0]["hasApiKey"] is True
    assert settings["roles"] == {
        "writingAccountId": account_id,
        "reviewAccountId": account_id,
    }

    runtime.bind_roles("", "")
    assert runtime.settings()["roles"] == {
        "writingAccountId": "",
        "reviewAccountId": "",
    }


def test_local_secret_store_persists_key_without_public_echo(tmp_path) -> None:
    db_path = tmp_path / "workspace.sqlite3"
    runtime = AIRuntimeService(
        AIAccountRepository(db_path),
        LocalSecretStore(db_path),
    )

    account = runtime.save_account(
        name="database account",
        base_url="https://api.example.com/v1",
        api_key="database-secret",
        model="test-model",
        protocol="responses",
        max_context_tokens=128000,
        enabled=True,
    )

    with sqlite3.connect(db_path) as conn:
        stored_secret = conn.execute(
            "SELECT secret FROM ai_secrets WHERE reference = ?",
            (f"ai-account:{account['id']}",),
        ).fetchone()

    assert stored_secret == ("database-secret",)
    assert account["hasApiKey"] is True
    assert "apiKey" not in account
    assert "secretRef" not in account

    reloaded = AIRuntimeService(
        AIAccountRepository(db_path),
        LocalSecretStore(db_path),
    )
    assert reloaded.settings()["accounts"][0]["hasApiKey"] is True


def test_local_secret_store_migrates_and_removes_legacy_json(tmp_path) -> None:
    db_path = tmp_path / "workspace.sqlite3"
    fallback_path = tmp_path / "open-novel-ai-secrets.json"
    fallback_path.write_text(
        json.dumps(
            {
                "ai-account:first": "first-secret",
                "ai-account:second": "second-secret",
            }
        ),
        encoding="utf-8",
    )

    store = LocalSecretStore(db_path)

    assert store.get("ai-account:first") == "first-secret"
    assert store.get("ai-account:second") == "second-secret"
    assert not fallback_path.exists()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT reference, secret FROM ai_secrets ORDER BY reference"
        ).fetchall()
    assert rows == [
        ("ai-account:first", "first-secret"),
        ("ai-account:second", "second-secret"),
    ]


def test_local_secret_store_removes_empty_legacy_json(tmp_path) -> None:
    db_path = tmp_path / "workspace.sqlite3"
    fallback_path = tmp_path / "open-novel-ai-secrets.json"
    fallback_path.write_text("{}\n", encoding="utf-8")

    LocalSecretStore(db_path)

    assert not fallback_path.exists()


def test_discover_models_uses_standard_models_endpoint(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    requested: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "data": [
                    {"id": "model-b"},
                    {"id": "model-a"},
                    {"id": "model-a"},
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            requested["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, *, headers):
            requested["url"] = url
            requested["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(ai_runtime_module.httpx, "AsyncClient", FakeAsyncClient)

    models = asyncio.run(
        runtime.discover_models(
            base_url="https://api.example.com/v1/responses",
            api_key="secret",
        )
    )

    assert models == ["model-a", "model-b"]
    assert requested["url"] == "https://api.example.com/v1/models"
    assert requested["headers"] == {
        "Accept": "application/json",
        "User-Agent": "Open-Novel/1.0",
        "Authorization": "Bearer secret",
        "X-API-Key": "secret",
    }


def test_models_endpoint_adds_v1_for_root_base_url(tmp_path) -> None:
    runtime = _runtime(tmp_path)

    assert runtime._models_endpoint("https://api.example.com") == (
        "https://api.example.com/v1/models"
    )
    assert runtime._models_endpoint("https://api.example.com/responses") == (
        "https://api.example.com/v1/models"
    )
    assert runtime._models_endpoint("https://api.example.com/v1") == (
        "https://api.example.com/v1/models"
    )


def test_unsaved_account_configuration_can_be_probed_and_records_usage(
    tmp_path,
    monkeypatch,
) -> None:
    runtime = _runtime(tmp_path)

    async def fake_upstream(account, prompt):
        assert account.base_url == "https://api.example.com/v1"
        assert account.model == "draft-model"
        assert account.protocol == "chat_completions"
        assert runtime.secret_store.get(account.secret_ref) == "draft-key"
        assert prompt == "hi"
        yield "token", {"text": "hi"}
        yield "usage", {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
        }

    monkeypatch.setattr(runtime, "_upstream_events", fake_upstream)

    result = asyncio.run(
        runtime.probe_configuration(
            base_url="https://api.example.com/v1",
            api_key="draft-key",
            model="draft-model",
            protocol="chat_completions",
            max_context_tokens=128000,
        )
    )

    assert result["text"] == "hi"
    assert result["usage"]["totalTokens"] == 2
    event = runtime.settings()["usageEvents"][0]
    assert event["action"] == "账号拨测"
    assert event["totalTokens"] == 2


def test_responses_and_chat_completions_payloads_are_parsed(tmp_path) -> None:
    runtime = _runtime(tmp_path)

    async def collect(protocol: str, event: str, payload: dict) -> list[tuple[str, dict]]:
        return [
            item
            async for item in runtime._parse_upstream_event(
                protocol,
                event,
                json.dumps(payload),
            )
        ]

    responses = asyncio.run(
        collect(
            "responses",
            "response.completed",
            {
                "response": {
                    "output": [
                        {
                            "content": [
                                {"type": "output_text", "text": "responses ok"}
                            ]
                        }
                    ],
                    "usage": {
                        "input_tokens": 3,
                        "output_tokens": 2,
                        "total_tokens": 5,
                    },
                }
            },
        )
    )
    chat = asyncio.run(
        collect(
            "chat_completions",
            "",
            {
                "choices": [
                    {"message": {"content": "chat ok"}}
                ],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 2,
                    "total_tokens": 6,
                },
            },
        )
    )

    assert responses[0] == ("token", {"text": "responses ok"})
    assert responses[1][0] == "usage"
    assert chat[0] == ("token", {"text": "chat ok"})
    assert chat[1][0] == "usage"


def test_responses_request_body_uses_input_item_list(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    account_id = _account(runtime, "responses")
    account = runtime.repository.get_account(account_id)

    assert runtime._request_body(account, "继续写这一章") == {
        "model": "test-model",
        "input": [{"role": "user", "content": "继续写这一章"}],
        "stream": True,
    }


def test_each_completion_records_provider_or_estimated_token_usage(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    _account(runtime)
    calls = 0

    async def fake_upstream(account, prompt):
        nonlocal calls
        calls += 1
        yield "token", {"text": "候选文本"}
        if calls == 1:
            yield "usage", {
                "input_tokens": 8,
                "output_tokens": 4,
                "total_tokens": 12,
                "input_tokens_details": {"cached_tokens": 2},
            }

    monkeypatch.setattr(runtime, "_upstream_events", fake_upstream)

    first = asyncio.run(
        runtime.complete(
            role="writing",
            prompt="第一份提示",
            root="/book",
            action="生成候选一",
            bypass_cache=True,
        )
    )
    second = asyncio.run(
        runtime.complete(
            role="writing",
            prompt="第二份提示",
            root="/book",
            action="生成候选二",
            bypass_cache=True,
        )
    )
    events = runtime.settings()["usageEvents"]

    assert first.usage.payload() == {
        "inputTokens": 8,
        "outputTokens": 4,
        "totalTokens": 12,
        "cachedInputTokens": 2,
        "reasoningTokens": 0,
        "source": "provider",
    }
    assert second.usage.source == "estimated"
    assert second.usage.input_tokens > 0
    assert second.usage.output_tokens > 0
    assert [event["usageSource"] for event in events[:2]] == ["estimated", "provider"]
    assert runtime.settings()["usageSummary"]["callCount"] == 2


def test_result_cache_avoids_repeated_upstream_token_cost(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    _account(runtime)
    calls = 0

    async def fake_upstream(account, prompt):
        nonlocal calls
        calls += 1
        yield "token", {"text": "缓存候选"}

    monkeypatch.setattr(runtime, "_upstream_events", fake_upstream)
    first = asyncio.run(
        runtime.complete(
            role="writing",
            prompt="相同提示",
            root="/book",
            action="续写",
        )
    )
    second = asyncio.run(
        runtime.complete(
            role="writing",
            prompt="相同提示",
            root="/book",
            action="续写",
        )
    )

    assert calls == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.usage.total_tokens == 0
    assert runtime.settings()["usageSummary"]["cacheHits"] == 1


def test_account_probe_always_sends_hi_and_bypasses_result_cache(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    account_id = _account(runtime)
    prompts: list[str] = []

    async def fake_upstream(account, prompt):
        prompts.append(prompt)
        yield "token", {"text": "hi"}
        yield "usage", {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        }

    monkeypatch.setattr(runtime, "_upstream_events", fake_upstream)

    first = asyncio.run(runtime.probe(account_id))
    second = asyncio.run(runtime.probe(account_id))

    assert prompts == ["hi", "hi"]
    assert first["success"] is True
    assert second["usage"]["totalTokens"] == 2
    assert runtime.settings()["usageSummary"]["callCount"] == 2
    assert runtime.settings()["usageSummary"]["cacheHits"] == 0


def test_prompt_compression_respects_account_context_limit(tmp_path) -> None:
    repository = AIAccountRepository(tmp_path / "workspace.sqlite3")
    prompt = "\n\n".join(f"第 {index} 段：" + "重要上下文" * 300 for index in range(80))

    compressed = PromptCompressor(repository).compress(prompt, 2048)

    assert compressed.compressed is True
    assert compressed.original_tokens > compressed.sent_tokens
    assert compressed.sent_tokens <= 1536


def test_stream_disconnect_records_cancellation_and_cleans_inflight(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    _account(runtime)

    async def slow_upstream(account, prompt):
        yield "token", {"text": "已生成部分"}
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime, "_upstream_events", slow_upstream)

    async def cancel_stream() -> None:
        stream = runtime.stream(
            role="writing",
            prompt="会被取消的提示",
            root="/book",
            action="续写",
        )
        assert (await anext(stream)).event == "status"
        assert (await anext(stream)).event == "token"
        await stream.aclose()

    asyncio.run(cancel_stream())

    assert not _INFLIGHT
    event = runtime.settings()["usageEvents"][0]
    assert event["status"] == "cancelled"
    assert event["usageSource"] == "estimated"
    assert event["inputTokens"] > 0
    assert event["outputTokens"] > 0
