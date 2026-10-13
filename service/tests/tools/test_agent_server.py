"""Agent 网关：鉴权、路由与三个工具端点的契约（socket 级，起临时端口实测）。"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from tools import agent_server

_TOKEN = "test-token"
_FIXTURES = Path(__file__).resolve().parents[1] / "review_fixtures"


class _FakeClient:
    def __init__(self, payload: object, **kwargs: object) -> None:
        self.payload = payload

    def chat_json(self, system: str, user: str, temperature: float = 0.3) -> object:
        return {"titles": ["假标题一"], "caption": "假文案。", "tags": ["短剧推荐"]}


@pytest.fixture()
def server_url(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(
        agent_server.titles_engine, "LlmClient", lambda *a, **k: _FakeClient(None)
    )
    # 形似配置即可过 configured 门；真调用走上面的假客户端
    settings = {"llm.base_url": "https://x/v1", "llm.model": "m", "llm.api_key": "k"}
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), agent_server.make_handler(_TOKEN, settings_provider=lambda: settings)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    thread.join(timeout=5)


def _call(
    url: str, path: str, token: str | None = _TOKEN, body: dict | None = None
) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    method = "POST" if body is not None else "GET"
    request = urllib.request.Request(url + path, data=data, method=method)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_health_needs_no_token(server_url: str) -> None:
    status, payload = _call(server_url, "/health", token=None)
    assert status == 200 and payload["ok"] is True


def test_tools_reject_missing_token(server_url: str) -> None:
    status, payload = _call(server_url, "/tools/audit_copy", token=None, body={})
    assert status == 401 and "token" in payload["error"]


def test_unknown_endpoint_is_404(server_url: str) -> None:
    status, payload = _call(server_url, "/tools/nope", body={})
    assert status == 404


def test_audit_copy_roundtrip(server_url: str) -> None:
    slots = [{"id": "s1", "task": "开场", "start": 0.0, "end": 12.5, "lines": "台词"}]
    lines = [{"id": "s1", "text": "开场文案"}]
    status, payload = _call(server_url, "/tools/audit_copy", body={"lines": lines, "slots": slots})
    assert status == 200
    assert payload["passed"] is True
    assert any(f["rule_id"] == "COPY_COVER_ALL_IDS" for f in payload["findings"])


def test_audit_copy_rejects_bad_body(server_url: str) -> None:
    status, payload = _call(server_url, "/tools/audit_copy", body={"lines": "不是数组"})
    assert status == 422 and "数组" in payload["error"]


def test_audit_script_roundtrip(server_url: str) -> None:
    script = {
        "hook": "开场钩子",
        "segments": [{"episode": 1, "start": 0.0, "end": 12.5, "text": "文案"}],
        "cta": "点我看完结",
    }
    transcript = [
        {"episode": 1, "start": 0.0, "end": 12.5, "speaker": "角色A", "text": "台词一"},
    ]
    status, payload = _call(
        server_url, "/tools/audit_script", body={"script": script, "transcript": transcript}
    )
    assert status == 200 and payload["passed"] is True


def test_draft_titles_roundtrip(server_url: str) -> None:
    status, payload = _call(
        server_url,
        "/tools/draft_titles",
        body={"narration_texts": ["她被全家逼着嫁给残废将军。"]},
    )
    assert status == 200
    assert payload["titles"][0]["text"] == "假标题一"
    assert payload["tags"] == ["短剧推荐"]
