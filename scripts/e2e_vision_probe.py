"""视觉轨 e2e 探针：绕过 transport，直接以真实依赖跑 _analyze_one 全链路。

用仓库根 .venv 的 python 跑（funasr/rapidocr 全依赖）：
  .venv/Scripts/python.exe scripts/e2e_vision_probe.py [episode_number]

验收：episode_analysis.visual_track 里 contact_sheet 在场 + frames=16 条带时间戳描述。
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service"))

from dramaclip.api import analysis as analysis_api  # noqa: E402
from dramaclip.api.context import AppContext  # noqa: E402
from dramaclip.engines.analysis.runtime import AnalysisRuntime  # noqa: E402
from dramaclip.engines.vision import runtime as vision_engine  # noqa: E402
from dramaclip.infra import config, jobs, paths  # noqa: E402
from dramaclip.infra.storage import db  # noqa: E402
from dramaclip.infra.storage.repos import episodes as episodes_repo  # noqa: E402


class _PrintNotifier:
    """探针替身：日志与进度直落 stdout，观察全链路各阶段。"""

    def log(self, level: str, message: str, **_k: object) -> None:
        print(f"[{level}] {message}", flush=True)

    def progress(self, _job_id: str, percent: float, message: str) -> None:
        print(f"  [{percent:.0f}%] {message}", flush=True)

    def model_download(self, _model_id: str, percent: float, **_k: object) -> None:
        pass


def main() -> int:
    want_episode = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    # 开发态真实数据根 = 仓库 data/（Electron 主进程 dev 注入的同款）；不传会落到打包版 %APPDATA% 空库
    data_dir = paths.resolve_data_dir({"DRAMACLIP_DATA_DIR": str(Path(__file__).resolve().parents[1] / "data")})
    conn: sqlite3.Connection = db.connect(paths.db_path(data_dir))
    settings = config.load(conn)
    job_store = jobs.JobStore(conn)
    context = AppContext(
        conn=conn,
        settings=settings,
        notifier=_PrintNotifier(),  # type: ignore[arg-type]
        executor=None,
        job_store=job_store,
        analysis_runtime=AnalysisRuntime(settings, data_dir / "models"),
        work_dir=data_dir / "cache" / "analysis",
        data_dir=data_dir,
    )
    row = conn.execute(
        "select e.id from episodes e join projects p on p.id = e.project_id"
        " where e.episode_number = ? order by e.created_at desc limit 1",
        (want_episode,),
    ).fetchone()
    if row is None:
        print(f"找不到第 {want_episode} 集")
        return 1
    episode = episodes_repo.get(conn, str(row[0]))
    episode_id = str(episode["id"])
    project_id = str(episode["project_id"])
    print(f"目标：第 {want_episode} 集（{episode_id}）", flush=True)

    episodes_repo.set_status(conn, episode_id, "pending")
    job_id = job_store.create("analysis", ref_id=project_id)
    vision = vision_engine.open_session(data_dir, data_dir / "models", settings)
    print(f"vision session: {vision.model_id if vision else None}", flush=True)
    language = analysis_api.runtime.language(settings)
    ok = analysis_api._analyze_one(
        context,
        job_id,
        episode,
        0,
        1,
        language,
        threading.Event(),
        vision=vision,
    )
    if vision is not None:
        vision.close()
    print(f"_analyze_one ok={ok}", flush=True)

    record = conn.execute(
        "select visual_track from episode_analysis where episode_id = ?", (episode_id,)
    ).fetchone()
    track = json.loads(str(record["visual_track"])) if record is not None and record["visual_track"] else {}
    sheet_ok = bool(track.get("contact_sheet"))
    frames = track.get("frames", [])
    print(f"验收：contact_sheet={sheet_ok}  frames={len(frames)}  engine={track.get('engine')}")
    for frame in frames[:3]:
        print(" ", round(frame["t"], 1), frame["shot"], frame["scene"], "|", frame["people"][:30])
    if not ok or not sheet_ok or len(frames) != 16:
        print("E2E 未达标")
        return 1
    print("E2E 通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
