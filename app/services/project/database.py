"""
SQLite 数据库管理模块
替代 JSON 文件存储，提供更好的并发支持和数据一致性
"""

import sqlite3
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from contextlib import contextmanager
from loguru import logger


class Database:
    """SQLite 数据库管理器"""
    
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path.home() / ".dramaclip" / "data.db"
        
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 初始化数据库
        self._init_db()
    
    @contextmanager
    def _get_conn(self):
        """获取数据库连接（上下文管理器）"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # 返回字典风格的行
        conn.execute("PRAGMA journal_mode=WAL")  # 提高并发性能
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_db(self):
        """初始化数据库表结构"""
        with self._get_conn() as conn:
            conn.executescript("""
                -- 项目表
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    episode_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'idle',
                    settings TEXT DEFAULT '{}'
                );
                
                -- 视频表
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    size INTEGER DEFAULT 0,
                    duration REAL DEFAULT 0.0,
                    format TEXT DEFAULT '',
                    sort_order INTEGER DEFAULT 0,
                    imported_at TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
                
                -- 创建索引
                CREATE INDEX IF NOT EXISTS idx_videos_project_id ON videos(project_id);
                CREATE INDEX IF NOT EXISTS idx_projects_path ON projects(path);
            """)
            
            # 数据库迁移：添加 sort_order 列（如果不存在）
            self._migrate_add_sort_order(conn)
            
        logger.info(f"Database initialized at {self.db_path}")
    
    def _migrate_add_sort_order(self, conn: sqlite3.Connection):
        """迁移：添加 sort_order 列到 videos 表"""
        # 检查列是否存在
        cursor = conn.execute("PRAGMA table_info(videos)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "sort_order" not in columns:
            logger.info("Migrating: Adding sort_order column to videos table")
            conn.execute("ALTER TABLE videos ADD COLUMN sort_order INTEGER DEFAULT 0")
            # 为现有视频设置排序值（按导入时间）
            rows = conn.execute(
                "SELECT id, project_id FROM videos ORDER BY imported_at"
            ).fetchall()
            
            current_project = None
            order = 0
            for row in rows:
                if row["project_id"] != current_project:
                    current_project = row["project_id"]
                    order = 0
                conn.execute(
                    "UPDATE videos SET sort_order = ? WHERE id = ?",
                    (order, row["id"])
                )
                order += 1
            
            logger.info("Migration completed: sort_order column added")
        
        # 创建 sort_order 索引（如果不存在）
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_sort_order ON videos(project_id, sort_order)"
        )
    
    # ==================== 项目操作 ====================
    
    def create_project(self, project: Dict[str, Any]) -> Dict[str, Any]:
        """创建项目"""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO projects (id, name, path, created_at, updated_at, episode_count, status, settings)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project["id"],
                    project["name"],
                    project["path"],
                    project["created_at"],
                    project["updated_at"],
                    project.get("episode_count", 0),
                    project.get("status", "idle"),
                    json.dumps(project.get("settings", {}), ensure_ascii=False)
                )
            )
        logger.debug(f"[DB] Created project: {project['name']} ({project['id']})")
        return project
    
    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """获取项目"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            
            if row:
                return self._row_to_project(row)
        return None
    
    def get_project_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        """通过路径获取项目"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE path = ?", (path,)
            ).fetchone()
            
            if row:
                return self._row_to_project(row)
        return None
    
    def list_projects(self) -> List[Dict[str, Any]]:
        """列出所有项目"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC"
            ).fetchall()
            
            return [self._row_to_project(row) for row in rows]
    
    def update_project(self, project_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """更新项目"""
        project = self.get_project(project_id)
        if not project:
            return None
        
        # 合并更新
        project.update(updates)
        project["updated_at"] = datetime.now().isoformat()
        
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE projects 
                   SET name = ?, updated_at = ?, episode_count = ?, status = ?, settings = ?
                   WHERE id = ?""",
                (
                    project["name"],
                    project["updated_at"],
                    project["episode_count"],
                    project["status"],
                    json.dumps(project.get("settings", {}), ensure_ascii=False),
                    project_id
                )
            )
        
        logger.debug(f"[DB] Updated project: {project_id}")
        return project
    
    def delete_project(self, project_id: str) -> bool:
        """删除项目（级联删除视频）"""
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            deleted = cursor.rowcount > 0
        
        if deleted:
            logger.debug(f"[DB] Deleted project: {project_id}")
        return deleted
    
    # ==================== 视频操作 ====================
    
    def add_video(self, video: Dict[str, Any]) -> Dict[str, Any]:
        """添加视频"""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO videos 
                   (id, project_id, name, path, size, duration, format, sort_order, imported_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    video["id"],
                    video["project_id"],
                    video["name"],
                    video["path"],
                    video.get("size", 0),
                    video.get("duration", 0.0),
                    video.get("format", ""),
                    video.get("sort_order", 0),
                    video["imported_at"],
                    json.dumps(video.get("metadata", {}), ensure_ascii=False)
                )
            )
        return video
    
    def get_videos(self, project_id: str, order_by: str = "sort_order") -> List[Dict[str, Any]]:
        """获取项目的视频列表
        
        Args:
            project_id: 项目ID
            order_by: 排序字段，可选 "sort_order"（默认）、"name"、"duration"、"size"
        """
        # 验证排序字段，防止SQL注入
        valid_orders = {"sort_order": "sort_order, name", "name": "name", "duration": "duration", "size": "size"}
        order_clause = valid_orders.get(order_by, "sort_order, name")
        
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM videos WHERE project_id = ? ORDER BY {order_clause}",
                (project_id,)
            ).fetchall()
            
            return [self._row_to_video(row) for row in rows]
    
    def update_video_order(self, video_orders: List[Dict[str, Any]]) -> int:
        """批量更新视频排序
        
        Args:
            video_orders: [{"id": "video_id", "sort_order": 0}, ...]
        
        Returns:
            更新的记录数
        """
        updated = 0
        with self._get_conn() as conn:
            for item in video_orders:
                if "id" in item and "sort_order" in item:
                    conn.execute(
                        "UPDATE videos SET sort_order = ? WHERE id = ?",
                        (item["sort_order"], item["id"])
                    )
                    updated += 1
        logger.debug(f"[DB] Updated {updated} video orders")
        return updated
    
    def delete_videos_by_project(self, project_id: str) -> int:
        """删除项目的所有视频"""
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM videos WHERE project_id = ?", (project_id,))
            return cursor.rowcount
    
    def delete_missing_videos(self, project_id: str) -> int:
        """删除不存在的视频记录"""
        import os
        videos = self.get_videos(project_id)
        deleted = 0
        
        with self._get_conn() as conn:
            for video in videos:
                if not os.path.exists(video["path"]):
                    conn.execute("DELETE FROM videos WHERE id = ?", (video["id"],))
                    deleted += 1
        
        if deleted > 0:
            logger.debug(f"[DB] Deleted {deleted} missing videos for project {project_id}")
        return deleted
    
    def get_video_count(self, project_id: str) -> int:
        """获取项目的视频数量"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as count FROM videos WHERE project_id = ?",
                (project_id,)
            ).fetchone()
            return row["count"]
    
    # ==================== 辅助方法 ====================
    
    def _row_to_project(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库行转换为项目字典"""
        return {
            "id": row["id"],
            "name": row["name"],
            "path": row["path"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "episode_count": row["episode_count"],
            "status": row["status"],
            "settings": json.loads(row["settings"]) if row["settings"] else {}
        }
    
    def _row_to_video(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库行转换为视频字典"""
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "path": row["path"],
            "size": row["size"],
            "duration": row["duration"],
            "format": row["format"],
            "sort_order": row["sort_order"],
            "imported_at": row["imported_at"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {}
        }


# 全局数据库实例
_db: Optional[Database] = None


def get_database() -> Database:
    """获取全局数据库实例"""
    global _db
    if _db is None:
        _db = Database()
    return _db


def reset_database() -> None:
    """重置全局数据库实例（用于测试）"""
    global _db
    _db = None
