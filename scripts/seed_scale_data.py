"""规模造数脚本（P-B 尾，09-10 规格 §9 验收项 7）。

造 50 部剧 + 500 条成品 + 单剧 100 集，用于实测三处规模表现：
剧库滚动（DramaMatrix）、成品分组网格（WorksPage）、素材列表（EpisodeListPanel）。

诚实声明：本脚本造的是**库行**，不是真实产物——episodes.source_path 与
export_jobs.output_path 指向不存在或空的文件，封面为 NULL（界面显示占位）。
它只回答「列表在这个数据量下渲染多快、滚动掉不掉行」，不回答画质/时长真伪。

隔离纪律（沿 scripts/verify_modes.py 的先例）：默认写 <repo>/data-scale/data.db，
绝不碰真实数据目录。实跑观察用：
    $env:DRAMACLIP_DATA_DIR = "<repo>\\data-scale"
    Remove-Item Env:ELECTRON_RUN_AS_NODE; npm run dev

用法：
    ..\\.venv\\Scripts\\python.exe scripts/seed_scale_data.py [--reset]
        [--data-dir DIR] [--projects 50] [--works 500] [--big-episodes 100]
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "service"))

from dramaclip.infra import paths  # noqa: E402
from dramaclip.infra.storage import db  # noqa: E402
from dramaclip.infra.storage.repos import episodes as episodes_repo  # noqa: E402
from dramaclip.infra.storage.repos import exports as exports_repo  # noqa: E402
from dramaclip.infra.storage.repos import plans as plans_repo  # noqa: E402
from dramaclip.infra.storage.repos import projects as projects_repo  # noqa: E402

MODES = (
    "intro_narration",
    "dialogue_narration",
    "full_narration",
    "inner_monologue",
    "dual_host_chat",
    "cross_narration",
    "ultra_short_hook",
    "subtitle_flow",
    "raw_clip",
)

ANGLES = ("主角视角", "反派视角", "悬疑线", "情感线", "反转盘点", "上帝视角")

# 自检汇总态配比：多数通过，少量失败/部分，一部分从未自检（作品库筛选四态都有数据）
SELFCHECK_CYCLE = ("passed",) * 12 + ("failed",) * 2 + ("partial",) * 3 + (None,) * 3

DRAMA_NAMES = (
    "逆袭千金", "重生之都市修仙", "闪婚老公是豪门", "战神归来", "穿越医妃",
    "首富从退婚开始", "重生之商界女王", "龙王赘婿", "萌宝助攻", "重生之电竞女王",
)


def _stagger(now_ms: int, index: int, span_days: int, rng: random.Random) -> int:
    """把 created_at/completed_at 摊到过去 span_days 天里，分组网格才有真实的时间层次。"""
    span_ms = span_days * 24 * 3600 * 1000
    return now_ms - int(span_ms * (index + rng.random()) / max(1, span_days))


def seed_projects(conn, base: Path, count: int, rng: random.Random) -> list[dict]:
    now_ms = int(time.time() * 1000)
    projects = []
    for index in range(count):
        name = f"{DRAMA_NAMES[index % len(DRAMA_NAMES)]}·{index // len(DRAMA_NAMES) + 1:02d}"
        source = base / "sources" / name
        project = projects_repo.create(conn, name, str(source))
        # 剧库按 created_at 倒序：摊开时间轴，滚动才有分页感
        created = _stagger(now_ms, index, 120, rng)
        conn.execute("UPDATE projects SET created_at = ? WHERE id = ?", (created, project["id"]))
        projects.append(project)
    conn.commit()
    return projects


def seed_episodes(conn, project: dict, count: int, rng: random.Random, *, silent: int) -> None:
    base = Path(project["source_path"])
    rows = []
    for number in range(1, count + 1):
        rows.append(
            {
                "episode_number": number,
                "name": f"ep{number:03d}",
                "source_path": str(base / f"ep{number:03d}.mp4"),
                "duration": round(rng.uniform(90.0, 240.0), 3),
                # 少数集缺音轨/旧数据未知，让告警行与三态都有样本
                "has_audio": False if number <= silent else (None if number == silent + 1 else True),
            }
        )
    episodes_repo.replace_all(conn, project["id"], rows)
    # 一部分集已转写：素材列表三态与「已分析 n/m」都有真实分布
    done = episodes_repo.list_by_project(conn, project["id"])[: max(1, count // 3)]
    for episode in done:
        episodes_repo.set_status(conn, episode["id"], "done")


def seed_works(conn, projects: list[dict], total: int, base: Path, rng: random.Random) -> int:
    now_ms = int(time.time() * 1000)
    outputs = base / "outputs"
    made = 0
    for index in range(total):
        project = projects[index % len(projects)]
        mode = MODES[index % len(MODES)]
        episode_ids = [f"ep-{project['id'][:8]}-{n}" for n in range(1, rng.randint(2, 4))]
        plan = plans_repo.create(
            conn,
            project["id"],
            mode,
            episode_ids,
            {"mode": mode, "seed": True},
            angle=ANGLES[index % len(ANGLES)],
        )
        export_id = exports_repo.create(conn, project["id"], plan["id"], mode)
        exports_repo.mark_completed(conn, export_id, str(outputs / f"{export_id}.mp4"))
        exports_repo.set_meta(
            conn,
            export_id,
            duration_s=round(rng.uniform(45.0, 180.0), 2),
            size_bytes=rng.randint(8_000_000, 900_000_000),
        )
        state = SELFCHECK_CYCLE[index % len(SELFCHECK_CYCLE)]
        if state is not None:
            exports_repo.set_selfcheck(conn, export_id, '{"seed": true}', state)
        completed = _stagger(now_ms, index, 90, rng)
        conn.execute("UPDATE export_jobs SET completed_at = ? WHERE id = ?", (completed, export_id))
        made += 1
    conn.commit()
    return made


def main() -> int:
    parser = argparse.ArgumentParser(description="规模造数（默认写 data-scale，不碰真实数据）")
    parser.add_argument("--data-dir", default=str(REPO / "data-scale"))
    parser.add_argument("--projects", type=int, default=50)
    parser.add_argument("--works", type=int, default=500)
    parser.add_argument("--big-episodes", type=int, default=100)
    parser.add_argument("--reset", action="store_true", help="先删掉旧的 data.db 再造")
    parser.add_argument("--seed", type=int, default=20260910)
    args = parser.parse_args()

    base = Path(args.data_dir)
    if args.reset:
        stale = paths.db_path(base)
        if stale.exists():
            stale.unlink()
    base = paths.resolve_data_dir({"DRAMACLIP_DATA_DIR": str(base)})
    conn = db.connect(paths.db_path(base))
    try:
        applied = db.migrate(conn)
        rng = random.Random(args.seed)
        projects = seed_projects(conn, base, args.projects, rng)
        for index, project in enumerate(projects):
            # 第一部剧 = 单剧 100 集（素材列表规模样本），其余 6~14 集
            count = args.big_episodes if index == 0 else rng.randint(6, 14)
            seed_episodes(conn, project, count, rng, silent=2 if index == 0 else rng.randint(0, 1))
        made = seed_works(conn, projects, args.works, base, rng)
        total_eps = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        print(f"迁移应用: {len(applied)} 个（首次为全量，二次为 0）")
        print(f"剧: {len(projects)} 部 / 集: {total_eps} 行 / 成品: {made} 条（completed）")
        print(f"库: {paths.db_path(base)}")
        print("实跑观察：")
        print(f'  $env:DRAMACLIP_DATA_DIR = "{base}"')
        print("  Remove-Item Env:ELECTRON_RUN_AS_NODE; npm run dev")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
