"""A/B 驱动（临时脚本，不进仓库）：钟情错付 EP1/2 真素材，槽位制 vs 整篇线对比。

用法：cd service && uv run python ../tmp-rel/drive_ab.py
产出：两版方案的全文 dump（stdout）——对比文案质量（诊断主旨的核心实验）。
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))

import sqlite3  # noqa: E402

from dramaclip.api import narration_plans, narration as narration_api  # noqa: E402
from dramaclip.engines.narration import script_driver  # noqa: E402
from dramaclip.infra import config, jobs  # noqa: E402
from dramaclip.infra.storage import db  # noqa: E402
from dramaclip.infra.ffmpeg import probe as ffprobe_mod  # noqa: E402
from dramaclip.transport.notify import Notifier  # noqa: E402

DATA_DIR = ROOT / "data"


def main() -> None:
    conn = db.connect(DATA_DIR / "data.db")
    conn.row_factory = sqlite3.Row
    project = conn.execute(
        "SELECT id, name FROM projects WHERE name LIKE '%钟情错付%'"
    ).fetchone()
    assert project is not None, "找不到钟情错付项目"
    project_id = project["id"]
    episodes = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM episodes WHERE project_id=? AND episode_number<=2 "
            "ORDER BY episode_number",
            (project_id,),
        )
    ]
    assert len(episodes) == 2, f"EP1/2 应齐备，实得 {len(episodes)}"

    # 补 duration（分析产物校验用）
    for ep in episodes:
        src = Path(ep["source_path"])
        if src.is_file() and not ep.get("duration"):
            ep["duration"] = ffprobe_mod.probe(str(src)).duration_s

    work_dir = DATA_DIR / "cache" / "analysis"
    work_dir.mkdir(parents=True, exist_ok=True)
    settings = config.load(conn)
    context = SimpleNamespace(
        conn=conn,
        settings=settings,
        notifier=Notifier(lambda payload: print(f"[notify] {payload}")),
        executor=ThreadPoolExecutor(max_workers=2),
        job_store=jobs.JobStore(conn),
        work_dir=work_dir,
        data_dir=DATA_DIR,
    )
    settings = narration_api._effective_settings(context, project_id)
    print(f"LLM 端点：{settings.get('llm.base_url', '?')}  模型：{settings.get('llm.model', '?')}")

    episode_inputs = narration_plans._collect_episode_inputs(context, episodes)
    print(f"episode_inputs：{len(episode_inputs)} 集，"
          f"段数 {[len(e['segments']) for e in episode_inputs]}")

    angle_block = "取材角度：女主视角——下毒复仇的暗线如何一步步收网，反转落在最亲的人身上。"
    

    only = sys.argv[1] if len(sys.argv) > 1 else ""
    labels = [x for x in ("A-槽位剧本链", "B-整篇叙事线") if not only or x.startswith(only)]
    for label in labels:
        settings["narration.flow_style"] = "1" if label.startswith("B") else "0"
        print(f"\n{'=' * 24} {label} {'=' * 24}")
        scoped = [e for e in episode_inputs if int(e["number"]) <= 2]
        plan, used = script_driver.script_dialogue_plan(
            scoped, settings, angle_block=angle_block, trace_dir=DATA_DIR / "logs"
        )
        print(f"[used_ids] {used}")
        print(f"[hook] {plan.model_dump().get('timeline') and ''}{plan.narration_texts[0].text if plan.narration_texts else ''}")
        for seg in plan.timeline:
            line = next(
                (t for t in plan.narration_texts if t.id == seg.narration_id), None
            )
            if line is not None and line.text:
                print(f"  [{seg.start:6.1f} → {seg.end:6.1f}] {line.text}")
        if plan.narration_texts:
            tail = plan.narration_texts[-1]
            if tail.id.startswith("n") and "全集" in tail.text or "左下角" in tail.text:
                print(f"[cta] {tail.text}")
        print(f"[方案句数] {len(plan.narration_texts)}")


if __name__ == "__main__":
    main()
