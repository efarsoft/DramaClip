"""RPC 执行池分工：轻量查询走专用小池，长任务不再饿死任务列表（2026-10-28 实测立案）。"""

import pathlib
import re

import pytest

from dramaclip.service_app import EXPLICIT_LIGHT_QUERIES, _is_light_query


def test_job_and_status_queries_are_light() -> None:
    assert _is_light_query("models.list")
    assert _is_light_query("models.runtime_status")
    assert _is_light_query("jobs.list")
    assert _is_light_query("jobs.status")
    assert _is_light_query("export.status")
    assert _is_light_query("analysis.status")
    assert _is_light_query("system.ping")


def test_long_running_calls_stay_in_work_pool() -> None:
    assert not _is_light_query("narration.plan_variants")
    assert not _is_light_query("export.start")
    assert not _is_light_query("bgm.generate")
    assert not _is_light_query("tools.tts_start")


def test_every_protocol_rpc_is_classified() -> None:
    """协议全覆盖：每个 RPC 必须落进「轻量查询」或「长任务」之一，二选一缺号即红。

    两次实锤（jobs.list、models.list 被长任务饿死）证明隐式模式必有漏网——
    新增 RPC 时此测试强制做一次饿死风险评估，漏分类在 CI 当场拦下。
    """
    protocol = pathlib.Path(__file__).resolve().parents[2] / "protocol" / "ts" / "index.ts"
    if not protocol.is_file():
        pytest.skip("协议文件不在（非仓库运行）")
    names = set(re.findall(r"'([a-z_]+\.[a-z_0-9]+)'", protocol.read_text(encoding='utf-8')))
    known_long = {
        "analysis.cancel", "analysis.export_transcripts", "analysis.prescreen",
        "analysis.start", "analysis.resync_semantic", "analysis.update_asr",
        "bgm.generate", "bgm.rescan",
        "engine_configs.create", "engine_configs.delete", "engine_configs.enable",
        "engine_configs.test", "engine_configs.update", "engines.selftest",
        "engines.selftest_results",
        "export.delete", "export.ensure_covers", "export.retry", "export.selfcheck",
        "export.submit", "export.set_publish_data",
        "narration.generate_titles", "narration.plan_variants",
        "narration.recommend_modes", "narration.update_titles",
        "project.create", "project.delete", "project.duplicate",
        "project.ensure_covers", "project.rename", "project.reorder_episodes",
        "project.scan_episodes", "project.update_settings",
        "prompts.reset", "prompts.save", "settings.update",
        "tools.asr_start", "tools.extract_start", "tools.get_result", "tools.rewrite",
        "tools.tts", "tts.auto_voice", "tts.clean_reference", "tts.preview",
    }
    for name in sorted(names):
        if _is_light_query(name):
            assert name in EXPLICIT_LIGHT_QUERIES or name.endswith(".status") or name.startswith(
                ("jobs.", "system.", "models.")
            ), f"{name} 撞上轻量模式但不在显式清单"
        else:
            assert name in known_long, (
                f"{name} 未分类：判定它是长任务就补进 known_long，是纯读查询就补进"
                "EXPLICIT_LIGHT_QUERIES——新 RPC 必须做一次饿死风险评估"
            )
