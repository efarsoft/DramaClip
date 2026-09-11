"""真机成片回归门禁：真实素材 → 真实编排 → 真实 ffmpeg 渲染 → 实测音轨/时长/冻结帧。

与单元测试的分界线：这里不 mock ffmpeg、不 mock TTS。桩测证明"代码按参数生成命令"，
本脚本证明"命令跑出来的片子真的有声音、时长合理、没有静止画面"。

用法：
  .venv/Scripts/python scripts/verify_modes.py --modes full_narration
  .venv/Scripts/python scripts/verify_modes.py --modes all --out D:/tmp/dc-report

隔离：把 data/data.db 复制进临时目录再跑，产物写临时目录，绝不写开发者的真实 data/。
退出码：任一断言失败即非零。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "service"))

from dramaclip.api import narration as narration_api
from dramaclip.api.context import AppContext
from dramaclip.engines.analysis.runtime import AnalysisRuntime
from dramaclip.engines.exporter import encoder
from dramaclip.engines.tts.factory import create as create_tts
from dramaclip.infra import config
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.storage import db
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest

ALL_MODES = [
    "raw_clip", "intro_narration", "cross_narration", "ultra_short_hook",
    "dialogue_narration", "full_narration", "subtitle_flow",
    "dual_host_chat", "inner_monologue",
]

MIN_MEAN_VOLUME_DB = -70.0  # 近乎静音的判据：旁白整条丢失会落在这里
MAX_FREEZE_S = 2.0  # 任一静止段超过这么久即判失败

FFMPEG = str(REPO / "resources" / "ffmpeg" / "ffmpeg.exe")
FFPROBE = str(REPO / "resources" / "ffmpeg" / "ffprobe.exe")

# 渲染命令插桩：记录每段用的音频角色与是否真的带上了旁白输入
CAPTURED: list[dict[str, Any]] = []
_ORIG_CUT_ARGS = encoder.cut_segment_args


def _capturing_cut_args(*args: Any, **kw: Any) -> list[str]:
    result = _ORIG_CUT_ARGS(*args, **kw)
    audio = str(kw.get("audio") or (args[3] if len(args) > 3 else ""))
    tts = kw.get("tts_audio")
    CAPTURED.append({
        "audio": audio,
        "has_tts_input": bool(tts),
        "tts_path": str(tts) if tts else None,
        "mixed": "-filter_complex" in result,
        "cmd_tail": result[-6:],
    })
    return result


encoder.cut_segment_args = _capturing_cut_args  # type: ignore[assignment]


def sh(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)


def mean_volume_db(video: Path) -> float | None:
    proc = sh([FFMPEG, "-hide_banner", "-i", str(video), "-map", "0:a:0",
               "-af", "volumedetect", "-f", "null", "-"])
    for line in proc.stderr.splitlines():
        if "mean_volume" in line:
            try:
                return float(line.split("mean_volume:")[1].strip().removesuffix(" dB"))
            except ValueError:
                return None
    return None


def max_freeze_s(video: Path) -> float:
    proc = sh([FFMPEG, "-hide_banner", "-i", str(video), "-vf",
               "freezedetect=n=-60dB:d=1.0", "-map", "0:v:0", "-an", "-f", "null", "-"])
    values = [float(line.split("duration:")[1].strip())
              for line in proc.stderr.splitlines() if "freeze_duration" in line]
    return max(values, default=0.0)


def probe_duration_s(video: Path) -> float:
    proc = sh([FFPROBE, "-v", "error", "-show_entries", "format=duration",
               "-of", "json", str(video)])
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except Exception:  # noqa: BLE001 - 探测失败按 0 处理，交给时长断言去判
        return 0.0


def has_audio_stream(video: Path) -> bool:
    proc = sh([FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries",
               "stream=codec_type", "-of", "csv=p=0", str(video)])
    return "audio" in proc.stdout


def build_context(data_dir: Path, models_dir: Path) -> tuple[AppContext, ThreadPoolExecutor]:
    conn = db.connect(data_dir / "data.db")
    settings = config.load(conn)
    store = jobs_mod.JobStore(conn)
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="verify")
    ctx = AppContext(
        conn=conn, settings=settings, notifier=Notifier(lambda _m: None),
        executor=executor, job_store=store,
        analysis_runtime=AnalysisRuntime(settings, models_dir),
        work_dir=data_dir / "cache" / "analysis", data_dir=data_dir,
    )
    return ctx, executor


def wait_job(store: jobs_mod.JobStore, job_id: str, timeout_s: float) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = store.get(job_id)
        if job and job["status"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.5)
    return {"status": "timeout", "error": f">{timeout_s}s"}


def _same_drive_temp(prefix: str) -> Path:
    """临时目录必须与仓库同盘。

    跨盘时 os.path.relpath 给不出相对路径，ass 滤镜的盘符冒号转义随之失效
    （实测 ffmpeg 把路径当 original_size 解析而整段渲染失败）。
    """
    for base in (REPO, Path(tempfile.gettempdir())):
        try:
            target = Path(tempfile.mkdtemp(prefix=f"{prefix}_", dir=str(base)))
        except OSError:
            continue
        if target.exists():
            return target
    raise RuntimeError("无法创建临时目录")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--media", default=r"D:\BaiduNetdiskDownload\小小球神不好惹")
    ap.add_argument("--modes", default="full_narration", help="逗号分隔，或 all")
    ap.add_argument("--out", default="")
    ap.add_argument("--job-timeout", type=float, default=1800.0)
    args = ap.parse_args()

    modes = ALL_MODES if args.modes == "all" else [m.strip() for m in args.modes.split(",")]
    for exe in (FFMPEG, FFPROBE):
        if not Path(exe).is_file():
            print(f"缺少可执行文件：{exe}（可从 legacy/v1-electron 分支恢复）", file=sys.stderr)
            return 2
    out_dir = Path(args.out) if args.out else _same_drive_temp("tmp_dc-verify")
    out_dir.mkdir(parents=True, exist_ok=True)

    src_db = REPO / "data" / "data.db"
    if not src_db.is_file():
        print("缺少 data/data.db，无法复用已完成的分析结果", file=sys.stderr)
        return 2
    work = _same_drive_temp("tmp_dc-verify-data")
    for suffix in ("", "-wal", "-shm"):
        f = src_db.with_name(src_db.name + suffix)
        if f.is_file():
            shutil.copy2(f, work / ("data.db" + suffix))
    # 模型目录必须是 <data_dir>/models —— _generate_one 就是这么拼路径的。
    # 用目录联接（mklink /J）而非符号链接：后者在 Windows 需要管理员特权。
    models_dir = (REPO / "data" / "models").resolve()
    link = work / "models"
    made_link = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(models_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    ).returncode == 0
    if not made_link and not link.exists():
        print(f"无法建立模型联接，TTS 会静默全批失败：{models_dir} -> {link}", file=sys.stderr)
        return 2

    media = Path(args.media)
    if not media.is_dir():
        print(f"素材目录不存在：{media}", file=sys.stderr)
        return 2

    ctx, executor = build_context(work, link)
    # 预检：先确认 TTS 真能出声，否则后面所有"零旁白"都可能是脚手架问题而不是产品缺陷
    try:
        probe_engine = create_tts(ctx.settings.get("tts.engine", "edge"), link)
        sample = probe_engine.synthesize(
            "预检", "zf_001", work / "preflight.mp3"
        )
        if not sample.is_file() or sample.stat().st_size == 0:
            print("预检失败：TTS 未产出音频，环境未就绪", file=sys.stderr)
            return 2
    except Exception as exc:  # noqa: BLE001 - 预检就是要吞下一切环境问题
        print(f"预检失败：TTS 不可用（{type(exc).__name__}: {exc}），环境未就绪", file=sys.stderr)
        return 2
    print(f"预检通过：TTS={ctx.settings.get('tts.engine', 'edge')} 可出声")
    project = ctx.conn.execute("select id from projects limit 1").fetchone()
    if project is None:
        print("库里没有项目", file=sys.stderr)
        return 2
    project_id = str(project[0])
    done = ctx.conn.execute(
        "select count(*) from episodes where status='done'"
    ).fetchone()[0]
    print(f"项目 {project_id[:8]} · 已分析 {done} 集 · 素材 {media.name} · 隔离副本 {work.name}")
    print(f"待跑模式：{', '.join(modes)}\n")

    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for mode in modes:
        CAPTURED.clear()
        router = Router()
        narration_api.register(router, ctx)
        started = time.time()
        resp = router.dispatch(RpcRequest(id=mode, method="narration.produce",
                                          params={"project_id": project_id, "modes": [mode]}))
        if resp.error is not None:
            failures.append(f"{mode}: RPC 失败 {resp.error.message}")
            rows.append({"mode": mode, "status": "rpc-error", "error": resp.error.message})
            continue
        job = wait_job(ctx.job_store, str(resp.result["job_id"]), args.job_timeout)
        rec: dict[str, Any] = {"mode": mode, "status": job["status"],
                               "elapsed_s": round(time.time() - started, 1)}
        if job["status"] != "completed":
            rec["error"] = job.get("error")
            failures.append(f"{mode}: 任务未完成（{job['status']} · {job.get('error')}）")
            rows.append(rec)
            continue

        row = ctx.conn.execute(
            "select output_path, narration_plan_id from export_jobs"
            " where status='completed' order by created_at desc limit 1").fetchone()
        if row is None or not row[0]:
            failures.append(f"{mode}: 没有成品记录")
            rows.append(rec)
            continue
        clip = Path(str(row[0]))
        plan_row = ctx.conn.execute("select plan_data from narration_plans where id=?",
                                    (row[1],)).fetchone()
        plan = json.loads(str(plan_row[0])) if plan_row else {}
        timeline = plan.get("timeline", [])
        texts = plan.get("narration_texts", [])
        roles: dict[str, int] = {}
        for seg in timeline:
            role = str(seg.get("audio", "?"))
            roles[role] = roles.get(role, 0) + 1
        tts_ok = sum(1 for t in texts
                     if t.get("audio_path") and Path(str(t["audio_path"])).is_file()
                     and Path(str(t["audio_path"])).stat().st_size > 0)
        rec.update({
            "clip": clip.name, "size_mb": round(clip.stat().st_size / 1e6, 1),
            "duration_s": round(probe_duration_s(clip), 2),
            "has_audio": has_audio_stream(clip),
            "mean_volume_db": mean_volume_db(clip),
            "max_freeze_s": round(max_freeze_s(clip), 2),
            "planner": plan.get("planner"),
            "segments": len(timeline),
            "audio_roles": roles,
            "narration_texts": len(texts),
            "tts_files_ok": tts_ok,
            "segments_captured": len(CAPTURED),
            "segments_with_tts": sum(1 for c in CAPTURED if c["has_tts_input"]),
            "segments_mixed": sum(1 for c in CAPTURED if c["mixed"]),
            "tts_files_missing": sum(1 for c in CAPTURED
                                      if c["tts_path"] and not Path(c["tts_path"]).is_file()),
            "tts_files_empty": sum(1 for c in CAPTURED
                                   if c["tts_path"] and Path(c["tts_path"]).is_file()
                                   and Path(c["tts_path"]).stat().st_size == 0),
        })

        # 断言
        # 插桩自身要先可信：抓到 0 段时，下面所有"该有旁白"的断言都会空转通过
        if rec["segments_captured"] != rec["segments"]:
            failures.append(f"{mode}: 插桩只覆盖 {rec['segments_captured']}/{rec['segments']} 段"
                            "——本行结果不可信，先修门禁再下结论")
        if not rec["has_audio"]:
            failures.append(f"{mode}: 成片无音轨")
        if rec["mean_volume_db"] is None or rec["mean_volume_db"] < MIN_MEAN_VOLUME_DB:
            failures.append(f"{mode}: 近乎静音（mean_volume={rec['mean_volume_db']} dB）")
        budget_max = float(ctx.settings.get("strategy.max_duration_s", "300"))
        budget_min = float(ctx.settings.get("strategy.min_duration_s", "30"))
        if not budget_min <= rec["duration_s"] <= budget_max:
            failures.append(f"{mode}: 时长 {rec['duration_s']}s 超出预算 [{budget_min:.0f},{budget_max:.0f}]")
        if rec["max_freeze_s"] >= MAX_FREEZE_S:
            failures.append(f"{mode}: 存在 {rec['max_freeze_s']}s 冻结画面")
        wants_tts = sum(1 for c in CAPTURED if c["audio"] in ("narration", "ducked"))
        if mode == "raw_clip":
            if wants_tts or rec["segments_mixed"]:
                failures.append(f"{mode}: 纯原片不该混入旁白（零加工原则）")
        else:
            planned = sum(v for k, v in roles.items() if k in ("narration", "ducked"))
            if planned == 0:
                failures.append(f"{mode}: 编排里没有任何旁白段（音频角色={roles}）")
            elif rec["segments_with_tts"] == 0:
                failures.append(
                    f"{mode}: 应有 {planned} 段旁白，实际混入 0 段 —— "
                    f"TTS 产出 {rec['tts_files_ok']}/{rec['narration_texts']} 个可用音频文件"
                    + ("（TTS 未出声，属环境问题）" if rec["tts_files_ok"] == 0
                       else "（TTS 出了音频却没接到段上，属管道断链）"))
            elif rec["segments_with_tts"] != wants_tts:
                failures.append(f"{mode}: {wants_tts} 段该有旁白，实际 {rec['segments_with_tts']} 段拿到")
        if rec["tts_files_missing"] or rec["tts_files_empty"]:
            failures.append(f"{mode}: 旁白音频文件缺失/为空 "
                            f"(missing={rec['tts_files_missing']}, empty={rec['tts_files_empty']})")
        rows.append(rec)

    executor.shutdown(wait=True, cancel_futures=True)

    print(f"{'模式':<18}{'状态':<11}{'时长s':>8}{'均量dB':>9}{'冻结s':>7}"
          f"{'来源':>10}{'段':>4}{'插桩':>5}{'TTS':>5}{'带旁白':>7}{'已混音':>7}{'耗时s':>7}")
    print("-" * 104)
    for r in rows:
        print(f"{r['mode']:<18}{r['status']:<11}{r.get('duration_s', 0):>8}"
              f"{(r.get('mean_volume_db') if r.get('mean_volume_db') is not None else 0):>9}"
              f"{r.get('max_freeze_s', 0):>7}{r.get('planner', '-')!s:>10}"
              f"{r.get('segments', 0):>4}{r.get('segments_captured', 0):>5}"
              f"{r.get('tts_files_ok', 0):>5}{r.get('segments_with_tts', 0):>7}"
              f"{r.get('segments_mixed', 0):>7}{r.get('elapsed_s', 0):>7}")
        if r.get("audio_roles"):
            print(f"{'':<29}音频角色：{r['audio_roles']}")

    (out_dir / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    print(f"\n明细：{out_dir / 'summary.json'}")
    if failures:
        print("\n失败：")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("\n全部断言通过。")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
