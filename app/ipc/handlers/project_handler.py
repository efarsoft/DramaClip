"""
项目管理 Handler
处理项目创建、打开、删除、视频导入等操作
"""

import os
from typing import Any, Dict, List

from loguru import logger

from app.services.project.manager_sqlite import get_manager
from app.ipc.protocol import RPCError


def project_list() -> List[Dict]:
    """获取所有项目列表"""
    logger.info("[Project] Listing all projects")
    manager = get_manager()
    projects = manager.list_projects()
    result = [p.to_dict() for p in projects]
    logger.info(f"[Project] Found {len(result)} projects")
    return result


def project_create(name: str, path: str) -> Dict:
    """创建新项目

    Args:
        name: 项目名称
        path: 项目路径（可选，为空时使用默认路径）

    Returns:
        创建的项目信息字典
    """
    logger.info(f"[Project] Creating project: name={name!r}, path={path!r}")
    if not name:
        raise RPCError(-32602, "项目名称不能为空")

    if not path:
        path = os.path.expanduser("~/DramaClipProjects")

    manager = get_manager()
    project = manager.create_project(name, path)
    logger.info(f"[Project] Created project: {name} ({project.id})")
    return project.to_dict()


def project_open(project_id: str) -> Dict:
    """打开项目，自动扫描视频目录

    Args:
        project_id: 项目ID

    Returns:
        项目信息及视频列表
    """
    logger.info(f"[Project] Opening project: {project_id}")
    if not project_id:
        raise RPCError(-32602, "project_id is required")

    try:
        manager = get_manager()
        project = manager.open_project(project_id)

        if not project:
            raise RPCError(-32001, f"Project not found: {project_id}")

        logger.info(f"[Project] Opened project: {project_id}")

        videos = manager.get_videos(project_id)
        result = project.to_dict()
        result["videos"] = [v.to_dict() for v in videos]
        return result
    except RPCError:
        raise
    except Exception as e:
        logger.exception(f"[Project] Failed to open project {project_id}: {e}")
        raise RPCError(-32003, f"Failed to open project: {str(e)}")


def project_delete(project_id: str, keep_files: bool = False) -> Dict:
    """删除项目

    Args:
        project_id: 项目ID
        keep_files: 是否保留项目文件

    Returns:
        删除结果
    """
    logger.info(f"[Project] Deleting project: {project_id}, keep_files={keep_files}")
    if not project_id:
        raise RPCError(-32602, "project_id is required")

    manager = get_manager()
    success = manager.delete_project(project_id, keep_files)

    if not success:
        raise RPCError(-32001, f"Project not found: {project_id}")

    logger.info(f"[Project] Deleted project: {project_id}")
    return {"success": True}


def project_rename(project_id: str, new_name: str) -> Dict:
    """重命名项目

    Args:
        project_id: 项目ID
        new_name: 新项目名称

    Returns:
        更新后的项目信息
    """
    logger.info(f"[Project] Renaming project: {project_id} -> {new_name}")
    if not project_id:
        raise RPCError(-32602, "project_id is required")
    if not new_name:
        raise RPCError(-32602, "new_name is required")

    manager = get_manager()
    project = manager.rename_project(project_id, new_name)

    if not project:
        raise RPCError(-32001, f"Project not found: {project_id}")

    logger.info(f"[Project] Renamed project: {project_id} -> {new_name}")
    return project.to_dict()


def project_import_videos(project_id: str, paths: List[str]) -> List[Dict]:
    """导入视频文件到项目

    Args:
        project_id: 项目ID
        paths: 视频文件路径列表

    Returns:
        导入的视频列表
    """
    logger.info(f"[Project] Importing videos: project={project_id}, count={len(paths)}")
    if not project_id:
        raise RPCError(-32602, "project_id is required")
    if not paths:
        return []

    manager = get_manager()
    videos = manager.import_videos(project_id, paths)
    logger.info(f"[Project] Imported {len(videos)} videos to project {project_id}")
    return [v.to_dict() for v in videos]


def project_get_videos(project_id: str, order_by: str = "sort_order") -> List[Dict]:
    """获取项目的视频列表

    Args:
        project_id: 项目ID
        order_by: 排序字段，可选 "sort_order"（默认）、"name"、"duration"、"size"

    Returns:
        视频列表
    """
    logger.info(f"[Project] Getting videos: project={project_id}, order_by={order_by}")
    if not project_id:
        raise RPCError(-32602, "project_id is required")

    manager = get_manager()
    videos = manager.get_videos(project_id, order_by=order_by)
    return [v.to_dict() for v in videos]


def project_update_video_order(video_orders: List[Dict[str, Any]]) -> int:
    """批量更新视频排序

    Args:
        video_orders: 视频排序列表，格式: [{"id": "video_id", "sort_order": 0}, ...]

    Returns:
        更新的记录数
    """
    logger.info(f"[Project] Updating video order: count={len(video_orders)}")
    if not video_orders:
        return 0

    manager = get_manager()
    return manager.update_video_order(video_orders)
