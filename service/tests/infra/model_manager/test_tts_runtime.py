"""tts_runtime 解包纪律：软链跳过不实体化（软链是归档逃逸的第二条通道）。"""

import io
import tarfile
from pathlib import Path

from dramaclip.infra.model_manager import tts_runtime


def _make_repo_tar(path: Path) -> None:
    """构造带符号链接成员的仓库归档（Matcha 真实形状：data → 数据集占位）。"""
    with tarfile.open(path, "w:gz") as tar:
        link = tarfile.TarInfo("repo-x/data")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../somewhere-else"
        tar.addfile(link)
        regular = tarfile.TarInfo("repo-x/matcha/__init__.py")
        payload = b"__all__: list[str] = []\n"
        regular.size = len(payload)
        regular.type = tarfile.REGTYPE
        tar.addfile(regular, io.BytesIO(payload))


def test_extract_tar_stripped_skips_symlinks_and_never_materializes_them(
    tmp_path: Path,
) -> None:
    """软链成员跳过（运行期用不到、Windows 建链要特权），常规文件照常落位。"""
    archive = tmp_path / "matcha.tar.gz"
    _make_repo_tar(archive)
    dest = tmp_path / "matcha"

    tts_runtime._extract_tar_stripped(archive, dest)

    assert (dest / "matcha" / "__init__.py").is_file(), "常规文件必须落位"
    assert not (dest / "data").exists() and not (dest / "data").is_symlink(), (
        "符号链接成员不许实体化——落地即可被改造成逃逸通道"
    )
