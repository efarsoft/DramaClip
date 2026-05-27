"""
项目服务管理器 - SQLite 版本
使用 SQLite 替代 JSON 文件存储
"""

import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from loguru import logger

from app.utils.ffmpeg_utils import get_ffprobe_path
from .database import get_database, Database as DatabaseType


def _probe_video_duration(video_path: str) -> float:
    """使用 ffprobe 获取视频时长（秒），失败时返回 0.0"""
    try:
        result = subprocess.run(
            [
                get_ffprobe_path(), "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        val = result.stdout.strip()
        return float(val) if val else 0.0
    except Exception as exc:
        logger.debug(f"ffprobe duration failed for {video_path}: {exc}")
        return 0.0


class ProjectMeta(BaseModel):
    """项目元数据模型"""
    id: str
    name: str
    path: str
    created_at: str
    updated_at: str
    episode_count: int = 0
    status: str = "idle"
    sync_result: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict:
        result = self.model_dump()
        # 移除 sync_result，不存入数据库
        result.pop("sync_result", None)
        return result


class VideoInfo(BaseModel):
    """视频信息模型"""
    id: str
    name: str
    path: str
    size: int = 0
    duration: float = 0.0
    format: str = ""
    sort_order: int = 0
    imported_at: str = ""

    def to_dict(self) -> Dict:
        return self.model_dump()


class ProjectManager:
    """
    项目管理器 - SQLite 版本
    处理项目的创建、读取、更新、删除操作
    """

    VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.webm', '.flv'}

    def __init__(self, db: Optional[DatabaseType] = None):
        """
        初始化项目管理器
        
        Args:
            db: 可选的数据库实例，如果不提供则使用全局实例
        """
        self.db = db if db is not None else get_database()

    def list_projects(self) -> List[ProjectMeta]:
        """列出所有项目"""
        projects_data = self.db.list_projects()
        return [ProjectMeta(**p) for p in projects_data]

    def get_project(self, project_id: str) -> Optional[ProjectMeta]:
        """获取指定项目"""
        logger.debug(f"[DB] Looking for project {project_id}")
        project_data = self.db.get_project(project_id)
        if project_data:
            # 实时同步视频数量
            video_count = self.db.get_video_count(project_id)
            if project_data.get("episode_count", 0) != video_count:
                project_data["episode_count"] = video_count
                self.db.update_project(project_id, {"episode_count": video_count})
            logger.debug(f"[DB] Found project: {project_data['name']}")
            return ProjectMeta(**project_data)
        logger.warning(f"[DB] Project {project_id} NOT FOUND")
        return None

    def get_project_by_path(self, path: str) -> Optional[ProjectMeta]:
        """通过路径获取项目"""
        project_data = self.db.get_project_by_path(path)
        if project_data:
            return ProjectMeta(**project_data)
        return None

    def create_project(self, name: str, path: str) -> ProjectMeta:
        """
        创建新项目

        Args:
            name: 项目名称
            path: 项目存储路径（父目录）

        Returns:
            创建的项目元数据
        """
        if not name or not name.strip():
            raise ValueError('Project name cannot be empty')

        project_id = str(uuid.uuid4())
        project_path = Path(path) / name

        # 创建项目目录
        project_path.mkdir(parents=True, exist_ok=True)

        # 创建子目录
        (project_path / "videos").mkdir(exist_ok=True)
        (project_path / "analysis").mkdir(exist_ok=True)
        (project_path / "clips").mkdir(exist_ok=True)
        (project_path / "output").mkdir(exist_ok=True)

        # 创建项目元数据
        now = datetime.now().isoformat()
        project = ProjectMeta(
            id=project_id,
            name=name,
            path=str(project_path),
            created_at=now,
            updated_at=now,
            episode_count=0,
            status="idle"
        )

        # 保存项目元数据到 meta.json（兼容性）
        meta_file = project_path / "meta.json"
        meta_file.write_text(
            json.dumps(project.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # 保存到数据库
        self.db.create_project(project.to_dict())

        logger.info(f"[DB] Created project: {name} ({project_id})")
        return project

    def open_project(self, project_id: str) -> Optional[ProjectMeta]:
        """打开项目，自动扫描 videos/ 目录索引视频资源"""
        logger.debug(f"[DB] Attempting to open project {project_id}")
        
        project = self.get_project(project_id)
        if not project:
            logger.error(f"[DB] Project {project_id} not found!")
            return None
        
        logger.debug(f"[DB] Found project {project.name} at {project.path}")

        project_path = Path(project.path)
        videos_dir = project_path / "videos"
        
        sync_result = {"found": 0, "removed": 0, "missing": 0}
        
        # 自动扫描视频目录，更新视频索引
        if videos_dir.exists():
            sync_result = self._scan_videos_dir(project_id, videos_dir)

        # 无论是否扫描，都同步实际的视频数量，保证 episode_count 在以任意方式导入后都能保持最新且与数据库强一致
        video_count = self.db.get_video_count(project_id)
        project.episode_count = video_count
        self.db.update_project(project_id, {"episode_count": video_count})

        # 更新最后访问时间
        project.updated_at = datetime.now().isoformat()
        self.db.update_project(project_id, {"updated_at": project.updated_at})
        
        # 更新 meta.json（兼容性）
        self._save_meta(project)

        # 将同步结果存到 project 上
        project.sync_result = sync_result

        logger.info(f"[DB] Opened project: {project_id} with {project.episode_count} episodes")
        return project

    def _save_meta(self, project: ProjectMeta) -> None:
        """保存项目元数据到 meta.json"""
        try:
            meta_file = Path(project.path) / "meta.json"
            meta_file.write_text(
                json.dumps(project.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except (OSError, PermissionError) as e:
            logger.error(f"Failed to save project meta: {e}")

    def _scan_videos_dir(self, project_id: str, videos_dir: Path) -> Dict[str, int]:
        """
        扫描视频目录（可选功能）
        
        注意：现在 videos/ 目录是可选的，主要用于用户想把视频放在项目目录下的场景
        大部分情况下用户直接导入外部文件，不需要扫描
        """
        # 如果 videos/ 目录不存在，跳过扫描
        if not videos_dir.exists():
            logger.debug(f"[DB] Videos directory not exists, skip scan: {videos_dir}")
            return {"found": 0, "removed": 0, "missing": 0}
        
        found_count = 0
        scanned_paths = set()
        
        # 获取数据库中已有的视频
        existing_videos = self.db.get_videos(project_id)
        existing_paths = {v["path"]: v for v in existing_videos}
        
        # 扫描目录 (只扫描当前目录)
        try:
            for file_path in videos_dir.glob("*"):  # 非递归扫描
                if file_path.is_file() and file_path.suffix.lower() in self.VIDEO_EXTENSIONS:
                    str_path = str(file_path)
                    scanned_paths.add(str_path)
                    
                    if str_path not in existing_paths:
                        # 新发现的视频
                        video_id = str(uuid.uuid4())
                        now = datetime.now().isoformat()
                        
                        try:
                            file_size = file_path.stat().st_size
                        except (OSError, PermissionError):
                            file_size = 0
                        
                        video_info = {
                            "id": video_id,
                            "project_id": project_id,
                            "name": file_path.stem,
                            "path": str_path,
                            "size": file_size,
                            "duration": 0.0,
                            "format": file_path.suffix.lstrip(".").lower(),
                            "imported_at": now,
                            "metadata": {}
                        }
                        
                        self.db.add_video(video_info)
                        found_count += 1
                        logger.info(f"[DB] Discovered new video: {file_path.name}")
        except (OSError, PermissionError) as e:
            logger.error(f"Failed to scan videos directory: {e}")
        
        # 检查缺失的视频（标记为 missing，但不删除）
        missing_count = 0
        for path in scanned_paths:
            if not Path(path).exists():
                missing_count += 1
        
        # 更新项目视频数量
        video_count = self.db.get_video_count(project_id)
        self.db.update_project(project_id, {"episode_count": video_count})
        
        if found_count > 0 or missing_count > 0:
            logger.info(
                f"[DB] Sync result for {project_id}: "
                f"+{found_count} new, {missing_count} missing"
            )
        
        return {
            "found": found_count,
            "removed": 0,
            "missing": missing_count,
        }

    def update_project(self, project_id: str, updates: Dict[str, Any]) -> Optional[ProjectMeta]:
        """更新项目元数据"""
        result = self.db.update_project(project_id, updates)
        if result:
            return ProjectMeta(**result)
        return None

    def delete_project(self, project_id: str, keep_files: bool = False) -> bool:
        """删除项目"""
        project = self.get_project(project_id)
        if not project:
            return False

        # 从数据库删除（级联删除视频）
        self.db.delete_project(project_id)

        # 删除项目文件
        if not keep_files:
            project_path = Path(project.path)
            if project_path.exists():
                shutil.rmtree(project_path)
                logger.info(f"[DB] Deleted project files: {project_path}")

        logger.info(f"[DB] Deleted project: {project_id}")
        return True

    def rename_project(self, project_id: str, new_name: str) -> Optional[ProjectMeta]:
        """重命名项目"""
        project = self.get_project(project_id)
        if not project:
            return None

        project.name = new_name
        project.updated_at = datetime.now().isoformat()
        
        self.db.update_project(project_id, {
            "name": new_name,
            "updated_at": project.updated_at
        })
        
        # 更新 meta.json
        self._save_meta(project)

        logger.info(f"[DB] Renamed project: {project_id} -> {new_name}")
        return project

    def import_videos(self, project_id: str, video_paths: List[str]) -> List[VideoInfo]:
        """
        导入视频文件到项目
        
        注意：只记录原始路径，不复制/移动文件
        对于大文件的视频场景更高效
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        # 获取当前视频数量，用于设置 sort_order
        current_videos = self.db.get_videos(project_id)
        next_order = len(current_videos)

        # 展开所有文件夹，扫描并去重/排序视频文件
        expanded_paths = []
        for video_path in video_paths:
            src_path = Path(video_path)
            if not src_path.exists():
                logger.warning(f"Video file/folder not found: {video_path}")
                continue

            if src_path.is_dir():
                # 只读取当前选择目录的文件夹，不需要读取子目录相关视频
                dir_videos = []
                for sub_path in src_path.glob("*"):
                    if sub_path.is_file() and sub_path.suffix.lower() in self.VIDEO_EXTENSIONS:
                        dir_videos.append(sub_path)
                # 对该目录下的视频路径进行排序，保证按文件名顺序导入
                dir_videos.sort(key=lambda p: str(p))
                expanded_paths.extend(dir_videos)
            else:
                if src_path.suffix.lower() in self.VIDEO_EXTENSIONS:
                    expanded_paths.append(src_path)
                else:
                    logger.warning(f"Skipping unsupported format: {video_path}")

        imported = []
        for src_path in expanded_paths:
            video_id = str(uuid.uuid4())
            now = datetime.now().isoformat()

            try:
                # 直接记录原始路径，不复制文件
                video_info = {
                    "id": video_id,
                    "project_id": project_id,
                    "name": src_path.stem,
                    "path": str(src_path.resolve()),  # 使用绝对路径
                    "size": src_path.stat().st_size,
                    "duration": _probe_video_duration(str(src_path)),
                    "format": src_path.suffix.lstrip(".").lower(),
                    "sort_order": next_order,  # 设置排序值
                    "imported_at": now,
                    "metadata": {}
                }
                
                self.db.add_video(video_info)
                imported.append(VideoInfo(**video_info))
                logger.info(f"[DB] Imported video: {src_path.name} (order: {next_order})")
                next_order += 1
                
            except Exception as e:
                logger.error(f"Failed to import {src_path}: {e}")

        # 更新项目视频数量
        video_count = self.db.get_video_count(project_id)
        self.db.update_project(project_id, {"episode_count": video_count})

        return imported

    def get_videos(self, project_id: str, order_by: str = "sort_order") -> List[VideoInfo]:
        """获取项目的视频列表
        
        Args:
            project_id: 项目ID
            order_by: 排序字段，可选 "sort_order"（默认）、"name"、"duration"、"size"
        """
        videos_data = self.db.get_videos(project_id, order_by=order_by)
        return [VideoInfo(**v) for v in videos_data]
    
    def update_video_order(self, video_orders: List[Dict[str, Any]]) -> int:
        """批量更新视频排序
        
        Args:
            video_orders: [{"id": "video_id", "sort_order": 0}, ...]
        
        Returns:
            更新的记录数
        """
        return self.db.update_video_order(video_orders)


# 全局单例
_manager: Optional[ProjectManager] = None


def get_manager() -> ProjectManager:
    """获取全局项目管理器"""
    global _manager
    if _manager is None:
        _manager = ProjectManager()
    return _manager
