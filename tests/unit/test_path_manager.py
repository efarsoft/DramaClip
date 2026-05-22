"""
单元测试 - PathManager
测试统一路径管理器
"""

import pytest
from pathlib import Path
from app.utils.path_manager import PathManager, get_path_manager


class TestPathManager:
    """PathManager 测试"""

    def test_init_default_paths(self, temp_dir: Path):
        """测试默认路径初始化"""
        path_mgr = PathManager(
            output_root=temp_dir / "outputs",
            cache_root=temp_dir / "cache",
            temp_root=temp_dir / "temp",
        )

        assert path_mgr.output_root == temp_dir / "outputs"
        assert path_mgr.cache_root == temp_dir / "cache"
        assert path_mgr.temp_root == temp_dir / "temp"

    def test_get_output_path(self, temp_dir: Path):
        """测试获取输出路径"""
        path_mgr = PathManager(
            output_root=temp_dir / "outputs",
            temp_root=temp_dir / "temp",
        )

        output_path = path_mgr.get_output_path(
            project_name="测试项目",
            filename="clip_001.mp4"
        )

        assert "测试项目" in str(output_path)
        assert output_path.name == "clip_001.mp4"

    def test_output_path_no_user_directory(self, temp_dir: Path):
        """测试输出路径不在用户原始目录"""
        path_mgr = PathManager(output_root=temp_dir / "outputs")

        user_dir = temp_dir / "user_videos"
        user_dir.mkdir()

        output_path = path_mgr.get_output_path(
            project_name="my_project",
            filename="output.mp4"
        )

        # 输出路径不应该在用户目录
        assert not str(output_path).startswith(str(user_dir))

    def test_create_temp_file(self, temp_dir: Path):
        """测试创建临时文件路径
        
        create_temp_file() 按设计只分配路径，不会实际创建文件。
        调用者负责创建/填充文件内容。
        """
        path_mgr = PathManager(temp_root=temp_dir / "temp")

        temp_file = path_mgr.create_temp_file(suffix=".mp4")

        # 只分配路径，尚未创建文件
        assert temp_file.suffix == ".mp4"
        assert "dramaclip" in str(temp_file)
        # 文件在 temp_root 下
        assert str(temp_file).startswith(str(temp_dir / "temp"))

    def test_temp_file_context(self, temp_dir: Path):
        """测试临时文件上下文管理器
        
        temp_file_context 返回路径但不创建文件，
        退出时自动清理（即使文件不存在也安全）。
        """
        path_mgr = PathManager(temp_root=temp_dir / "temp")

        with path_mgr.temp_file_context(suffix=".mp4") as temp_file:
            assert temp_file.suffix == ".mp4"
            # 手动创建文件
            temp_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file.write_bytes(b"test")
            assert temp_file.exists()

        # 退出上下文后文件应该被清理
        assert not temp_file.exists()

    def test_temp_dir_context(self, temp_dir: Path):
        """测试临时目录上下文管理器"""
        path_mgr = PathManager(temp_root=temp_dir / "temp")

        with path_mgr.temp_dir_context() as temp_dir_path:
            assert temp_dir_path.exists()
            assert temp_dir_path.is_dir()

        # 退出上下文后目录应该被清理
        assert not temp_dir_path.exists()

    def test_cleanup_all(self, temp_dir: Path):
        """测试清理所有临时文件"""
        path_mgr = PathManager(temp_root=temp_dir / "temp")

        # 创建多个临时文件
        files = [path_mgr.create_temp_file(suffix=f".{i}") for i in range(3)]

        # 清理
        stats = path_mgr.cleanup_all()

        assert stats["success"] == 3
        assert all(not f.exists() for f in files)

    def test_sanitize_name(self, temp_dir: Path):
        """测试文件名清理"""
        path_mgr = PathManager(output_root=temp_dir)

        # 测试非法字符
        name = path_mgr._sanitize_name("项目/名称<>:|?*")
        assert "/" not in name
        assert "<" not in name
        assert ">" not in name

        # 测试空名称
        name = path_mgr._sanitize_name("")
        assert name == "unnamed"

    def test_invalid_filename_rejected(self, temp_dir: Path):
        """测试无效文件名被拒绝"""
        path_mgr = PathManager(output_root=temp_dir)

        with pytest.raises(ValueError):
            path_mgr.get_output_path(
                project_name="test",
                filename="../etc/passwd"  # 路径穿越尝试
            )

    def test_list_output_dirs(self, temp_dir: Path):
        """测试列出输出目录"""
        path_mgr = PathManager(output_root=temp_dir / "outputs")

        # 创建测试目录
        (temp_dir / "outputs" / "project1").mkdir(parents=True)
        (temp_dir / "outputs" / "project2").mkdir(parents=True)

        dirs = path_mgr.list_output_dirs()

        assert len(dirs) == 2
        names = [d["name"] for d in dirs]
        assert "project1" in names
        assert "project2" in names


class TestPathManagerSingleton:
    """全局单例测试"""

    def test_get_path_manager(self):
        """测试获取全局实例"""
        mgr1 = get_path_manager()
        mgr2 = get_path_manager()

        # 应该是同一个实例
        assert mgr1 is mgr2
