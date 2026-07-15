from __future__ import annotations

from open_novel.agents.cli_adapters import CliAgentCommandBuilder, CliAgentService


def test_codex_command_uses_read_only_by_default() -> None:
    command = CliAgentCommandBuilder().build("codex-cli", "hello")

    assert command.command[:5] == ["codex", "exec", "--json", "--sandbox", "read-only"]
    assert command.parseMode == "jsonl"


def test_codex_command_can_request_workspace_write() -> None:
    command = CliAgentCommandBuilder().build("codex-cli", "hello", writable=True)

    assert "workspace-write" in command.command


def test_claude_command_uses_stream_json() -> None:
    command = CliAgentCommandBuilder().build("claude-cli", "hello")

    assert command.command[:2] == ["claude", "-p"]
    assert "stream-json" in command.command


def test_qwen_command_uses_partial_stream_json() -> None:
    command = CliAgentCommandBuilder().build("qwen-cli", "hello")

    assert command.command[:2] == ["qwen", "-p"]
    assert "--include-partial-messages" in command.command


def test_codex_jsonl_extracts_only_completed_agent_messages() -> None:
    stdout = "\n".join(
        [
            '{"type":"thread.started","thread_id":"thread-1"}',
            '{"type":"item.completed","item":{"type":"error","message":"metadata warning"}}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"options\\":[1,2,3]}"}}',
            '{"type":"turn.completed","usage":{"output_tokens":12}}',
        ]
    )

    assert CliAgentService._extract_assistant_text(stdout, "jsonl") == '{"options":[1,2,3]}'


def test_codex_jsonl_uses_final_completed_agent_message() -> None:
    stdout = "\n".join(
        [
            '{"type":"item.completed","item":{"type":"agent_message","text":"working"}}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"ok\\":true}"}}',
        ]
    )

    assert CliAgentService._extract_assistant_text(stdout, "jsonl") == '{"ok":true}'


def test_stream_json_prefers_final_result_text() -> None:
    stdout = "\n".join(
        [
            '{"type":"assistant","message":{"content":[{"type":"text","text":"partial"}]}}',
            '{"type":"result","result":"final answer"}',
        ]
    )

    assert CliAgentService._extract_assistant_text(stdout, "stream-json") == "final answer"
