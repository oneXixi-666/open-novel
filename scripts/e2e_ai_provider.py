from __future__ import annotations

import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
CONTROLLED_MODEL = REPOSITORY_ROOT / "scripts" / "e2e_controlled_model.py"


def controlled_output(prompt: str) -> str:
    if prompt.strip() == "hi":
        return "hi"
    with TemporaryDirectory(prefix="open-novel-e2e-ai-") as temp_dir:
        prompt_path = Path(temp_dir) / "prompt.txt"
        output_path = Path(temp_dir) / "output.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        subprocess.run(
            [sys.executable, str(CONTROLLED_MODEL), str(prompt_path), str(output_path)],
            cwd=REPOSITORY_ROOT,
            check=True,
            timeout=30,
        )
        output = output_path.read_text(encoding="utf-8")
        if output.startswith('{"error": "unsupported controlled E2E prompt"}'):
            return (
                "审核角色生成的修复候选。"
                if "审稿" in prompt or "review" in prompt.lower()
                else "写作角色生成的候选内容。"
            )
        return output


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


class ProviderHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json({"status": "ok"})
            return
        if self.path == "/v1/models":
            self._send_json(
                {
                    "object": "list",
                    "data": [
                        {"id": "controlled-responses", "object": "model"},
                        {"id": "controlled-chat", "object": "model"},
                    ],
                }
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path not in {"/v1/responses", "/v1/chat/completions"}:
            self.send_error(404)
            return
        try:
            payload = self._read_json()
            prompt = self._prompt(payload)
            output = controlled_output(prompt)
            if self.path.endswith("/responses"):
                self._send_responses_stream(prompt, output)
            else:
                self._send_chat_stream(prompt, output)
        except Exception as exc:
            self._send_json(
                {"error": {"message": str(exc)}},
                status=500,
            )

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        value = json.loads(self.rfile.read(length) or b"{}")
        return value if isinstance(value, dict) else {}

    def _prompt(self, payload: dict[str, Any]) -> str:
        if self.path.endswith("/responses"):
            inputs = payload.get("input")
            if isinstance(inputs, str):
                return inputs
            if not isinstance(inputs, list):
                return ""
            return "\n".join(
                str(item.get("content") or "")
                for item in inputs
                if isinstance(item, dict)
            )
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return ""
        return "\n".join(
            str(item.get("content") or "")
            for item in messages
            if isinstance(item, dict)
        )

    def _send_responses_stream(self, prompt: str, output: str) -> None:
        usage = {
            "input_tokens": estimate_tokens(prompt),
            "output_tokens": estimate_tokens(output),
            "total_tokens": estimate_tokens(prompt) + estimate_tokens(output),
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }
        response_id = f"resp_{uuid4().hex}"
        events = [
            (
                "response.output_text.delta",
                {
                    "type": "response.output_text.delta",
                    "response_id": response_id,
                    "delta": output,
                },
            ),
            (
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {
                        "id": response_id,
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": output}],
                            }
                        ],
                        "usage": usage,
                    },
                },
            ),
        ]
        self._send_sse(events)

    def _send_chat_stream(self, prompt: str, output: str) -> None:
        input_tokens = estimate_tokens(prompt)
        output_tokens = estimate_tokens(output)
        events = [
            (
                "",
                {
                    "id": f"chatcmpl-{uuid4().hex}",
                    "choices": [{"index": 0, "delta": {"content": output}}],
                },
            ),
            (
                "",
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": input_tokens,
                        "completion_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                        "prompt_tokens_details": {"cached_tokens": 0},
                        "completion_tokens_details": {"reasoning_tokens": 0},
                    },
                },
            ),
        ]
        self._send_sse(events, done=True)

    def _send_sse(
        self,
        events: list[tuple[str, dict[str, Any]]],
        *,
        done: bool = False,
    ) -> None:
        chunks: list[str] = []
        for event_name, payload in events:
            if event_name:
                chunks.append(f"event: {event_name}\n")
            chunks.append(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")
        if done:
            chunks.append("data: [DONE]\n\n")
        body = "".join(chunks).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8876), ProviderHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
