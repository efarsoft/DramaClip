"""RPC 执行池分工：轻量查询走专用小池，长任务不再饿死任务列表（2026-10-28 实测立案）。

2026-11-26 修正：分类只认显式清单。历史上按 jobs./system./models. 前缀兜底，把写方法
（jobs.clear_finished、models.download、export.import_settlement_csv）送进只读连接——
结算 CSV 回填匹配到作品即必失败；任务清理靠 JobStore 自带写连接侥幸成功，但写操作占了
查询通道，读写分离名存实亡。本文件同时钉死：写方法永不进轻量清单，清单不得有僵尸项。
"""

import pathlib
import re

import pytest

from dramaclip.service_app import EXPLICIT_LIGHT_QUERIES, _is_light_query

# 写库/写文件/长耗时方法：只允许走工作池（可写连接 + 足够线程）。
WRITE_OR_HEAVY = frozenset(
    {
        "system.shutdown",
        "project.create",
        "project.delete",
        "project.rename",
        "project.update_settings",
        "project.duplicate",
        "project.scan_episodes",
        "project.ensure_covers",
        "project.reorder_episodes",
        "analysis.prescreen",
        "analysis.update_asr",
        "analysis.speaker_mapping",
        "analysis.resync_semantic",
        "analysis.start",
        "analysis.cancel",
        "analysis.episodes",
        "analysis.episode_detail",
        "analysis.export_transcripts",
        "narration.plan_variants",
        "narration.recommend_modes",
        "narration.generate_titles",
        "narration.update_titles",
        "export.submit",
        "export.retry",
        "export.ensure_covers",
        "export.platform_covers",
        "export.delete",
        "export.selfcheck",
        "export.set_publish_data",
        "export.import_settlement_csv",
        "models.install_runtime",
        "models.install_local_runtime",
        "models.install_indextts",
        "models.install_music_runtime",
        "models.llama_install",
        "models.download",
        "models.clean_residue",
        "models.clean_orphan",
        "models.relayout",
        "models.import_commit",
        "models.import_forget",
        "models.delete",
        "bgm.generate",
        "bgm.rescan",
        "jobs.cancel",
        "jobs.clear_finished",
        "engines.selftest",
        "engines.selftest_results",
        "engine_configs.create",
        "engine_configs.update",
        "engine_configs.delete",
        "engine_configs.enable",
        "engine_configs.test",
        "settings.update",
        "tts.preview",
        "tts.clean_reference",
        "tts.auto_voice",
        "prompts.save",
        "prompts.reset",
        "tools.extract_start",
        "tools.get_result",
        "tools.asr_start",
        "tools.rewrite",
        "tools.tts",
    }
)


def _protocol_names() -> set[str]:
    protocol = pathlib.Path(__file__).resolve().parents[2] / "protocol" / "ts" / "index.ts"
    if not protocol.is_file():
        pytest.skip("协议文件不在（非仓库运行）")
    text = protocol.read_text(encoding="utf-8")
    block = text.split("export const METHOD_NAMES = [", 1)[1].split("] as const;", 1)[0]
    return set(re.findall(r"'([a-z_]+\.[a-z_0-9]+)'", block))


def test_job_and_status_queries_are_light() -> None:
    assert _is_light_query("models.list")
    assert _is_light_query("models.runtime_status")
    assert _is_light_query("jobs.list")
    assert _is_light_query("jobs.get")
    assert _is_light_query("analysis.status")
    assert _is_light_query("export.get")
    assert _is_light_query("system.ping")
    assert _is_light_query("system.health")


def test_write_methods_never_route_to_read_lane() -> None:
    """只读连接上执行写语句必抛 readonly 错误（2026-11-26 临时库复现）。

    这些方法一旦被判成轻量查询，轻则结算回填失败，重则写操作占满查询通道。
    """
    for method in (
        "jobs.cancel",
        "jobs.clear_finished",
        "models.download",
        "models.install_runtime",
        "models.import_commit",
        "export.import_settlement_csv",
        "export.set_publish_data",
        "settings.update",
        "narration.plan_variants",
    ):
        assert not _is_light_query(method), f"{method} 是写/长任务，不能走只读小池"


def test_long_running_calls_stay_in_work_pool() -> None:
    assert not _is_light_query("narration.plan_variants")
    assert not _is_light_query("export.submit")
    assert not _is_light_query("bgm.generate")
    assert not _is_light_query("tools.tts")


def test_every_protocol_rpc_is_classified() -> None:
    """协议全覆盖：每个 RPC 必须落进「纯读小池」或「工作池」之一，二选一缺号即红。"""
    names = _protocol_names()
    light = {name for name in names if _is_light_query(name)}
    assert light == set(EXPLICIT_LIGHT_QUERIES), "轻量清单与协议集合不一致（有僵尸项或漏登记）"
    assert names - light == WRITE_OR_HEAVY, (
        "未分类 RPC：判定它是长任务/写操作就补进 WRITE_OR_HEAVY，"
        "是纯读查询就补进 EXPLICIT_LIGHT_QUERIES——新 RPC 必须做一次副作用评估"
    )
    assert not (light & WRITE_OR_HEAVY)
