"""tts_runtime 的解包纪律：剥掉仓库前缀落 dest；坏名字（越界/绝对路径）一律当场
拒收，软链成员跳过且绝不实体化。

解包对象是从 GitHub/代理镜像拉下来的仓库归档，成员名属于外部输入——zip 里一条
``repo-x/../../evil`` 就能把文件写到 runtimes 之外，而装运行环境这步正握着用户目录
的写权限。坏名字不「清洗」只拒收：悄悄跳过只会得到一棵缺文件的源码树，然后在
pip 构建那步抛一句看不出根因的错误。软链是第二条逃逸通道（P0-5 曾一律拒收），
但拒收会让装运行环境死在 Matcha 归档的合法软链上（真机 2026-11-13 全链实锤）——
契约改为跳过且不实体化：不落地即无逃逸，性质等价。
"""

from __future__ import annotations

import tarfile
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from dramaclip.infra.model_manager import tts_runtime


def _write_zip(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, payload in files.items():
            zf.writestr(name, payload)


def _write_tar(path: Path, files: dict[str, bytes], extras: list[tarfile.TarInfo]) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, payload in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, BytesIO(payload))
        for info in extras:
            tar.addfile(info)


def test_zip_strips_the_repo_prefix_and_lands_every_member(tmp_path: Path) -> None:
    archive = tmp_path / "src.zip"
    _write_zip(archive, {"repo-abc/README.md": b"hi", "repo-abc/pkg/mod.py": b"x = 1\n"})
    dest = tmp_path / "out"

    tts_runtime._extract_zip_stripped(archive, dest)  # noqa: SLF001

    assert (dest / "README.md").read_bytes() == b"hi"
    assert (dest / "pkg" / "mod.py").read_bytes() == b"x = 1\n"


def test_zip_rejects_a_member_that_climbs_out_of_dest(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    _write_zip(archive, {"repo-abc/ok.txt": b"ok", "repo-abc/../../escape.txt": b"pwned"})
    dest = tmp_path / "out"

    with pytest.raises(RuntimeError, match="逃逸目标目录"):
        tts_runtime._extract_zip_stripped(archive, dest)  # noqa: SLF001

    assert list(tmp_path.glob("escape.txt")) == [], "拒收发生在写盘之前"


def test_zip_rejects_an_absolute_member_name(tmp_path: Path) -> None:
    """``/etc/passwd`` 剥掉空前缀后看着像 dest 内的正常路径——原始名必须先过闸。"""
    archive = tmp_path / "evil.zip"
    _write_zip(archive, {"/etc/passwd": b"pwned"})

    with pytest.raises(RuntimeError, match="绝对路径"):
        tts_runtime._extract_zip_stripped(archive, tmp_path / "out")  # noqa: SLF001

    assert not (tmp_path / "out" / "etc").exists()


def test_tar_strips_the_repo_prefix_and_lands_every_member(tmp_path: Path) -> None:
    archive = tmp_path / "src.tar.gz"
    _write_tar(
        archive,
        {"repo-abc/pyproject.toml": b"[project]\n", "repo-abc/a/b.py": b"pass\n"},
        [],
    )
    dest = tmp_path / "out"

    tts_runtime._extract_tar_stripped(archive, dest)  # noqa: SLF001

    assert (dest / "pyproject.toml").read_bytes() == b"[project]\n"
    assert (dest / "a" / "b.py").read_bytes() == b"pass\n"


def test_tar_rejects_a_member_that_climbs_out_of_dest(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar.gz"
    _write_tar(archive, {"repo-abc/../../escape.txt": b"pwned"}, [])
    dest = tmp_path / "out"

    with pytest.raises(RuntimeError, match="逃逸目标目录"):
        tts_runtime._extract_tar_stripped(archive, dest)  # noqa: SLF001

    assert list(tmp_path.glob("escape.txt")) == []


def test_tar_skips_symlink_members_without_materializing_them(tmp_path: Path) -> None:
    """软链是第二条逃逸通道：先落一个 ``a -> /``，再写 ``a/etc/...`` 就出圈了。

    P0-5 的契约是一律拒收，但拒收会让装运行环境死在 Matcha 归档的合法软链上
    (``data`` → 数据集占位，真机 2026-11-13 全链实锤）。契约改为跳过且绝不
    实体化：不落地即无逃逸——恶意与合法软链同样不落地，常规文件照常落位。
    """
    archive = tmp_path / "link.tar.gz"
    evil = tarfile.TarInfo("repo-abc/a")
    evil.type = tarfile.SYMTYPE
    evil.linkname = "/"
    data = tarfile.TarInfo("repo-abc/data")
    data.type = tarfile.SYMTYPE
    data.linkname = "../datasets"
    _write_tar(archive, {"repo-abc/ok.txt": b"ok"}, [evil, data])

    dest = tmp_path / "out"
    tts_runtime._extract_tar_stripped(archive, dest)  # noqa: SLF001

    assert (dest / "ok.txt").read_bytes() == b"ok", "常规文件照常落位"
    assert not (dest / "a").exists() and not (dest / "a").is_symlink(), "恶意软链不落地"
    assert not (dest / "data").exists() and not (dest / "data").is_symlink(), "合法软链同样不落地"
    assert list(tmp_path.glob("escape*")) == [], "dest 外零落地"
