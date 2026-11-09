"""engines.narration.publish_pack：逐平台发布包（画幅/字数适配 + 实测话题注入）。"""

from __future__ import annotations

from dramaclip.engines.narration import publish_pack


def test_platform_specs_match_report() -> None:
    assert publish_pack.PLATFORM_SPECS["小红书"]["cover_ratio"] == (3, 4)
    assert publish_pack.PLATFORM_SPECS["B站"]["cover_ratio"] == (16, 10)
    assert publish_pack.PLATFORM_SPECS["视频号"]["cover_ratio"] == (6, 7)
    assert publish_pack.PLATFORM_SPECS["抖音"]["cover_ratio"] == (9, 16)
    assert publish_pack.PLATFORM_ORDER[0] == "抖音", "平台优先级按实测：抖音>视频号>快手"


def test_inject_topics_dedup_and_cap() -> None:
    assert publish_pack.inject_topics(["逆袭", "好剧推荐"]) == [
        "逆袭", "好剧推荐", "短剧推荐", "因为一个片段看了整部剧", "短剧",
    ]
    full = [f"t{i}" for i in range(8)]
    assert publish_pack.inject_topics(full) == full, "槽满不挤掉用户标签"


def test_build_pack_selected_title_and_fitness() -> None:
    pack = publish_pack.build_pack(
        [{"text": "落选", "selected": False}, {"text": "当选标题", "selected": True}],
        "文案", ["爽剧"],
    )
    assert pack["title"] == "当选标题"
    assert pack["platforms"]["小红书"]["title_fits"] is True
    assert pack["platforms"]["小红书"]["cover_ratio"] == [3, 4]
    assert "好剧推荐" in pack["platforms"]["抖音"]["tags"]
    for entry in pack["platforms"].values():
        assert entry["ai_declaration"] != "", "逐平台 AI 声明指引（报告项①配套）"


def test_build_pack_overlong_title_flagged_not_truncated() -> None:
    pack = publish_pack.build_pack([{"text": "字" * 21, "selected": True}], None, [])
    assert pack["platforms"]["小红书"]["title_fits"] is False
    assert pack["platforms"]["小红书"]["title"] == "字" * 21, "校验而非截断"


def test_build_pack_falls_back_to_first_title() -> None:
    pack = publish_pack.build_pack([{"text": "第一条", "selected": False}], None, [])
    assert pack["title"] == "第一条"
