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
from typing import Any, Dict, Optional, Callable

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
                stderr=asyncio.subprocess.PIPE,
            )

            # 实时读取进度
            current_time = 0.0
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break

                line_text = line.decode().strip()
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
                stderr_out = await proc.stderr.read()
                raise RuntimeError(f"FFmpeg 退出码 {returncode}: {stderr_out.decode()[-300:]}")

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


def _run_export_pipeline(
    task_id: str,
    input_path: str,
    output_path: str,
    preset: str,
    fmt: str,
    fps: int,
) -> None:
    """后台线程：调用 FFmpeg 进行转码/封装（同步版本，保留兼容）"""
    try:
        update_export_task(task_id, progress=5, phase="probe", message="探测视频信息...")

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

        update_export_task(task_id, progress=10, phase="transcode", message=f"转码中（{w}×{h}）...")

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
            stdout=sp.PIPE, stderr=sp.PIPE,
            text=True, bufsize=1,
        )

        current_time = 0.0
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_ms="):
                try:
                    ms = int(line.split("=")[1])
                    current_time = ms / 1_000_000
                    pct = min(int(current_time / total_duration * 85) + 10, 95)
                    update_export_task(
                        task_id, progress=pct, phase="transcode",
                        message=f"转码 {int(current_time)}/{int(total_duration)}s",
                    )
                except (ValueError, IndexError):
                    pass

        proc.wait()
        if proc.returncode != 0:
            stderr_out = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"FFmpeg 退出码 {proc.returncode}: {stderr_out[-300:]}")

        update_export_task(
            task_id, status="completed", progress=100,
            phase="done", message="导出完成",
            output_path=output_path,
        )
        logger.info(f"[Export] Task {task_id} completed: {output_path}")

    except Exception as exc:
        logger.exception(f"[Export] Task {task_id} failed: {exc}")
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
    if clip_task_id:
        clip_task = get_clip_task(clip_task_id)
        if clip_task:
            input_path = clip_task.get("output_path", "")

    if not input_path:
        input_path = output_config.get("input_path", "")

    if not input_path:
        raise RPCError(-32602, "无法确定导出源文件，请提供 clip_task_id 或 input_path")

    if custom_output_path:
        output_path = custom_output_path
    else:
        mgr = get_manager()
        project = mgr.get_project(project_id)
        if not project:
            raise RPCError(-32001, f"Project not found: {project_id}")
        export_dir = Path(project.path) / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(export_dir / f"export_{export_task_id[:8]}.{fmt}")

    update_export_task(export_task_id, status="running", progress=0, phase="preparing", message="准备导出...")

    # 使用线程池执行同步版本（避免阻塞事件循环）
    get_worker_pool().submit(
        _run_export_pipeline,
        export_task_id, input_path, output_path, preset, fmt, fps,
    )

    logger.info(f"[Export] Task {export_task_id} queued: {input_path} -> {output_path}")
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
