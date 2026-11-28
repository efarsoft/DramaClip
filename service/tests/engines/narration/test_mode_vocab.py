"""ModeSpec 注册表契约：五张派生表与注册行一致，加模式只动一行不另抄表。"""

from __future__ import annotations

import pytest

from dramaclip.engines.narration.mode_vocab import (
    _MODE_SPECS,
    _NARRATION_MODES,
    _NO_TTS_MODES,
    _SCRIPT_DRIVEN_MODES,
    _ZERO_COPY_MODES,
    SUPPORTED_MODES,
    expected_copy_source,
    spec_of,
)


def test_registry_covers_supported_exactly_once_in_order() -> None:
    """注册表是 SUPPORTED 的唯一来源：一行一模式、无重名、顺序即白名单顺序。"""
    assert tuple(spec.name for spec in _MODE_SPECS) == SUPPORTED_MODES
    assert len({spec.name for spec in _MODE_SPECS}) == len(_MODE_SPECS)


def test_partitions_are_complete_and_disjoint() -> None:
    """有配音/无配音恰好二分全部模式；零文案就是无配音的别名，不另立第四张表。"""
    assert set(SUPPORTED_MODES) == _NO_TTS_MODES | _NARRATION_MODES
    assert not _NO_TTS_MODES & _NARRATION_MODES
    assert _ZERO_COPY_MODES is _NO_TTS_MODES


def test_script_driven_subset_matches_spec_rows() -> None:
    """剧本驱动是注册行属性：集合可由行推出，且今天的唯一成员是 dialogue_narration。"""
    assert set(SUPPORTED_MODES) >= _SCRIPT_DRIVEN_MODES
    assert {spec.name for spec in _MODE_SPECS if spec.script_driven} == _SCRIPT_DRIVEN_MODES
    assert {"dialogue_narration"} == _SCRIPT_DRIVEN_MODES


def test_copy_source_follows_tts_row() -> None:
    """文案来源逐模式跟 tts 注册行：无 TTS=rule（规则预算），其余=llm_script。"""
    for spec in _MODE_SPECS:
        want = "rule" if not spec.tts else "llm_script"
        assert expected_copy_source(spec.name) == want
    assert expected_copy_source("raw_clip") == "rule"
    assert expected_copy_source("cross_narration") == "llm_script"


def test_spec_of_round_trips_and_rejects_unknown() -> None:
    for mode in SUPPORTED_MODES:
        assert spec_of(mode).name == mode
    with pytest.raises(KeyError):
        spec_of("highlight_cut")  # 下线模式不在注册表（migrations/027 已清）
