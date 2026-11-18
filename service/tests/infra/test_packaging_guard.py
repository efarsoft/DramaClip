"""打包完整性守卫：collect-data 清单缺一就是装测级发布缺陷。

silero_vad_v6.onnx 没进包的实锤（2026-11-17）：dev/CI 从源码跑探不到，
只有装测产物才暴露——守卫读打包脚本源码静态钉住，防后续改脚本时漏回。
"""

from __future__ import annotations

from pathlib import Path


def _script(repo_root: Path) -> str:
    return (repo_root / "scripts" / "build-service.py").read_text(encoding="utf-8")


def test_faster_whisper_assets_are_collected(repo_root: Path) -> None:
    src = _script(repo_root)
    assert '"--collect-data", "faster_whisper"' in src, (
        "faster_whisper 包内资产（silero VAD onnx）必须随包收集——缺了全量用户 "
        "faster-whisper 自检 NO_SUCHFILE 必挂（装测 2026-11-17 实锤）"
    )


def test_existing_data_collections_intact(repo_root: Path) -> None:
    src = _script(repo_root)
    for key in ('"--collect-data", "dramaclip"', '"--collect-data", "jieba"'):
        assert key in src, f"既有数据收集不得回退：{key}"
