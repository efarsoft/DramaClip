"""
ProjectManager 单元测试
"""
import json
import os
import tempfile
import shutil
from pathlib import Path

import pytest

# 确保 app 在 sys.path 中
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.project.manager import ProjectManager, ProjectMeta, VideoInfo


@pytest.fixture
def temp_dir():
    """创建临时目录作为测试工作区"""
    path = tempfile.mkdtemp(prefix="dramaclip_test_")
    yield Path(path)
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def manager(temp_dir):
    """创建一个使用临时目录的 ProjectManager"""
    m = ProjectManager(base_dir=str(temp_dir / ".dramaclip"))
    return m


@pytest.fixture
def sample_video(temp_dir):
    """创建一个空的「视频文件」用于测试"""
    video_path = temp_dir / "sample.mp4"
    video_path.write_text("fake mp4 content")
    return str(video_path)


class TestProjectManager:
    """ProjectManager CRUD 操作测试"""

    # ===== 初始化 =====

    def test_init_creates_directories(self, temp_dir):
        """初始化时应创建必要的目录结构"""
        base_dir = temp_dir / ".dramaclip"
        manager = ProjectManager(base_dir=str(base_dir))

        assert base_dir.exists()
        assert (base_dir / "projects").exists()
        assert (base_dir / "projects" / "projects.json").exists()

        # 索引文件初始应为空数组
        index_content = json.loads((base_dir / "projects" / "projects.json").read_text())
        assert index_content == []

    def test_init_with_default_base_dir(self):
        """默认 base_dir 应为 ~/.dramaclip"""
        manager = ProjectManager()
        assert manager.base_dir == Path.home() / ".dramaclip"

    # ===== 创建项目 =====

    def test_create_project_validates_name(self, manager):
        """创建项目时空白名称应抛出 ValueError"""
        with pytest.raises(ValueError, match="cannot be empty"):
            manager.create_project("", "/tmp/projects")
        with pytest.raises(ValueError, match="cannot be empty"):
            manager.create_project("   ", "/tmp/projects")

    def test_create_project(self, manager, temp_dir):
        """创建项目应返回带正确字段的元数据"""
        project = manager.create_project("测试项目", str(temp_dir / "projects"))

        assert project.id is not None
        assert project.name == "测试项目"
        assert project.status == "idle"
        assert project.episode_count == 0
        assert project.created_at is not None
        assert project.updated_at is not None

        # 验证目录结构
        project_path = Path(project.path)
        assert project_path.exists()
        assert (project_path / "videos").exists()
        assert (project_path / "analysis").exists()
        assert (project_path / "clips").exists()
        assert (project_path / "output").exists()

        # 验证 meta.json
        meta = json.loads((project_path / "meta.json").read_text())
        assert meta["name"] == "测试项目"
        assert meta["id"] == project.id

    def test_create_project_adds_to_index(self, manager, temp_dir):
        """创建项目应更新索引文件"""
        project = manager.create_project("项目A", str(temp_dir / "projects"))
        project2 = manager.create_project("项目B", str(temp_dir / "projects"))

        projects = manager.list_projects()
        assert len(projects) == 2
        assert projects[0].name == "项目A"
        assert projects[1].name == "项目B"

    # ===== 列出项目 =====

    def test_list_projects_empty(self, manager):
        """空状态下应返回空列表"""
        assert manager.list_projects() == []

    def test_list_projects(self, manager, temp_dir):
        """应返回所有已创建的项目"""
        p1 = manager.create_project("项目1", str(temp_dir / "projects"))
        p2 = manager.create_project("项目2", str(temp_dir / "projects"))
        p3 = manager.create_project("项目3", str(temp_dir / "projects"))

        projects = manager.list_projects()
        assert len(projects) == 3
        assert all(isinstance(p, ProjectMeta) for p in projects)

    # ===== 获取项目 =====

    def test_get_project(self, manager, temp_dir):
        """通过 ID 应能获取项目"""
        created = manager.create_project("测试项目", str(temp_dir / "projects"))
        fetched = manager.get_project(created.id)

        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "测试项目"

    def test_get_project_not_found(self, manager):
        """不存在的 ID 应返回 None"""
        assert manager.get_project("non-existent") is None

    # ===== 打开项目 =====

    def test_open_project(self, manager, temp_dir):
        """打开项目应返回元数据"""
        created = manager.create_project("测试项目", str(temp_dir / "projects"))
        opened = manager.open_project(created.id)

        assert opened is not None
        assert opened.id == created.id

    def test_open_project_updates_timestamp(self, manager, temp_dir):
        """打开项目应更新 updated_at"""
        created = manager.create_project("测试项目", str(temp_dir / "projects"))
        original_updated = created.updated_at

        opened = manager.open_project(created.id)
        assert opened.updated_at >= original_updated

    def test_open_project_nonexistent(self, manager):
        """打开不存在的项目应返回 None"""
        assert manager.open_project("non-existent") is None

    # ===== 更新项目 =====

    def test_update_project(self, manager, temp_dir):
        """应能更新项目字段"""
        created = manager.create_project("测试项目", str(temp_dir / "projects"))
        updated = manager.update_project(created.id, {"name": "新名称", "episode_count": 5})

        assert updated is not None
        assert updated.name == "新名称"
        assert updated.episode_count == 5

        # 验证 meta.json 同步更新
        meta = json.loads((Path(created.path) / "meta.json").read_text())
        assert meta["name"] == "新名称"

    def test_update_project_not_found(self, manager):
        """更新不存在的项目应返回 None"""
        assert manager.update_project("non-existent", {"name": "x"}) is None

    # ===== 重命名项目 =====

    def test_rename_project(self, manager, temp_dir):
        """重命名应更新名称和索引"""
        created = manager.create_project("旧名称", str(temp_dir / "projects"))
        renamed = manager.rename_project(created.id, "新名称")

        assert renamed is not None
        assert renamed.name == "新名称"

        # 验证索引已更新
        fetched = manager.get_project(created.id)
        assert fetched.name == "新名称"

    def test_rename_project_not_found(self, manager):
        """重命名不存在的项目应返回 None"""
        assert manager.rename_project("non-existent", "新名称") is None

    # ===== 删除项目 =====

    def test_delete_project(self, manager, temp_dir):
        """删除项目应从索引移除"""
        created = manager.create_project("测试项目", str(temp_dir / "projects"))
        result = manager.delete_project(created.id, keep_files=True)

        assert result is True
        # 索引中应移除
        assert manager.get_project(created.id) is None
        # 目录应保留（keep_files=True）
        assert Path(created.path).exists()

    def test_delete_project_with_files(self, manager, temp_dir):
        """keep_files=False 时应删除项目目录"""
        created = manager.create_project("测试项目", str(temp_dir / "projects"))
        result = manager.delete_project(created.id, keep_files=False)

        assert result is True
        # 目录应被删除
        assert not Path(created.path).exists()

    def test_delete_project_not_found(self, manager):
        """删除不存在的项目应返回 False"""
        assert manager.delete_project("non-existent") is False

    # ===== 导入视频 =====

    def test_import_videos(self, manager, temp_dir, sample_video):
        """导入视频应复制文件并记录"""
        created = manager.create_project("测试项目", str(temp_dir / "projects"))
        imported = manager.import_videos(created.id, [sample_video])

        assert len(imported) == 1
        video = imported[0]
        assert video.name == "sample"
        assert video.format == "mp4"
        assert video.id is not None
        # 视频文件名应包含 UUID
        assert len(Path(video.path).stem) > len("sample")  # UUID 文件名

        # 验证项目视频计数
        project = manager.get_project(created.id)
        assert project.episode_count == 1

    def test_import_videos_project_not_found(self, manager, temp_dir):
        """导入到不存在的项目应抛出 ValueError"""
        with pytest.raises(ValueError, match="Project not found"):
            manager.import_videos("non-existent", ["/tmp/fake.mp4"])

    def test_import_videos_missing_file(self, manager, temp_dir):
        """导入不存在的文件应跳过"""
        created = manager.create_project("测试项目", str(temp_dir / "projects"))
        imported = manager.import_videos(created.id, ["/tmp/nonexistent.mp4"])
        assert len(imported) == 0

    def test_import_videos_unsupported_format(self, manager, temp_dir):
        """不支持的格式应跳过"""
        created = manager.create_project("测试项目", str(temp_dir / "projects"))
        unsupported = temp_dir / "test.txt"
        unsupported.write_text("not a video")
        imported = manager.import_videos(created.id, [str(unsupported)])
        assert len(imported) == 0
        # 确保 videos.json 未创建
        videos_file = Path(created.path) / "videos.json"
        assert not videos_file.exists()

    # ===== 获取视频列表 =====

    def test_get_videos(self, manager, temp_dir, sample_video):
        """获取视频应返回导入的视频信息"""
        created = manager.create_project("测试项目", str(temp_dir / "projects"))
        manager.import_videos(created.id, [sample_video])

        videos = manager.get_videos(created.id)
        assert len(videos) == 1
        assert isinstance(videos[0], VideoInfo)
        assert videos[0].name == "sample"

    def test_get_videos_no_videos_file(self, manager, temp_dir):
        """无 videos.json 时应返回空列表"""
        created = manager.create_project("测试项目", str(temp_dir / "projects"))
        videos = manager.get_videos(created.id)
        assert videos == []

    def test_get_videos_project_not_found(self, manager):
        """不存在的项目应返回空列表"""
        assert manager.get_videos("non-existent") == []

    # ===== 索引持久化 =====

    def test_index_persistence(self, manager, temp_dir):
        """索引文件应持久化项目列表"""
        manager.create_project("项目A", str(temp_dir / "projects"))
        manager.create_project("项目B", str(temp_dir / "projects"))

        # 创建新 manager 实例读取相同索引
        manager2 = ProjectManager(base_dir=str(manager.base_dir))
        projects = manager2.list_projects()
        assert len(projects) == 2

    def test_handle_corrupted_index(self, temp_dir):
        """损坏的索引文件应被优雅处理"""
        base_dir = temp_dir / ".dramaclip"
        manager = ProjectManager(base_dir=str(base_dir))
        manager.create_project("测试项目", str(temp_dir / "projects"))

        # 损坏索引
        index_file = base_dir / "projects" / "projects.json"
        index_file.write_text("{{{corrupted}}}", encoding="utf-8")

        # 应返回空列表而非崩溃
        assert manager.list_projects() == []


class TestProjectMeta:
    """ProjectMeta 模型测试"""

    def test_to_dict(self):
        """to_dict 应返回正确字典"""
        meta = ProjectMeta(
            id="test-1",
            name="测试",
            path="/tmp/test",
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
            episode_count=0,
            status="idle",
        )
        d = meta.to_dict()
        assert d["id"] == "test-1"
        assert d["name"] == "测试"
        assert d["status"] == "idle"

    def test_serialization_roundtrip(self):
        """ProjectMeta 应能 JSON 序列化并还原"""
        meta = ProjectMeta(
            id="test-1",
            name="测试",
            path="/tmp/test",
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
            episode_count=0,
            status="idle",
        )
        json_str = json.dumps(meta.to_dict(), ensure_ascii=False)
        restored = ProjectMeta(**json.loads(json_str))

        assert restored.id == meta.id
        assert restored.name == meta.name
        assert restored.status == meta.status
