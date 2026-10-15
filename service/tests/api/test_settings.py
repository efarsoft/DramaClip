"""api.settings：get/update（未知键拒绝、写后原地 reload）。"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from dramaclip.api import settings as settings_api
from dramaclip.infra import config
from dramaclip.infra.storage.repos import settings as settings_repo
from dramaclip.transport.rpc import Router, RpcRequest


class Harness:
    def __init__(self, conn: sqlite3.Connection, settings: dict[str, str]) -> None:
        from types import SimpleNamespace

        self.context = SimpleNamespace(conn=conn, settings=settings)
        self.router = Router()
        settings_api.register(self.router, self.context)  # type: ignore[arg-type]

    def rpc(self, method: str, params: dict[str, Any]) -> Any:
        return self.router.dispatch(RpcRequest(id=method, method=method, params=params)).result


def test_update_rejects_unknown_key(memory_db: sqlite3.Connection) -> None:
    harness = Harness(memory_db, {})
    response = harness.router.dispatch(
        RpcRequest(id=1, method="settings.update", params={"values": {"nope.key": "1"}})
    )
    assert response.error is not None and response.error.code == -32001


def test_update_writes_through_to_the_live_snapshot(
    memory_db: sqlite3.Connection,
) -> None:
    """写库之后内存快照必须同步——LLM 端点等热生效靠的就是这一步。"""
    settings = {"llm.base_url": ""}
    harness = Harness(memory_db, settings)

    result = harness.rpc(
        "settings.update", {"values": {"llm.base_url": "https://new.example/v1"}}
    )

    assert result == {"ok": True, "updated": 1}
    assert harness.rpc("settings.get", {})["llm.base_url"] == "https://new.example/v1"


def test_get_replaces_secret_values_with_the_sentinel(memory_db: sqlite3.Connection) -> None:
    """密钥类键（*.api_key / *.token）出参只给替位；空值不涂掩码，UI 仍是干净的空框。"""
    harness = Harness(
        memory_db,
        {
            "llm.api_key": "sk-real-secret",
            "agent_gateway.token": "tok-real",
            "asr.api_key": "",
            "llm.base_url": "https://api.example/v1",
        },
    )
    projected = harness.rpc("settings.get", {})

    assert projected["llm.api_key"] == settings_api.MASK_SENTINEL
    assert projected["agent_gateway.token"] == settings_api.MASK_SENTINEL
    assert projected["asr.api_key"] == ""
    assert projected["llm.base_url"] == "https://api.example/v1"
    assert "sk-real-secret" not in json.dumps(projected)
    # 脱敏是投影不是改写：内存快照仍持真值，消费方（LLM/TTS 客户端）照常可用
    assert harness.context.settings["llm.api_key"] == "sk-real-secret"  # type: ignore[attr-defined]


def test_update_treats_the_sentinel_as_keep_current(
    memory_db: sqlite3.Connection,
) -> None:
    """UI 把掩码原样送回 = 保持库中现值；计数只算真写下的键，避免「改了什么」虚报。"""
    harness = Harness(memory_db, {"llm.api_key": "sk-real-secret", "llm.model": "old"})
    settings_repo.set_value(memory_db, "llm.api_key", "sk-real-secret")

    result = harness.rpc(
        "settings.update",
        {"values": {"llm.api_key": settings_api.MASK_SENTINEL, "llm.model": "qwen-max"}},
    )

    assert result == {"ok": True, "updated": 1}
    assert settings_repo.get_all(memory_db)["llm.api_key"] == "sk-real-secret"
    assert harness.context.settings["llm.api_key"] == "sk-real-secret"  # type: ignore[attr-defined]


# ── 设置键治理：登记的键才有人能设，密钥类一律不得明文出仓 ──────────────

# `tts.voice` 是引擎分键（tts.voice.kokoro / .edge）之前的全局旧键，代码里留着只为
# 读升级前的旧库。它**故意不登记**：登记等于在界面上复活一个没人听的开关。
_LEGACY_READ_ONLY_KEYS = frozenset({"tts.voice"})
_KEY_READ = re.compile(
    r"(?:settings|_settings|context_settings|ctx_settings)"
    r"""\s*(?:\.get\(|\[)\s*["']([a-z0-9_]+\.[a-z0-9_.]+)["']"""
)


def _package_root() -> Path:
    """`dramaclip/` 包根（config.py 在 infra 下，往上两层）。"""
    return Path(config.__file__).resolve().parent.parent


def test_every_settings_key_read_in_code_is_registered() -> None:
    """代码里读的键必须能在 DEFAULTS 里找到名字（`docs/service/03` 第 2 节的字面化）。

    没登记的键有三重后果，每一条本仓都真中过：`settings.update` 按未知键拒绝，
    界面上永远写不进（`llm.timeout_s` 2026-10-06 起就是死的）；出参脱敏的判据按登记
    面走，`vision.cloud_api_key` 因此明文回显过；读它的代码只能靠猜默认值
    （`tts.model` 当年的注释就写了这句）。这条把「键表是真相源」从注释升级成门禁。
    """
    offenders: list[str] = []
    root = _package_root()
    for source in sorted(root.rglob("*.py")):
        for lineno, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in _KEY_READ.finditer(line):
                key = match.group(1)
                if key in config.DEFAULTS or key in _LEGACY_READ_ONLY_KEYS:
                    continue
                offenders.append(f"{source.relative_to(root)}:{lineno} {key}")
    assert offenders == [], (
        "读到未登记的设置键（界面上设不了、脱敏也罩不住）：" + "; ".join(offenders)
    )


def test_no_registered_secret_key_escapes_the_mask(memory_db: sqlite3.Connection) -> None:
    """按**登记面**穷举密钥类键，逐个验脱敏——逐个点名写死就是漏键的成因。

    上一条 `test_get_replaces_secret_values_with_the_sentinel` 手工列了三个键，
    第四个（`vision.cloud_api_key`，image 域启用即镜像写入）就这么漏过去了。
    """
    secrets = [key for key in config.DEFAULTS if settings_api._is_secret(key)]
    assert "vision.cloud_api_key" in secrets, (
        "vision.cloud_api_key 必须仍被认作密钥（它就在 DEFAULTS 里，判据却按尾段认）"
    )
    harness = Harness(memory_db, {key: "sk-real-secret" for key in secrets})

    projected = harness.rpc("settings.get", {})

    leaked = [key for key in secrets if projected[key] != settings_api.MASK_SENTINEL]
    assert leaked == [], f"这些密钥类键原样出仓了：{leaked}"
    assert "sk-real-secret" not in json.dumps(projected)
