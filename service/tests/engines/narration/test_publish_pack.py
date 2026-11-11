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


def test_checklist_three_items_always_manual() -> None:
    """授权/挂载/标题封面三项恒人工：无论配置如何 satisfied 一律 False，不假绿。"""
    pack = publish_pack.build_pack([{"text": "标题", "selected": True}], None, ["爽剧"])
    items = publish_pack.build_checklist(pack, drama_name="发布剧", drama_name_layer_enabled=True)
    assert len(items) == 5
    for item in items[:3]:
        assert item["satisfied"] is False
        assert item["label"].startswith("☐ ")
        assert item["note"] != "", "人工项必须带需人工确认的补充说明"


def test_checklist_drama_name_satisfied_when_layer_on_and_name_present() -> None:
    pack = publish_pack.build_pack([{"text": "标题", "selected": True}], None, ["爽剧"])
    items = publish_pack.build_checklist(pack, drama_name="发布剧", drama_name_layer_enabled=True)
    name_item = next(i for i in items if "全程剧名" in i["label"])
    assert name_item["satisfied"] is True
    assert name_item["label"].startswith("☑ ")
    assert name_item["note"] == ""


def test_checklist_drama_name_unsatisfied_when_layer_off_or_name_empty() -> None:
    pack = publish_pack.build_pack([{"text": "标题", "selected": True}], None, ["爽剧"])
    off = publish_pack.build_checklist(pack, drama_name="发布剧", drama_name_layer_enabled=False)
    off_name = next(i for i in off if "全程剧名" in i["label"])
    assert off_name["satisfied"] is False
    assert off_name["note"] != ""
    empty = publish_pack.build_checklist(pack, drama_name="  ", drama_name_layer_enabled=True)
    empty_name = next(i for i in empty if "全程剧名" in i["label"])
    assert empty_name["satisfied"] is False, "剧名空白视同未带剧名"


def test_checklist_tags_satisfied_by_injected_topics() -> None:
    """注入实测高频话题后标签恒非空 → 话题组满足；标签全空的包 → 未满足带补充。"""
    with_topics = publish_pack.build_pack([{"text": "标题", "selected": True}], None, [])
    items = publish_pack.build_checklist(
        with_topics, drama_name="发布剧", drama_name_layer_enabled=True,
    )
    tags_item = next(i for i in items if "话题组" in i["label"])
    assert tags_item["satisfied"] is True
    assert tags_item["note"] == ""
    empty_pack: dict[str, object] = {"tags": []}
    empty_items = publish_pack.build_checklist(
        empty_pack, drama_name="发布剧", drama_name_layer_enabled=True,
    )
    empty_tags = next(i for i in empty_items if "话题组" in i["label"])
    assert empty_tags["satisfied"] is False
    assert empty_tags["note"] != ""


def test_checklist_no_fake_granting_wording() -> None:
    """清单文案不得出现「已替你取得授权」类假绿措辞（2026-09-10 裁决 + 文案真值扫描）。"""
    pack = publish_pack.build_pack([{"text": "标题", "selected": True}], None, ["爽剧"])
    items = publish_pack.build_checklist(pack, drama_name="发布剧", drama_name_layer_enabled=True)
    joined = " ".join(str(i["label"]) + i["note"] for i in items)
    assert "已替你" not in joined and "已取得授权" not in joined and "自动完成" not in joined
