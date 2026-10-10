"""TTS 工厂的引擎表是唯一真相源；sherpa-onnx melo 已撤下（2026-09-20）。

撤的理由记在这里而不是聊天里：单说话人、没有仓库形式的自动下载源（资产库里永远是
一行点不动下载的「缺模型」），业主的耳朵判它不如 kokoro。

撤干净的标准是「三处一起少」：supported() 不再列出它、create() 当面拒绝它、
引擎模块本身不在包里。只删一半会留下清单说已接入而工厂造不出来的假就绪——
那正是 registry.engine_ready 读工厂这张表要防的事。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from dramaclip.engines.tts import factory


def test_factory_supports_exactly_the_wired_engines() -> None:
    assert factory.supported() == frozenset(
        {"edge", "kokoro", "indextts2", "cosyvoice", "cosyvoice3", "cosyvoice_cloud"}
    )


def test_dropped_engine_is_refused_not_silently_swapped(tmp_path: Path) -> None:
    """设置里还写着撤下的引擎也得当面报错：换个引擎出声等于把业主的选择吞掉。"""
    with pytest.raises(ValueError, match="未知 TTS 引擎"):
        factory.create("sherpa_melo", tmp_path / "models")


def test_model_dir_has_no_default_engine(tmp_path: Path) -> None:
    """默认引擎等于给「按引擎取目录」偷偷塞一个答案：漏传参数的调用会安静地读错目录。"""
    with pytest.raises(TypeError):
        factory.model_dir(tmp_path / "models")  # type: ignore[call-arg]


def test_dropped_engine_module_is_gone() -> None:
    assert importlib.util.find_spec("dramaclip.engines.tts.engines.sherpa") is None
