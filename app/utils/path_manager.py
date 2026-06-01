"""
统一路径管理器
负责管理所有文件路径：输出目录、缓存目录、临时目录、日志目录
解决输出污染用户原始目录的问题
"""

import os
import shutil
import uuid
from pathlib import Path
from typing import Optional, Union
from contextlib import contextmanager
from datetime import datetime


class PathManager:
    """
    统一路径管理器

    设计原则：
    1. 绝不污染用户原始文件目录
    2. 所有输出文件必须在用户可控的输出根目录
    3. 临时文件统一管理，异常也能清理
    4. 支持项目级别的输出隔离
    """

    def __init__(
        self,
        output_root: Optional[Union[str, Path]] = None,
        cache_root: Optional[Union[str, Path]] = None,
        temp_root: Optional[Union[str, Path]] = None,
    ):
        """
        初始化路径管理器

        Args:
            output_root: 输出根目录，默认 ~/DramaClip/Outputs
            cache_root: 缓存根目录，默认 ~/.dramaclip/cache
            temp_root: 临时文件根目录，默认 ~/.dramaclip/temp
        """
        self._output_root = self._resolve_path(
            output_root or Path.home() / "DramaClip" / "Outputs"
        )
        self._cache_root = self._resolve_path(
            cache_root or Path.home() / ".dramaclip" / "cache"
        )
        self._temp_root = self._resolve_path(
            temp_root or Path.home() / ".dramaclip" / "temp"
        )
        self._temp_files: set = set()

    @staticmethod
    def _resolve_path(path: Union[str, Path]) -> Path:
        """解析并确保路径存在"""
        p = Path(path).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def output_root(self) -> Path:
        """输出根目录"""
        return self._output_root

    @property
    def cache_root(self) -> Path:
        """缓存根目录"""
        return self._cache_root

    @property
    def temp_root(self) -> Path:
        """临时文件根目录"""
        return self._temp_root

    def set_output_root(self, path: Union[str, Path]) -> None:
        """设置输出根目录"""
        self._output_root = self._resolve_path(path)

    def get_project_output_dir(self, project_name: str, project_id: Optional[str] = None) -> Path:
        """
        获取项目输出目录（使用显示名称，便于用户识别；内部工作目录使用安全 ID）

        输出结构：
        ~/DramaClip/Outputs/
          └── 我的短剧/                 # 使用友好名称
              └── 2024-01-15_143022/
                  ├── clip_001.mp4
                  ...

        Args:
            project_name: 项目显示名称（推荐）
            project_id: 可选的项目ID（用于未来隔离）

        Returns:
            项目输出目录（已创建）
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        safe_name = self._sanitize_name(project_name or (project_id or "unnamed"))
        project_dir = self._output_root / safe_name
        project_dir.mkdir(parents=True, exist_ok=True)

        session_dir = project_dir / timestamp
        session_dir.mkdir(parents=True, exist_ok=True)

        return session_dir

    def get_output_path(
        self,
        project_name: str,
        filename: str,
        create_dir: bool = True
    ) -> Path:
        """
        获取输出文件路径（绝对不会在用户原始目录）

        Args:
            project_name: 项目名称
            filename: 文件名（包含扩展名）
            create_dir: 是否创建目录

        Returns:
            输出文件路径

        Raises:
            ValueError: 如果文件名包含路径分隔符（防止路径穿越）
        """
        if os.path.sep in filename or filename.startswith("."):
            raise ValueError(
                f"Invalid filename: {filename}. "
                "Filename must not contain path separators or start with dot."
            )

        output_dir = self.get_project_output_dir(project_name)

        if create_dir:
            output_dir.mkdir(parents=True, exist_ok=True)

        return output_dir / filename

    def create_temp_file(
        self,
        suffix: str = "",
        prefix: str = "dramaclip_",
        delete_on_exit: bool = True
    ) -> Path:
        """
        创建临时文件（统一管理，异常也能清理）

        Args:
            suffix: 文件扩展名
            prefix: 文件名前缀
            delete_on_exit: 程序退出时自动删除

        Returns:
            临时文件路径
        """
        self._temp_root.mkdir(parents=True, exist_ok=True)

        temp_path = self._temp_root / f"{prefix}{uuid.uuid4().hex}{suffix}"

        if delete_on_exit:
            self._temp_files.add(temp_path)

        return temp_path

    def create_temp_dir(
        self,
        prefix: str = "dramaclip_dir_",
        delete_on_exit: bool = True
    ) -> Path:
        """
        创建临时目录

        Args:
            prefix: 目录名前缀
            delete_on_exit: 程序退出时自动删除

        Returns:
            临时目录路径
        """
        self._temp_root.mkdir(parents=True, exist_ok=True)

        temp_path = self._temp_root / f"{prefix}{uuid.uuid4().hex}"
        temp_path.mkdir(parents=True, exist_ok=True)

        if delete_on_exit:
            self._temp_files.add(temp_path)

        return temp_path

    @contextmanager
    def temp_dir_context(self, prefix: str = "dramaclip_dir_"):
        """
        临时目录上下文管理器

        用法：
            with path_manager.temp_dir_context() as temp_dir:
                # 在临时目录中操作
                pass
            # 退出时自动清理
        """
        temp_dir = self.create_temp_dir(prefix=prefix, delete_on_exit=True)
        try:
            yield temp_dir
        finally:
            self.cleanup_path(temp_dir)

    @contextmanager
    def temp_file_context(self, suffix: str = "", prefix: str = "dramaclip_"):
        """
        临时文件上下文管理器

        用法：
            with path_manager.temp_file_context(suffix=".mp4") as temp_file:
                # 使用临时文件
                pass
            # 退出时自动清理
        """
        temp_file = self.create_temp_file(suffix=suffix, prefix=prefix, delete_on_exit=True)
        try:
            yield temp_file
        finally:
            self.cleanup_path(temp_file)

    def register_temp_path(self, path: Union[str, Path]) -> None:
        """
        注册临时文件/目录（用于跟踪清理）

        Args:
            path: 文件或目录路径
        """
        self._temp_files.add(Path(path))

    def cleanup_path(self, path: Union[str, Path]) -> bool:
        """
        清理指定的文件或目录

        Args:
            path: 文件或目录路径

        Returns:
            是否清理成功
        """
        path = Path(path)

        if not path.exists():
            return True

        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)

            self._temp_files.discard(path)
            return True

        except Exception as e:
            print(f"Failed to cleanup {path}: {e}")
            return False

    def cleanup_all(self) -> dict:
        """
        清理所有注册的临时文件

        Returns:
            清理统计信息
        """
        stats = {
            "total": len(self._temp_files),
            "success": 0,
            "failed": 0,
            "failed_paths": []
        }

        for path in list(self._temp_files):
            if self.cleanup_path(path):
                stats["success"] += 1
            else:
                stats["failed"] += 1
                stats["failed_paths"].append(str(path))

        self._temp_files.clear()
        return stats

    def cleanup_old_temp_files(self, max_age_hours: int = 24) -> int:
        """
        清理过期的临时文件

        Args:
            max_age_hours: 文件最大保留时间（小时）

        Returns:
            清理的文件数量
        """
        if not self._temp_root.exists():
            return 0

        count = 0
        max_age_seconds = max_age_hours * 3600
        current_time = datetime.now().timestamp()

        for path in self._temp_root.glob("**/*"):
            if not path.is_file():
                continue

            file_age = current_time - path.stat().st_mtime

            if file_age > max_age_seconds:
                if self.cleanup_path(path):
                    count += 1

        return count

    def cleanup_by_disk_usage(self, max_disk_usage_gb: float = 10.0) -> int:
        """
        根据磁盘使用量自动清理临时文件

        按文件修改时间从旧到新清理，直到磁盘使用量降到阈值以下

        Args:
            max_disk_usage_gb: 最大磁盘使用量（GB）

        Returns:
            清理的文件数量
        """
        if not self._temp_root.exists():
            return 0

        max_bytes = max_disk_usage_gb * 1024 * 1024 * 1024
        total_size = sum(f.stat().st_size for f in self._temp_root.rglob("*") if f.is_file())

        if total_size <= max_bytes:
            return 0

        excess_bytes = total_size - max_bytes
        cleaned_bytes = 0
        count = 0

        # 按修改时间排序（从旧到新）
        files = sorted(
            [f for f in self._temp_root.rglob("*") if f.is_file()],
            key=lambda x: x.stat().st_mtime
        )

        for path in files:
            if cleaned_bytes >= excess_bytes:
                break

            file_size = path.stat().st_size
            if self.cleanup_path(path):
                cleaned_bytes += file_size
                count += 1

        return count

    def get_disk_usage(self) -> dict:
        """
        获取磁盘使用统计

        Returns:
            磁盘使用信息字典
        """
        if not self._temp_root.exists():
            return {
                "total_bytes": 0,
                "total_files": 0,
                "total_dirs": 0
            }

        files = [f for f in self._temp_root.rglob("*") if f.is_file()]
        dirs = [d for d in self._temp_root.rglob("*") if d.is_dir()]

        return {
            "total_bytes": sum(f.stat().st_size for f in files),
            "total_files": len(files),
            "total_dirs": len(dirs)
        }

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """
        清理文件名（移除不安全字符）

        Args:
            name: 原始名称

        Returns:
            安全的名称
        """
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, "_")

        name = name.strip(". ")

        if not name:
            name = "unnamed"

        return name

    def open_output_dir(self, project_name: Optional[str] = None) -> Path:
        """
        打开输出目录（供前端调用）

        Args:
            project_name: 项目名称，如果为 None 则打开根输出目录

        Returns:
            目录路径
        """
        if project_name:
            output_dir = self._output_root / self._sanitize_name(project_name)
        else:
            output_dir = self._output_root

        output_dir.mkdir(parents=True, exist_ok=True)

        return output_dir

    def list_output_dirs(self) -> list:
        """
        列出所有项目输出目录

        Returns:
            项目目录列表（按修改时间排序，最新的在前）
        """
        if not self._output_root.exists():
            return []

        dirs = [
            d for d in self._output_root.iterdir()
            if d.is_dir()
        ]

        dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        return [
            {
                "name": d.name,
                "path": str(d),
                "modified": datetime.fromtimestamp(d.stat().st_mtime).isoformat(),
                "size": sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            }
            for d in dirs
        ]

    def __del__(self):
        """析构时清理所有临时文件"""
        self.cleanup_all()


# 全局单例
_global_path_manager: Optional[PathManager] = None


def get_path_manager() -> PathManager:
    """获取全局路径管理器实例"""
    global _global_path_manager
    if _global_path_manager is None:
        _global_path_manager = PathManager()
    return _global_path_manager


def init_path_manager(
    output_root: Optional[Union[str, Path]] = None,
    cache_root: Optional[Union[str, Path]] = None,
    temp_root: Optional[Union[str, Path]] = None
) -> PathManager:
    """
    初始化全局路径管理器

    Args:
        output_root: 输出根目录
        cache_root: 缓存根目录
        temp_root: 临时文件根目录

    Returns:
        PathManager 实例
    """
    global _global_path_manager
    _global_path_manager = PathManager(
        output_root=output_root,
        cache_root=cache_root,
        temp_root=temp_root
    )
    return _global_path_manager
