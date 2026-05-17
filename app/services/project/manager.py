"""
项目服务管理器
负责项目的 CRUD 操作、元数据管理和视频文件处理
"""

import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from loguru import logger

from app.utils.ffmpeg_utils import get_ffprobe_path


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
    status: str = "idle"  # idle/analyzing/ready/clipping/exporting
    sync_result: Optional[Dict[str, int]] = None  # 打开时自动扫描的结果

    def to_dict(self) -> Dict:
        return self.model_dump()


class VideoInfo(BaseModel):
    """视频信息模型"""
    id: str
    name: str
    path: str
    size: int = 0
    duration: float = 0.0
    format: str = ""
    imported_at: str = ""

    def to_dict(self) -> Dict:
        return self.model_dump()


class ProjectManager:
    """
    项目管理器
    处理项目的创建、读取、更新、删除操作
    """

    VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.webm', '.flv'}

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            base_dir = Path.home() / ".dramaclip"
        self.base_dir = Path(base_dir)
        self.projects_dir = self.base_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.projects_dir / "projects.json"
        self._ensure_index()

    def _ensure_index(self) -> None:
        """确保索引文件存在"""
        if not self.index_file.exists():
            self.index_file.write_text("[]", encoding="utf-8")

    def _load_index(self) -> List[Dict]:
        """加载项目索引"""
        try:
            content = self.index_file.read_text(encoding="utf-8")
            projects = json.loads(content)
            logger.debug(f"[Index] Loaded {len(projects)} projects from {self.index_file}")
            return projects
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in index file: {e}")
            return []
        except (OSError, PermissionError, FileNotFoundError) as e:
            logger.error(f"Failed to read index file: {e}")
            return []

    def _save_index(self, projects: List[Dict]) -> None:
        """保存项目索引"""
        try:
            content = json.dumps(projects, ensure_ascii=False, indent=2)
            self.index_file.write_text(content, encoding="utf-8")
            logger.debug(f"[Index] Saved {len(projects)} projects to {self.index_file}")
        except (OSError, PermissionError) as e:
            logger.error(f"Failed to save index file: {e}")
            raise

    def list_projects(self) -> List[ProjectMeta]:
        """列出所有项目"""
        projects_data = self._load_index()
        return [ProjectMeta(**p) for p in projects_data]

    def get_project(self, project_id: str) -> Optional[ProjectMeta]:
        """获取指定项目"""
        projects = self._load_index()
        logger.debug(f"[Index] Looking for project {project_id}, index has {len(projects)} projects")
        for p in projects:
            if p["id"] == project_id:
                logger.debug(f"[Index] Found project: {p['name']} at {p['path']}")
                return ProjectMeta(**p)
        logger.warning(f"[Index] Project {project_id} NOT FOUND in index")
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

        # 保存项目元数据
        meta_file = project_path / "meta.json"
        meta_file.write_text(
            json.dumps(project.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # 更新索引
        projects = self._load_index()
        logger.debug(f"[Create] Before append: {len(projects)} projects")
        projects.append(project.to_dict())
        logger.debug(f"[Create] After append: {len(projects)} projects, new id={project_id}")
        self._save_index(projects)
        logger.debug(f"[Create] Index saved, verifying...")
        
        # 验证保存是否成功
        verify = self._load_index()
        found = any(p["id"] == project_id for p in verify)
        logger.debug(f"[Create] Verification: project {project_id} in index = {found}")

        logger.info(f"Created project: {name} ({project_id})")
        return project

    def open_project(self, project_id: str) -> Optional[ProjectMeta]:
        """打开项目，自动扫描 videos/ 目录索引视频资源"""
        logger.debug(f"[Open] Attempting to open project {project_id}")
        project = self.get_project(project_id)
        if not project:
            logger.error(f"[Open] Project {project_id} not found!")
            return None
        logger.debug(f"[Open] Found project {project.name} at {project.path}")

        project_path = Path(project.path)
        videos_dir = project_path / "videos"
        
        sync_result = {"found": 0, "removed": 0, "missing": 0}
        # 自动扫描视频目录，更新视频索引
        if videos_dir.exists():
            sync_result = self._scan_videos_dir(project_id, videos_dir)

        # 更新最后访问时间
        project.updated_at = datetime.now().isoformat()
        self._save_meta(project)

        # 更新索引
        projects = self._load_index()
        for i, p in enumerate(projects):
            if p["id"] == project_id:
                projects[i] = project.to_dict()
                break
        self._save_index(projects)

        # 将同步结果存到 project 上，方便 handler 返回
        project.sync_result = sync_result

        logger.info(f"Opened project: {project_id} with {project.episode_count} episodes")
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
            raise

    def _scan_videos_dir(self, project_id: str, videos_dir: Path) -> Dict[str, int]:
        """扫描视频目录，同步 videos.json 索引"""
        project = self.get_project(project_id)
        if not project:
            return {"found": 0, "removed": 0, "missing": 0}

        project_path = Path(project.path)
        videos_file = project_path / "videos.json"
        
        # 读取已存在的视频记录
        if videos_file.exists():
            try:
                existing_videos = json.loads(videos_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing_videos = []
        else:
            existing_videos = []

        # 建立现有记录的路径映射（key 是文件路径）
        existing_map: Dict[str, Dict] = {v.get("path", ""): v for v in existing_videos}

        # 扫描目录中实际的视频文件
        scanned_paths: Set[str] = set()
        found_count = 0

        try:
            dir_iter = videos_dir.iterdir()
        except (OSError, PermissionError) as e:
            logger.error(f"Failed to iterate videos directory: {e}")
            return {"found": 0, "removed": 0, "missing": 0}

        for file_path in dir_iter:
            try:
                if file_path.is_file() and file_path.suffix.lower() in self.VIDEO_EXTENSIONS:
                    scanned_paths.add(str(file_path))
                    # 用路径匹配，而非文件名
                    if str(file_path) not in existing_map:
                        # 新发现的视频文件
                        video_id = str(uuid.uuid4())
                        now = datetime.now().isoformat()
                        try:
                            file_size = file_path.stat().st_size
                        except (OSError, PermissionError):
                            file_size = 0
                        video_info = VideoInfo(
                            id=video_id,
                            name=file_path.stem,
                            path=str(file_path),
                            size=file_size,
                            duration=0.0,
                            format=file_path.suffix.lstrip("."),
                            imported_at=now,
                        )
                        existing_videos.append(video_info.to_dict())
                        found_count += 1
                        logger.info(f"Discovered new video during scan: {file_path.name}")
            except (OSError, PermissionError) as e:
                logger.warning(f"Failed to process file {file_path}: {e}")
                continue

        # 移除已不存在于磁盘的视频记录
        before = len(existing_videos)
        existing_videos = [v for v in existing_videos if v.get("path", "") in scanned_paths]
        removed_count = before - len(existing_videos)

        # 检查那些仍保留但文件可能不可读的记录
        stats_by_path: Dict[str, int] = {}
        missing_count = 0
        for v in existing_videos:
            p = v.get("path", "")
            if p:
                p_obj = Path(p)
                if not p_obj.exists():
                    missing_count += 1

        # 更新项目元数据
        project.episode_count = len(existing_videos)
        if found_count > 0 or removed_count > 0:
            logger.info(
                f"Sync result for {project_id}: "
                f"+{found_count} new, -{removed_count} removed, "
                f"{missing_count} missing on disk"
            )
        
        # 保存更新的视频列表
        try:
            videos_file.write_text(
                json.dumps(existing_videos, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except (OSError, PermissionError) as e:
            logger.error(f"Failed to save videos.json: {e}")

        return {
            "found": found_count,
            "removed": removed_count,
            "missing": missing_count,
        }

    def update_project(self, project_id: str, updates: Dict[str, Any]) -> Optional[ProjectMeta]:
        """更新项目元数据"""
        projects = self._load_index()
        for i, p in enumerate(projects):
            if p["id"] == project_id:
                # 更新字段
                p.update(updates)
                p["updated_at"] = datetime.now().isoformat()

                # 保存到项目目录
                project_path = Path(p["path"])
                meta_file = project_path / "meta.json"
                meta_file.write_text(
                    json.dumps(p, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )

                # 更新索引
                self._save_index(projects)
                return ProjectMeta(**p)

        return None

    def delete_project(self, project_id: str, keep_files: bool = False) -> bool:
        """
        删除项目

        Args:
            project_id: 项目 ID
            keep_files: 是否保留项目文件

        Returns:
            是否成功删除
        """
        projects = self._load_index()
        project = None

        for p in projects:
            if p["id"] == project_id:
                project = p
                break

        if not project:
            return False

        # 从索引移除
        projects = [p for p in projects if p["id"] != project_id]
        self._save_index(projects)

        # 删除项目文件
        if not keep_files:
            project_path = Path(project["path"])
            if project_path.exists():
                shutil.rmtree(project_path)
                logger.info(f"Deleted project files: {project_path}")

        logger.info(f"Deleted project: {project_id}")
        return True

    def rename_project(self, project_id: str, new_name: str) -> Optional[ProjectMeta]:
        """
        重命名项目

        Args:
            project_id: 项目 ID
            new_name: 新名称

        Returns:
            更新后的 ProjectMeta，如果项目不存在则返回 None
        """
        project = self.get_project(project_id)
        if not project:
            return None

        # 更新 meta.json
        project.name = new_name
        project.updated_at = datetime.now().isoformat()
        self._save_meta(project)

        # 更新索引
        projects = self._load_index()
        for i, p in enumerate(projects):
            if p["id"] == project_id:
                projects[i] = project.to_dict()
                break
        self._save_index(projects)

        logger.info(f"Renamed project: {project_id} -> {new_name}")
        return project

    def import_videos(self, project_id: str, video_paths: List[str]) -> List[VideoInfo]:
        """
        导入视频文件到项目

        Args:
            project_id: 项目 ID
            video_paths: 视频文件路径列表

        Returns:
            导入成功的视频信息列表
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        project_path = Path(project.path)
        videos_dir = project_path / "videos"
        videos_dir.mkdir(parents=True, exist_ok=True)

        # 加载已导入的视频
        videos_file = project_path / "videos.json"
        if videos_file.exists():
            try:
                videos = json.loads(videos_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                videos = []
        else:
            videos = []

        imported = []
        for video_path in video_paths:
            src_path = Path(video_path)
            if not src_path.exists():
                logger.warning(f"Video file not found: {video_path}")
                continue

            # 跳过不支持的视频格式
            if src_path.suffix.lower() not in self.VIDEO_EXTENSIONS:
                logger.warning(
                    f"Skipping unsupported video format: {video_path} "
                    f"(extension: {src_path.suffix})"
                )
                continue

            # 生成唯一 ID
            video_id = str(uuid.uuid4())
            now = datetime.now().isoformat()

            # 复制到项目目录
            dest_name = f"{video_id}{src_path.suffix}"
            dest_path = videos_dir / dest_name

            try:
                # 硬链接或复制
                try:
                    os.link(src_path, dest_path)
                except OSError:
                    shutil.copy2(src_path, dest_path)

                video_info = VideoInfo(
                    id=video_id,
                    name=src_path.stem,
                    path=str(dest_path),
                    size=dest_path.stat().st_size,
                    duration=_probe_video_duration(str(dest_path)),
                    format=src_path.suffix.lstrip("."),
                    imported_at=now
                )
                videos.append(video_info.to_dict())
                imported.append(video_info)
                logger.info(f"Imported video: {src_path.name} -> {dest_path}")
            except Exception as e:
                logger.error(f"Failed to import {video_path}: {e}")

        # 保存视频列表
        if videos:
            try:
                videos_file.write_text(
                    json.dumps(videos, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
            except (OSError, PermissionError) as e:
                logger.error(f"Failed to save videos.json: {e}")

            # 更新项目视频数量
            self.update_project(project_id, {"episode_count": len(videos)})

        return imported

    def get_videos(self, project_id: str) -> List[VideoInfo]:
        """获取项目的视频列表"""
        project = self.get_project(project_id)
        if not project:
            return []

        project_path = Path(project.path)
        videos_file = project_path / "videos.json"

        if not videos_file.exists():
            return []

        try:
            videos_data = json.loads(videos_file.read_text(encoding="utf-8"))
            return [VideoInfo(**v) for v in videos_data]
        except (json.JSONDecodeError, IOError):
            return []



# 全局单例
_manager: Optional[ProjectManager] = None


def get_manager() -> ProjectManager:
    """获取全局项目管理器"""
    global _manager
    if _manager is None:
        _manager = ProjectManager()
    return _manager
