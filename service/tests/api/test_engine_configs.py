"""api.engine_configs：多实例 CRUD、同域单启用、LLM 域镜像 settings。"""

from __future__ import annotations

import inspect
import json
import re
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from typing import Any

from dramaclip.api import engine_configs as engine_configs_api
from dramaclip.infra.storage.repos import engine_configs as configs_repo
from dramaclip.infra.storage.repos import settings as settings_repo
from dramaclip.transport.rpc import Router, RpcRequest


class Harness:
    def __init__(self, conn: sqlite3.Connection, settings: dict[str, str]) -> None:
        self.context = SimpleNamespace(conn=conn, settings=settings)
        self.router = Router()
        engine_configs_api.register(self.router, self.context)  # type: ignore[arg-type]

    def rpc(self, method: str, params: dict[str, Any]) -> Any:
        return self.router.dispatch(RpcRequest(id=method, method=method, params=params)).result

    def error_code(self, method: str, params: dict[str, Any]) -> int | None:
        response = self.router.dispatch(RpcRequest(id=method, method=method, params=params))
        return None if response.error is None else response.error.code


def _create(harness: Harness, name: str = "a", **overrides: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "domain": "llm",
        "name": name,
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test-1234",
        "model": "qwen-plus",
    }
    params.update(overrides)
    return harness.rpc("engine_configs.create", params)


def test_create_and_list_by_domain(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {})
    created = _create(harness)
    assert created["enabled"] == 0
    # 短 key（≤8 位）全遮蔽，长 key 首尾各保留 4 位
    assert created["api_key_masked"] == "sk-t••••1234"
    long_one = _create(harness, "b", api_key="sk-abcdefghijkl")
    masked = long_one["api_key_masked"]
    assert masked.startswith("sk-a") and masked.endswith("ijkl")
    configs = harness.rpc("engine_configs.list", {"domain": "llm"})["configs"]
    assert [c["id"] for c in configs] == [created["id"], long_one["id"]]


def test_plaintext_key_never_leaves_the_api(memory_db: sqlite3.Connection) -> None:
    """裁决「密钥不回显」：create/list/update/enable 四条出参都只带掩码，无明文键。"""
    harness = Harness(memory_db, {})
    created = _create(harness)
    updated = harness.rpc(
        "engine_configs.update",
        {"id": created["id"], "name": "a", "base_url": "https://x/v1", "api_key": "", "model": "m"},
    )
    enabled = harness.rpc("engine_configs.enable", {"id": created["id"]})
    listed = harness.rpc("engine_configs.list", {"domain": "llm"})
    for name, payload in {
        "create": created,
        "list": listed["configs"][0],
        "update": updated,
        "enable": enabled,
    }.items():
        assert "api_key" not in payload, f"{name} 出参仍带明文键"
        assert "sk-test-1234" not in json.dumps(payload, ensure_ascii=False), name


def test_update_with_blank_key_keeps_the_stored_secret(memory_db: sqlite3.Connection) -> None:
    """出参脱敏后编辑弹窗不再回填明文：留空 = 保持库中现值，改其他字段不受影响。"""
    harness = Harness(memory_db, {})
    created = _create(harness)
    updated = harness.rpc(
        "engine_configs.update",
        {
            "id": created["id"],
            "name": "改名",
            "base_url": "https://new.example/v1",
            "api_key": "",
            "model": "qwen-max",
        },
    )
    assert updated["name"] == "改名"
    assert updated["api_key_masked"] == "sk-t••••1234"
    assert configs_repo.get_secret(memory_db, str(created["id"])) == "sk-test-1234"


def test_update_with_new_key_replaces_the_stored_secret(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {})
    created = _create(harness)
    harness.rpc(
        "engine_configs.update",
        {
            "id": created["id"],
            "name": "a",
            "base_url": "https://x/v1",
            "api_key": "sk-brand-new-9999",
            "model": "m",
        },
    )
    assert configs_repo.get_secret(memory_db, str(created["id"])) == "sk-brand-new-9999"


def test_enable_is_single_per_domain(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {})
    first = _create(harness, "first")
    second = _create(harness, "second")
    harness.rpc("engine_configs.enable", {"id": first["id"]})
    harness.rpc("engine_configs.enable", {"id": second["id"]})
    listed = harness.rpc("engine_configs.list", {"domain": "llm"})["configs"]
    enabled = {c["name"] for c in listed if c["enabled"] == 1}
    assert enabled == {"second"}


def test_enable_llm_mirrors_settings(memory_db: sqlite3.Connection) -> None:
    settings: dict[str, str] = {}
    harness = Harness(memory_db, settings)
    config = _create(harness)
    harness.rpc("engine_configs.enable", {"id": config["id"]})
    mirrored = settings_repo.get_all(memory_db)
    assert mirrored["llm.base_url"] == "https://api.example.com/v1"
    assert mirrored["llm.model"] == "qwen-plus"


def test_delete_enabled_config_rejected(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {})
    config = _create(harness)
    harness.rpc("engine_configs.enable", {"id": config["id"]})
    assert harness.error_code("engine_configs.delete", {"id": config["id"]}) == -32310


def test_update_active_config_resyncs_mirror(memory_db: sqlite3.Connection) -> None:
    settings: dict[str, str] = {}
    harness = Harness(memory_db, settings)
    config = _create(harness)
    harness.rpc("engine_configs.enable", {"id": config["id"]})
    harness.rpc(
        "engine_configs.update",
        {
            "id": config["id"],
            "name": "a",
            "base_url": "https://new.example.com/v1",
            "api_key": "sk-2",
            "model": "qwen-max",
        },
    )
    mirrored = settings_repo.get_all(memory_db)
    assert mirrored["llm.base_url"] == "https://new.example.com/v1"
    assert mirrored["llm.model"] == "qwen-max"


def test_unknown_domain_rejected(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {})
    assert harness.error_code("engine_configs.create", {"domain": "nope", "name": "x"}) == -32310
    assert harness.error_code("engine_configs.list", {"domain": "nope"}) == -32310


def test_video_domain_is_gone(memory_db: sqlite3.Connection) -> None:
    """video 从来没有消费方：镜像表里没它、界面上没它，却能建档能「启用」——启用写完空表。

    留着它等于给业主一个点了没反应的按钮；视觉走的域是 image。
    """
    harness = Harness(memory_db, {})
    for method, params in {
        "engine_configs.create": {"domain": "video", "name": "x", "api_key": "k", "model": "m"},
        "engine_configs.list": {"domain": "video"},
        "engine_configs.test": {"domain": "video", "base_url": "https://x", "model": "m"},
    }.items():
        assert harness.error_code(method, params) == -32310, method


def test_enabling_a_retired_domain_row_fails_loudly(memory_db: sqlite3.Connection) -> None:
    """老库里若留着 video 行（这域从前能建档），启用要说清「域不支持」，不许抛 KeyError。"""
    legacy = configs_repo.create(memory_db, "video", "旧行", "", "sk-x", "m")
    harness = Harness(memory_db, {})
    assert harness.error_code("engine_configs.enable", {"id": legacy["id"]}) == -32310


def test_domain_without_an_endpoint_rejects_a_base_url(memory_db: sqlite3.Connection) -> None:
    """asr_cloud/tts_cloud 由服务商 SDK 写死端点：收下地址字段就是「界面能填、后端不认」的死键。

    拒收而不是静默丢弃——业主填了地址却按 SDK 默认端点跑，失败时没人知道为什么。
    """
    harness = Harness(memory_db, {})
    assert harness.error_code(
        "engine_configs.create",
        {
            "domain": "asr_cloud",
            "name": "x",
            "base_url": "https://x",
            "api_key": "k",
            "model": "m",
        },
    ) == -32310
    created = _create(harness, domain="asr_cloud", base_url="", model="qwen-audio-3.1-asr-flash")
    assert harness.error_code(
        "engine_configs.update",
        {
            "id": created["id"],
            "name": "x",
            "base_url": "https://x",
            "api_key": "",
            "model": "m",
        },
    ) == -32310
    # 空地址照旧能建能改：域不是不要这个字段，是这个域不消费它
    changed = harness.rpc(
        "engine_configs.update",
        {"id": created["id"], "name": "改名", "base_url": "", "api_key": "", "model": "m"},
    )
    assert changed["name"] == "改名"


def test_llm_key_names_have_a_single_home() -> None:
    """llm.* 三键的写法只许出现在镜像表里：自检构造与镜像写入读同一份，否则改一处漏一处。"""
    source = inspect.getsource(engine_configs_api)
    assert sorted(re.findall(r'"(llm\.[a-z_]+)"', source)) == [
        "llm.api_key",
        "llm.base_url",
        "llm.model",
    ]


class _FakeOpenAI(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server 命名约定
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "pong"}}]}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        return


def test_test_reaches_a_live_llm_endpoint(memory_db: sqlite3.Connection) -> None:
    """「测试连接」必须真打到 OpenAI 兼容端点并量出往返：ping() 唯一的可达入口就是这条。"""
    server = HTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        harness = Harness(memory_db, {})
        result = harness.rpc(
            "engine_configs.test",
            {
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "api_key": "sk-test",
                "model": "fake",
            },
        )
        assert result["ok"] is True
        assert result["error"] is None
        assert result["latency_s"] is not None
    finally:
        server.shutdown()


def test_test_reports_unreachable_endpoint_without_raising(
    memory_db: sqlite3.Connection,
) -> None:
    """连不上是 UI 要显示的结论，不是 RPC 异常——弹窗就地报错，不炸整页。"""
    harness = Harness(memory_db, {})
    result = harness.rpc(
        "engine_configs.test",
        {"base_url": "http://127.0.0.1:9", "api_key": "", "model": "x"},
    )
    assert result["ok"] is False
    assert result["error"]


# ── 云端域镜像：启用配置写进既有设置键，运行时消费方零改动 ─────────────────────


def test_enable_asr_cloud_mirrors_three_keys(memory_db: sqlite3.Connection) -> None:
    settings: dict[str, str] = {}
    harness = Harness(memory_db, settings)
    config = _create(harness, domain="asr_cloud", base_url="", model="qwen-audio-3.1-asr-flash")
    harness.rpc("engine_configs.enable", {"id": config["id"]})
    mirrored = settings_repo.get_all(memory_db)
    assert mirrored["asr.engine"] == "dashscope_cloud"
    assert mirrored["asr.api_key"] == "sk-test-1234"
    assert mirrored["asr.model"] == "qwen-audio-3.1-asr-flash"


def test_enable_tts_cloud_mirrors_three_keys(memory_db: sqlite3.Connection) -> None:
    settings: dict[str, str] = {}
    harness = Harness(memory_db, settings)
    config = _create(harness, domain="tts_cloud", base_url="", model="cosyvoice-v2")
    harness.rpc("engine_configs.enable", {"id": config["id"]})
    mirrored = settings_repo.get_all(memory_db)
    assert mirrored["tts.engine"] == "cosyvoice_cloud"
    assert mirrored["tts.api_key"] == "sk-test-1234"
    assert mirrored["tts.model"] == "cosyvoice-v2"


def test_enable_vision_cloud_mirrors_four_keys(memory_db: sqlite3.Connection) -> None:
    settings: dict[str, str] = {}
    harness = Harness(memory_db, settings)
    config = _create(harness, domain="image", model="qwen-vl-max")
    harness.rpc("engine_configs.enable", {"id": config["id"]})
    mirrored = settings_repo.get_all(memory_db)
    assert mirrored["vision.cloud"] == "1"
    assert mirrored["vision.cloud_base_url"] == "https://api.example.com/v1"
    assert mirrored["vision.cloud_api_key"] == "sk-test-1234"
    assert mirrored["vision.cloud_model"] == "qwen-vl-max"


class _FakeVision(BaseHTTPRequestHandler):
    """假多模态端点：校验 Bearer 头与路径，回一条 chat 结构。"""

    seen_auth = ""
    seen_path = ""

    def do_POST(self) -> None:  # noqa: N802 - http.server 命名约定
        _FakeVision.seen_auth = str(self.headers.get("Authorization", ""))
        _FakeVision.seen_path = self.path
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "白色"}}]}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        return


def test_vision_test_hits_chat_completions_with_bearer(
    memory_db: sqlite3.Connection,
) -> None:
    server = HTTPServer(("127.0.0.1", 0), _FakeVision)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        harness = Harness(memory_db, {})
        result = harness.rpc(
            "engine_configs.test",
            {
                "domain": "image",
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "api_key": "sk-vl",
                "model": "qwen-vl-max",
            },
        )
        assert result["ok"] is True, result["error"]
        assert _FakeVision.seen_path == "/chat/completions"
        assert _FakeVision.seen_auth == "Bearer sk-vl"
    finally:
        server.shutdown()


def test_vision_test_missing_fields_is_honest_false(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {})
    result = harness.rpc("engine_configs.test", {"domain": "image"})
    assert result["ok"] is False
    assert "不能为空" in str(result["error"])


def test_test_with_id_and_blank_key_uses_the_stored_secret(
    memory_db: sqlite3.Connection,
) -> None:
    """出参脱敏后「测连接」不能再指望前端传明文：带 id、key 留空 → 服务端内部取现值。"""
    server = HTTPServer(("127.0.0.1", 0), _FakeVision)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        harness = Harness(memory_db, {})
        config = _create(
            harness,
            domain="image",
            api_key="sk-vl-stored",
            base_url=f"http://127.0.0.1:{server.server_port}",
            model="qwen-vl-max",
        )
        result = harness.rpc(
            "engine_configs.test",
            {
                "id": config["id"],
                "domain": "image",
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "api_key": "",
                "model": "qwen-vl-max",
            },
        )
        assert result["ok"] is True, result["error"]
        assert _FakeVision.seen_auth == "Bearer sk-vl-stored"
    finally:
        server.shutdown()
