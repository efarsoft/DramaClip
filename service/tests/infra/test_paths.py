"""infra.paths：数据目录解析（env 注入优先）。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.infra import paths


def test_env_override_creates_subdirs(tmp_path: Path) -> None:
    base = tmp_path / "data-home"
    result = paths.resolve_data_dir(env={"DRAMACLIP_DATA_DIR": str(base)})
    assert result == base
    for name in ("models", "cache", "outputs", "logs"):
        assert (base / name).is_dir()


def test_blank_env_falls_back_to_appdata(tmp_path: Path) -> None:
    appdata = tmp_path / "appdata"
    result = paths.resolve_data_dir(env={"DRAMACLIP_DATA_DIR": "  ", "APPDATA": str(appdata)})
    assert result == appdata / "DramaClip"


def test_db_path(tmp_path: Path) -> None:
    assert paths.db_path(tmp_path) == tmp_path / "data.db"


def test_resources_env_override(tmp_path: Path) -> None:
    result = paths.resolve_resources_dir(env={"DRAMACLIP_RESOURCES_DIR": str(tmp_path)})
    assert result == tmp_path


def test_resources_blank_env_falls_back_to_repo_root() -> None:
    result = paths.resolve_resources_dir(env={"DRAMACLIP_RESOURCES_DIR": "  "})
    assert result.name == "resources"
    assert (result / "ffmpeg").is_dir(), "开发模式回退应指向仓库根 resources/"
