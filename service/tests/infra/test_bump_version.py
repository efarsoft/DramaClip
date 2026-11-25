"""版本齐平脚本（scripts/bump_version.py）：八处声明一次改齐，且全有或全无。

背景（2026-11-24 审查实锤）：脚本原先不覆盖两个锁文件，0.2.6 期间
package-lock.json 与 uv.lock 各漏带过一次，都是事后手工追平的。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "bump_version.py"

_OLD = "1.2.3"
_NEW = "1.2.4"

# 临时仓库的八份桩：每份都带着真实文件里锚点所在的上下文。
# 锁文件桩里特意放进一个恰好同版本号的第三方包——它必须原样留着。
_STUBS: dict[str, str] = {
    "service/pyproject.toml": 'version = "1.2.3"\n# 历史注释里也提 1.2.3，不许动\n',
    "desktop/package.json": '{\n  "name": "@dramaclip/desktop",\n  "version": "1.2.3"\n}\n',
    "package.json": '{\n  "name": "dramaclip",\n  "version": "1.2.3"\n}\n',
    "protocol/package.json": '{\n  "name": "@dramaclip/protocol",\n  "version": "1.2.3"\n}\n',
    "service/dramaclip/__init__.py": '__version__ = "1.2.3"\n',
    "README.md": "![version](https://img.shields.io/badge/version-1.2.3-7C9CFF)\n",
    "package-lock.json": (
        '{\n  "name": "dramaclip",\n  "version": "1.2.3",\n  "lockfileVersion": 3,\n'
        '  "packages": {\n'
        '    "": {\n      "name": "dramaclip",\n      "version": "1.2.3"\n    },\n'
        '    "desktop": {\n      "name": "@dramaclip/desktop",\n      "version": "1.2.3"\n    },\n'
        '    "protocol": {\n      "name": "@dramaclip/protocol",\n'
        '      "version": "1.2.3"\n    },\n'
        '    "node_modules/some-other-pkg": {\n      "version": "1.2.3"\n    }\n'
        "  }\n}\n"
    ),
    "service/uv.lock": (
        '[[package]]\nname = "dramaclip"\nversion = "1.2.3"\n'
        'source = { editable = "." }\n\n[[package]]\nname = "other"\nversion = "1.2.3"\n'
    ),
}

# 每份桩改完后应有的新/旧版本号出现次数（旧号只剩在注释与第三方包上）
_EXPECTED_COUNTS: dict[str, tuple[int, int]] = {
    "service/pyproject.toml": (1, 1),
    "desktop/package.json": (1, 0),
    "package.json": (1, 0),
    "protocol/package.json": (1, 0),
    "service/dramaclip/__init__.py": (1, 0),
    "README.md": (1, 0),
    "package-lock.json": (4, 1),
    "service/uv.lock": (1, 1),
}


def _write_stubs(repo: Path) -> None:
    for rel, text in _STUBS.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")


def _load(repo: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location("bump_version_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "REPO", repo)
    return module


def _run(module: ModuleType, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["bump_version.py", *argv])
    return int(module.main())


def test_bump_updates_all_eight_and_spares_same_version_third_party(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_stubs(tmp_path)
    module = _load(tmp_path, monkeypatch)

    assert _run(module, monkeypatch, _NEW) == 0

    for rel, (new_count, old_count) in _EXPECTED_COUNTS.items():
        text = (tmp_path / rel).read_text(encoding="utf-8")
        assert text.count(_NEW) == new_count, f"{rel} 新版本号出现次数不对"
        assert text.count(_OLD) == old_count, f"{rel} 旧版本号残留次数不对"


def test_bump_is_all_or_nothing_when_an_anchor_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_stubs(tmp_path)
    (tmp_path / "README.md").write_text("# 没有徽章的 README\n", encoding="utf-8")
    module = _load(tmp_path, monkeypatch)

    assert _run(module, monkeypatch, _NEW) == 1

    # README 排在第六位，前五份的锚都命中了——也不许它们被改写。
    for rel in _STUBS:
        text = (tmp_path / rel).read_text(encoding="utf-8")
        assert _NEW not in text, f"{rel} 在整体失败时被改了一半"


def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_stubs(tmp_path)
    module = _load(tmp_path, monkeypatch)
    before = {rel: (tmp_path / rel).read_text(encoding="utf-8") for rel in _STUBS}

    assert _run(module, monkeypatch, _NEW, "--dry-run") == 0

    for rel, text in before.items():
        assert (tmp_path / rel).read_text(encoding="utf-8") == text


def test_real_repo_anchors_all_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """对着真实仓库空跑：八处锚只要有一处对不上真实文件（比如 npm 换了锁文件布局）就红。"""
    module = _load(REPO, monkeypatch)  # REPO 就是真实仓库，不替换

    assert _run(module, monkeypatch, "9.9.9", "--dry-run") == 0
    assert 'version = "9.9.9"' not in (REPO / "service" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
