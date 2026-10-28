"""RPC 执行池分工：轻量查询走专用小池，长任务不再饿死任务列表（2026-10-28 实测立案）。"""

from dramaclip.service_app import _is_light_query


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
