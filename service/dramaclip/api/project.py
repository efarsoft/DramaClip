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
_ERR_INVALID_SETTINGS = -32104

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".webm", ".flv"}

_NATURAL_KEY_PATTERN = re.compile(r"(\d+)")


def register(router: Router, context: AppContext) -> None:
    router.register("project.create", lambda params: create(context, params))
    router.register("project.list", lambda _params: list_all(context))
    router.register("project.get", lambda params: get(context, params))
    router.register("project.delete", lambda params: delete(context, params))
    router.register("project.rename", lambda params: rename(context, params))
    router.register("project.update_settings", lambda params: update_settings(context, params))
    router.register("project.duplicate", lambda params: duplicate(context, params))
    router.register("project.scan_episodes", lambda params: scan_episodes(context, params))
    router.register("project.dashboard_summary", lambda _params: dashboard_summary(context))
    router.register("project.ensure_covers", lambda params: ensure_covers(context, params))
    router.register("project.reorder_episodes", lambda params: reorder_episodes(context, params))


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


def update_settings(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """项目级参数覆盖（K / 转写档位 / 风格 / 字幕预设）。null 值=恢复该项默认。"""
    project_id = str(params.get("project_id", ""))
    changes = params.get("settings")
    if not isinstance(changes, dict):
        raise RpcDomainError(_ERR_INVALID_SETTINGS, "settings 必须是对象")
    merged = projects_repo.update_settings(context.conn, project_id, changes)
    if merged is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    return {"project_id": project_id, "settings": merged}


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
    for episode in episodes_repo.list_by_project(context.conn, project_id):
        _ensure_episode_cover(context, episode)
    return scanned


def ensure_covers(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """为缺封面的项目与各集补截帧（幂等；已有封面的跳过）。"""
    generated = 0
    for project in projects_repo.list_all(context.conn):
        if _cover_missing(project["cover_path"]) and _ensure_cover(context, project):
            generated += 1
        for episode in episodes_repo.list_by_project(context.conn, str(project["id"])):
            if _cover_missing(episode["cover_path"]) and _ensure_episode_cover(context, episode):
                generated += 1
    return {"ok": True, "generated": generated}


def reorder_episodes(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """手动排序：按给定 episode_ids 顺序重编号。"""
    project_id = str(params.get("project_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    ordered = params.get("episode_ids")
    if not isinstance(ordered, list):
        raise RpcDomainError(_ERR_SOURCE_INVALID, "episode_ids 必须为数组")
    ok = episodes_repo.reorder(context.conn, project_id, [str(item) for item in ordered])
    if not ok:
        raise RpcDomainError(_ERR_NO_EPISODES, "episode_ids 与项目剧集不一致")
    return {"ok": True}


def _ensure_episode_cover(context: AppContext, episode: dict[str, Any]) -> bool:
    cover_dir = context.data_dir / "covers"
    cover_dir.mkdir(parents=True, exist_ok=True)
    out_path = cover_dir / f"ep_{episode['id']}.jpg"
    if not cover_engine.extract_cover(Path(str(episode["source_path"])), out_path):
        return False
    episodes_repo.set_cover(context.conn, str(episode["id"]), str(out_path))
    return True


def _cover_missing(cover_path: Any) -> bool:
    return cover_path is None or not Path(str(cover_path)).is_file()


def _ensure_cover(context: AppContext, project: dict[str, Any]) -> bool:
    """从第一集视频截帧生成封面；无集/截帧失败返回 False。"""
    project_id = str(project["id"])
    episodes = episodes_repo.list_by_project(context.conn, project_id)
    if not episodes:
        return False
    first = min(episodes, key=lambda ep: int(ep["episode_number"]))
    cover_dir = context.data_dir / "covers"
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
