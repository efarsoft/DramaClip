"""
异步导出 Handler
P0 核心：使用 asyncio 实现 FFmpeg 异步执行，提升导出体验

优化点：
1. FFmpeg 使用异步子进程执行，避免阻塞
2. 实时读取进度，避免长等待
3. 支持取消操作
"""

import asyncio
import subprocess as sp
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from loguru import logger

from app.services.project.manager_sqlite import get_manager
from app.utils.ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path
from .base import (
    get_worker_pool,
    get_clip_task,
    update_export_task,
    get_export_task,
    RESOLUTION_MAP,
    BITRATE_MAP,
)
from app.ipc.protocol import RPCError


async def _run_export_pipeline_async(
    task_id: str,
    input_path: str,
    output_path: str,
    preset: str,
    fmt: str,
    fps: int,
    progress_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    异步执行 FFmpeg 转码

    Args:
        task_id: 任务ID
        input_path: 输入文件路径
        output_path: 输出文件路径
        preset: 质量预设
        fmt: 输出格式
        fps: 帧率
        progress_callback: 进度回调

    Returns:
        执行结果
    """
    try:
        # 获取视频时长
        update_export_task(task_id, progress=5, phase="probe", message="探测视频信息...")

        probe = await asyncio.create_subprocess_exec(
            get_ffprobe_path(), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        probe_output, probe_err = await probe.wait()
        total_duration = 1.0

        if probe_output:
            try:
                total_duration = float(probe_output.decode().strip())
            except ValueError:
                total_duration = 1.0

        w, h = RESOLUTION_MAP.get(preset, ("1920", "1080"))
        vbitrate = BITRATE_MAP.get(preset, "8M")

        update_export_task(
            task_id, progress=10, phase="transcode",
            message=f"转码中（{w}×{h}）..."
        )

        ffmpeg_path = get_ffmpeg_path()

        if fmt == "gif":
            # GIF 生成需要两步
            palette_path = output_path.replace(".gif", "_palette.png")

            # 第一步：生成调色板
            update_export_task(task_id, progress=15, phase="transcode", message="生成调色板...")
            await asyncio.create_subprocess_exec(
                ffmpeg_path, "-y", "-i", input_path,
                "-vf", f"fps={fps},scale={w}:{h}:flags=lanczos,palettegen",
                palette_path,
            )

            # 第二步：生成 GIF
            update_export_task(task_id, progress=50, phase="transcode", message="生成 GIF...")
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_path, "-y", "-i", input_path, "-i", palette_path,
                "-filter_complex", f"fps={fps},scale={w}:{h}:flags=lanczos[x];[x][1:v]paletteuse",
                output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()

        else:
            # 视频转码
            cmd = [
                ffmpeg_path, "-y", "-i", input_path,
                "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                       f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
                "-r", str(fps),
                "-b:v", vbitrate,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                "-progress", "pipe:1",
                "-nostats",
                output_path,
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            # 实时读取进度
            current_time = 0.0
            last_lines = []
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break

                line_text = line.decode('utf-8', errors='ignore').strip()
                if not line_text:
                    continue
                last_lines.append(line_text)
                if len(last_lines) > 100:
                    last_lines.pop(0)

                if line_text.startswith("out_time_ms="):
                    try:
                        ms = int(line_text.split("=")[1])
                        current_time = ms / 1_000_000
                        pct = min(int(current_time / total_duration * 85) + 10, 95)
                        update_export_task(
                            task_id, progress=pct, phase="transcode",
                            message=f"转码 {int(current_time)}/{int(total_duration)}s",
                        )
                    except (ValueError, IndexError):
                        pass

            # 等待进程结束
            returncode = await proc.wait()

            if returncode != 0:
                stderr_out = "\n".join(last_lines[-30:])
                raise RuntimeError(f"FFmpeg 退出码 {returncode}: {stderr_out}")

        update_export_task(
            task_id, status="completed", progress=100,
            phase="done", message="导出完成",
            output_path=output_path,
        )
        logger.info(f"[Export] Task {task_id} completed: {output_path}")

        return {
            "success": True,
            "output_path": output_path,
            "task_id": task_id,
        }

    except asyncio.CancelledError:
        update_export_task(
            task_id, status="cancelled", progress=0,
            phase="cancelled", message="导出已取消"
        )
        logger.info(f"[Export] Task {task_id} cancelled")
        raise

    except Exception as exc:
        logger.exception(f"[Export] Task {task_id} failed: {exc}")
        update_export_task(
            task_id, status="failed", progress=-1,
            phase="error", message=str(exc)
        )
        return {
            "success": False,
            "error": str(exc),
            "task_id": task_id,
        }


def _run_export_pipeline_single(
    task_id: str,
    input_path: str,
    output_path: str,
    preset: str,
    fmt: str,
    fps: int,
    start_pct: int = 10,
    end_pct: int = 95,
) -> None:
    """内部辅助方法：执行单个视频转码的完整 FFmpeg 同步调用，支持指定进度区间"""
    probe = sp.run(
        [get_ffprobe_path(), "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1",
         input_path],
        capture_output=True, text=True, timeout=30,
    )
    total_duration = float(probe.stdout.strip() or 0) or 1.0

    w, h = RESOLUTION_MAP.get(preset, ("1920", "1080"))
    vbitrate = BITRATE_MAP.get(preset, "8M")

    ffmpeg_path = get_ffmpeg_path()
    if fmt == "gif":
        palette_path = output_path.replace(".gif", "_palette.png")
        sp.run([
            ffmpeg_path, "-y", "-i", input_path,
            "-vf", f"fps={fps},scale={w}:{h}:flags=lanczos,palettegen",
            palette_path,
        ], capture_output=True, timeout=120)
        cmd = [
            ffmpeg_path, "-y", "-i", input_path, "-i", palette_path,
            "-filter_complex", f"fps={fps},scale={w}:{h}:flags=lanczos[x];[x][1:v]paletteuse",
            output_path,
        ]
    else:
        cmd = [
            ffmpeg_path, "-y", "-i", input_path,
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                   f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
            "-r", str(fps),
            "-b:v", vbitrate,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            output_path,
        ]

    proc = sp.Popen(
        cmd,
        stdout=sp.PIPE, stderr=sp.STDOUT,
        text=True, bufsize=1,
        encoding='utf-8', errors='ignore',
    )

    current_time = 0.0
    last_lines = []
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        last_lines.append(line)
        if len(last_lines) > 100:
            last_lines.pop(0)

        if line.startswith("out_time_ms="):
            try:
                ms = int(line.split("=")[1])
                current_time = ms / 1_000_000
                ratio = min(current_time / total_duration, 1.0)
                pct = start_pct + int(ratio * (end_pct - start_pct))
                update_export_task(
                    task_id, progress=pct, phase="transcode",
                    message=f"转码 {int(current_time)}/{int(total_duration)}s",
                )
            except (ValueError, IndexError):
                pass

    proc.wait()
    if proc.returncode != 0:
        stderr_out = "\n".join(last_lines[-30:])
        raise RuntimeError(f"FFmpeg 退出码 {proc.returncode}: {stderr_out}")


def _run_export_pipeline(
    task_id: str,
    input_path: str,
    output_path: str,
    preset: str,
    fmt: str,
    fps: int,
) -> None:
    """后台线程：调用 FFmpeg 进行转码/封装"""
    try:
        update_export_task(task_id, progress=5, phase="probe", message="探测视频信息...")
        _run_export_pipeline_single(task_id, input_path, output_path, preset, fmt, fps, start_pct=10, end_pct=95)

        update_export_task(
            task_id, status="completed", progress=100,
            phase="done", message="导出完成",
            output_path=output_path,
        )
        logger.info(f"[Export] Task {task_id} completed: {output_path}")

    except Exception as exc:
        logger.exception(f"[Export] Task {task_id} failed: {exc}")
        update_export_task(task_id, status="failed", progress=-1, phase="error", message=str(exc))


def _run_triple_export_pipeline(
    task_id: str,
    all_inputs: List[str],
    output_dir: str,
    preset: str,
    fmt: str,
    fps: int,
) -> None:
    """一键三连后台线程：顺序导出三个不同风格版本的视频"""
    try:
        names = ["original", "hybrid", "full"]
        outputs = []
        for inp, name in zip(all_inputs, names):
            out_file = Path(output_dir) / f"export_{task_id[:8]}_{name}.{fmt}"
            outputs.append(str(out_file))

        logger.info(f"[Export] 一键三连导出目标: {outputs}")

        # 1. 导出【原片解说】
        update_export_task(task_id, progress=10, phase="transcode", message="正在转码第 1/3 个视频：原片解说...")
        _run_export_pipeline_single(task_id, all_inputs[0], outputs[0], preset, fmt, fps, start_pct=10, end_pct=40)

        # 2. 导出【交叉解说】
        update_export_task(task_id, progress=40, phase="transcode", message="正在转码第 2/3 个视频：交叉解说...")
        _run_export_pipeline_single(task_id, all_inputs[1], outputs[1], preset, fmt, fps, start_pct=40, end_pct=70)

        # 3. 导出【全片解说】
        update_export_task(task_id, progress=70, phase="transcode", message="正在转码第 3/3 个视频：全片解说...")
        _run_export_pipeline_single(task_id, all_inputs[2], outputs[2], preset, fmt, fps, start_pct=70, end_pct=95)

        update_export_task(
            task_id, status="completed", progress=100,
            phase="done", message="一键三连视频导出全部完成！",
            output_path=outputs[0],
        )
        logger.info(f"[Export] 一键三连视频导出全部成功: {outputs}")

    except Exception as exc:
        logger.exception(f"[Export] 一键三连导出任务 {task_id} 失败: {exc}")
        update_export_task(task_id, status="failed", progress=-1, phase="error", message=str(exc))


def export_start(project_id: str, output_config: Dict[str, Any]) -> Dict:
    """开始导出

    Args:
        project_id: 项目ID
        output_config: 导出配置

    Returns:
        导出任务ID和状态
    """
    export_task_id = str(uuid.uuid4())

    clip_task_id: str = output_config.get("clip_task_id", "")
    preset: str = output_config.get("preset", "1080p")
    fmt: str = output_config.get("format", "mp4")
    fps: int = int(output_config.get("fps", 30))
    custom_output_path: str = output_config.get("output_path", "")

    input_path = ""
    all_outputs = []
    if clip_task_id:
        clip_task = get_clip_task(clip_task_id)
        if clip_task:
            input_path = clip_task.get("output_path", "")
            # 检查是否为一键三连生成任务，读取关联的所有输出版本
            if clip_task.get("result") and "all_outputs" in clip_task["result"]:
                all_outputs = clip_task["result"]["all_outputs"]

    if not input_path:
        input_path = output_config.get("input_path", "")

    if not input_path and not all_outputs:
        raise RPCError(-32602, "无法确定导出源文件，请提供 clip_task_id 或 input_path")

    mgr = get_manager()
    project = mgr.get_project(project_id)
    if not project:
        raise RPCError(-32001, f"Project not found: {project_id}")

    from app.utils.path_manager import get_path_manager
    path_mgr = get_path_manager()
    
    # 彻底解决污染项目源码目录的问题，将导出视频默认存放至系统设置配置的统一“输出目录”下
    export_dir = path_mgr.output_root / project_id / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    if all_outputs:
        output_path = str(export_dir / f"export_{export_task_id[:8]}_original.{fmt}")
        
        # 更新项目状态为 exporting，并在任务创建时关联项目ID
        mgr.update_project(project_id, {"status": "exporting"})
        update_export_task(export_task_id, status="running", progress=0, phase="preparing", message="准备一键三连导出...", project_id=project_id)

        # 启动一键三连导出流水线
        get_worker_pool().submit(
            _run_triple_export_pipeline,
            export_task_id, all_outputs, str(export_dir), preset, fmt, fps,
        )
    else:
        if custom_output_path:
            output_path = custom_output_path
        else:
            output_path = str(export_dir / f"export_{export_task_id[:8]}.{fmt}")

        # 更新项目状态为 exporting，并在任务创建时关联项目ID
        mgr.update_project(project_id, {"status": "exporting"})
        update_export_task(export_task_id, status="running", progress=0, phase="preparing", message="准备导出...", project_id=project_id)

        # 使用线程池执行同步版本
        get_worker_pool().submit(
            _run_export_pipeline,
            export_task_id, input_path, output_path, preset, fmt, fps,
        )

    logger.info(f"[Export] Task {export_task_id} queued. Outputs in: {export_dir}")
    return {
        "task_id": export_task_id,
        "status": "running",
        "output_path": output_path,
    }


def export_get_progress(task_id: str) -> Dict:
    """获取导出进度"""
    task = get_export_task(task_id)
    if not task:
        return {
            "task_id": task_id,
            "status": "running",
            "progress": 0,
            "phase": "preparing",
            "message": "任务已创建，等待启动...",
            "output_path": None,
        }
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "progress": task["progress"],
        "phase": task.get("phase", ""),
        "message": task.get("message", ""),
        "output_path": task.get("output_path"),
    }


def export_cancel(task_id: str) -> Dict:
    """取消导出任务"""
    from app.services.task_manager import get_task_manager

    task_mgr = get_task_manager()
    success = task_mgr.cancel_task(task_id, force=True)

    if success:
        update_export_task(
            task_id,
            status="cancelled",
            progress=0,
            phase="cancelled",
            message="导出已取消",
        )
        logger.info(f"[Export] Task {task_id} cancelled")
        return {"success": True, "task_id": task_id, "message": "导出已取消"}
    else:
        return {"success": False, "task_id": task_id, "message": "取消失败，任务不存在或已完成"}
