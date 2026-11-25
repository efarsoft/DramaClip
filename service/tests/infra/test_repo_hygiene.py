"""被跟踪文件卫生守卫：代理工作区 / 临时目录 / 密钥形态 / CRLF 不许再进索引。

背景（2026-11-24 审查实锤，同根四起）：.adnify 会话转录（内含 API 密钥）与
.agnes 调研产物、tmp-rel 临时文件、构建日志先后被整目录暂存带进了公开仓库；
.gitignore 里一条写成 ``../tmp-rel/`` 的规则，从仓库根看指向仓库外一级，
零命中。ignore 规则管不住已在索引里的文件，也挡不住写错的规则——本守卫
直接盯索引本身。

没有 git 的环境跳过（CI 的 checkout 自带 .git，索引即真实提交内容）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

# 仓库根下不许出现的一级目录：本机工作区、运行时数据、构建产物（desktop/build 除外）
_FORBIDDEN_ROOT_DIRS = frozenset(
    {
        ".agnes",
        ".adnify",
        ".claude",
        ".cursor",
        ".workbuddy",
        ".zcode",
        ".superpowers",
        "build",
        "data",
        "data-scale",
        "node_modules",
        "scratch",
        "tmp-rel",
        "tmp_w2_media",
    }
)

# 密钥形态：sk- 后跟 24 位以上的字母数字（两家常见平台的真实密钥都在此列；
# 测试夹具用的是带连字符的短假值，不会命中）。
_SECRET_PATTERN = r"sk-[A-Za-z0-9]{24,}"


def _git(*args: str, ok: tuple[int, ...] = (0,)) -> list[str]:
    completed = subprocess.run(  # noqa: S603 - 固定子命令、仓库内只读
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode in ok, f"git {' '.join(args)} 失败：{completed.stderr}"
    return completed.stdout.splitlines()


def _require_git() -> None:
    if shutil.which("git") is None or not (REPO / ".git").exists():
        pytest.skip("没有 git 或不是 git 工作树")


def test_index_has_no_workspace_or_temp_paths() -> None:
    _require_git()
    tracked = [line for line in _git("ls-files") if line]
    assert tracked, "索引是空的——checkout 不完整？"

    offenders = [
        path
        for path in tracked
        if path.split("/", 1)[0] in _FORBIDDEN_ROOT_DIRS or path.startswith("build_")
    ]
    assert not offenders, f"本机工作区/临时文件进了索引：{offenders[:10]}"


def test_index_has_no_key_shaped_strings() -> None:
    _require_git()
    # --cached 查索引内容；-I 跳过二进制；-l 只列文件名（命中内容不进测试输出）。
    # grep 没有命中时退出码是 1——那正是想要的结果，不算失败。
    hits = _git("grep", "--cached", "-I", "-l", "-E", _SECRET_PATTERN, ok=(0, 1))
    assert not hits, f"疑似密钥进了索引（立即轮换并移除）：{hits}"


def test_index_text_files_are_lf() -> None:
    _require_git()
    crlf = [
        line.split("\t", 1)[0]
        for line in _git("ls-files", "--eol")
        if line.startswith(("i/crlf", "i/mixed"))
    ]
    assert not crlf, (
        f"索引里出现了 CRLF/混合行尾的文件（行尾由 .gitattributes 统一成 LF）：{crlf[:10]}"
    )
