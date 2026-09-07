"""project 命名空间：create / list / get / delete / scan_episodes。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.infra.ffmpeg import cover as cover_engine
from dramaclip.infra.ffmpeg import probe
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_PROJECT_NOT_FOUND = -32101
_ERR_SOURCE_INVALID = -32102
_ERR_NO_EPISODES = -32103

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".webm", ".flv"}

_NATURAL_KEY_PATTERN = re.compile(r"(\d+)")


def register(router: Router, context: AppContext) -> None:
    router.register("project.create", lambda params: create(context, params))
    router.register("project.list", lambda _params: list_all(context))
    router.register("project.get", lambda params: get(context, params))
    router.register("project.delete", lambda params: delete(context, params))
    router.register("project.rename", lambda params: rename(context, params))
    router.register("project.duplicate", lambda params: duplicate(context, params))
    router.register("project.scan_episodes", lambda params: scan_episodes(context, params))
    router.register("project.dashboard_summary", lambda _params: dashboard_summary(context))
    router.register("project.ensure_covers", lambda params: ensure_covers(context, params))


def create(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name", "")).strip()
    source_path = str(params.get("source_path", "")).strip()
    if not name or not source_path:
        raise RpcDomainError(_ERR_SOURCE_INVALID, "name 与 source_path 必填")
    directory = Path(source_path)
    if not directory.is_dir():
        raise RpcDomainError(_ERR_SOURCE_INVALID, f"目录不存在：{source_path}")
    return projects_repo.create(context.conn, name, source_path)


def list_all(context: AppContext) -> list[dict[str, Any]]:
    return projects_repo.list_all(context.conn)


def get(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    project_id = str(params.get("project_id", ""))
    project = projects_repo.get(context.conn, project_id)
    if project is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    return {"project": project, "episodes": episodes_repo.list_by_project(context.conn, project_id)}


def delete(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    project_id = str(params.get("project_id", ""))
    if not projects_repo.delete(context.conn, project_id):
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    return {"ok": True}


def rename(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    project_id = str(params.get("project_id", ""))
    name = str(params.get("name", "")).strip()
    if not name:
        raise RpcDomainError(_ERR_SOURCE_INVALID, "项目名不能为空")
    if not projects_repo.rename(context.conn, project_id, name):
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    return projects_repo.get(context.conn, project_id) or {}


def duplicate(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    project_id = str(params.get("project_id", ""))
    source = projects_repo.get(context.conn, project_id)
    if source is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    created = projects_repo.duplicate(context.conn, project_id, f"{source['name']}（副本）")
    return created or {}


def dashboard_summary(context: AppContext) -> dict[str, int]:
    return projects_repo.summary(context.conn)


def scan_episodes(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """扫描项目目录：视频文件自然排序 → ffprobe 逐个 → 全量替换 episodes。"""
    project_id = str(params.get("project_id", ""))
    project = projects_repo.get(context.conn, project_id)
    if project is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    videos = sorted(
        (p for p in Path(project["source_path"]).iterdir() if _is_video(p)),
        key=lambda path: natural_key(path.name),
    )
    if not videos:
        raise RpcDomainError(_ERR_NO_EPISODES, f"目录中没有视频文件：{project['source_path']}")

    scanned: list[dict[str, Any]] = []
    for number, video in enumerate(videos, start=1):
        media = probe.probe(video)
        scanned.append(
            {
                "episode_number": number,
                "name": video.stem,
                "source_path": str(video),
                "duration": round(media.duration_s, 3),
                "size_bytes": video.stat().st_size,
            }
        )
    episodes_repo.replace_all(context.conn, project_id, scanned)
    _ensure_cover(context, project)
    return scanned


def ensure_covers(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """为缺封面的项目补截帧（幂等；已有封面的项目跳过）。"""
    generated = 0
    for project in projects_repo.list_all(context.conn):
        if project["cover_path"] is not None and Path(str(project["cover_path"])).is_file():
            continue
        if _ensure_cover(context, project):
            generated += 1
    return {"ok": True, "generated": generated}


def _ensure_cover(context: AppContext, project: dict[str, Any]) -> bool:
    """从第一集视频截帧生成封面；无集/截帧失败返回 False。"""
    project_id = str(project["id"])
    episodes = episodes_repo.list_by_project(context.conn, project_id)
    if not episodes:
        return False
    first = min(episodes, key=lambda ep: int(ep["episode_number"]))
    cover_dir = context.work_dir.parent / "covers"
    cover_dir.mkdir(parents=True, exist_ok=True)
    out_path = cover_dir / f"{project_id}.jpg"
    if not cover_engine.extract_cover(Path(str(first["source_path"])), out_path):
        return False
    projects_repo.set_cover(context.conn, project_id, str(out_path))
    return True


def _is_video(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in _VIDEO_EXTENSIONS


def natural_key(text: str) -> list[int | str]:
    """数字感知排序键：ep2 < ep10。纯函数可单测。"""
    return [int(part) if part.isdigit() else part for part in _NATURAL_KEY_PATTERN.split(text)]
