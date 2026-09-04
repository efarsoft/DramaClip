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
