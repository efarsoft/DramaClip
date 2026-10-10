"""审计器单测：守住「规则锚定 prompt 原文」+ 硬/软判定正确。

不与 LLM 交互，纯确定式审查。
"""

from __future__ import annotations

from dramaclip.engines.narration import audit as A

_TRANSCRIPT = [
    {
        "episode": 1, "start": 0.0, "end": 12.5, "speaker": "[角色A]",
        "text": "[角色A]：苏明月，你这般贱婢也配进我苏府大门？",
    },
    {
        "episode": 1, "start": 12.5, "end": 24.0, "speaker": "[角色B]",
        "text": "[角色B]：姐姐莫怕，这婚书是我替你藏下的。",
    },
    {
        "episode": 1, "start": 24.0, "end": 38.0, "speaker": "[角色A]",
        "text": "[角色A]：八千两银子，够买你半条命了。",
    },
    {
        "episode": 2, "start": 0.0, "end": 15.0, "speaker": "[角色C]",
        "text": "[角色C]：摄政王到，众人跪迎。",
    },
    {
        "episode": 2, "start": 15.0, "end": 30.0, "speaker": "[角色B]",
        "text": "[角色B]：原来那夜救我的，竟是当朝九千岁。",
    },
]


def _good_script() -> dict:
    return {
        "hook": "全城最怂的账房先生，竟是黑帮最怕的杀手。",
        "segments": [
            {
                "episode": 1, "start": 0.0, "end": 12.5,
                "text": "苏明月被嫡姐当众羞辱，婚书却早被妹妹藏下。",
            },
            {"episode": 1, "start": 24.0, "end": 38.0, "text": "八千两银子，够买她半条命。"},
        ],
        "cta": "她到底是谁救的？点击左下角，免费看全集。",
    }


def _bad_script() -> dict:
    return {
        "hook": "他竟然藏着惊天秘密，后续更精彩！",
        "segments": [
            {
                "episode": 1, "start": 0.0, "end": 12.5,
                "text": "在这镜头里，苏明月被[角色A]当众羞辱。",
            },
            {"start": 13.0, "end": 60.0, "text": "八千两银子买半条命，[角色A]狠辣尽显。"},
            {"episode": 2, "start": 0.0, "end": 30.0, "text": "摄政王到场，局势陡变。"},
        ],
        "cta": "点个赞关注我，下集更精彩！",
    }


def test_good_script_passes_hard() -> None:
    rep = A.review_script(_good_script(), _TRANSCRIPT)
    assert rep.passed, rep.summary_line()
    assert not rep.hard_fails


def test_bad_script_flags_exact_rules() -> None:
    rep = A.review_script(_bad_script(), _TRANSCRIPT)
    failed = {f.rule_id for f in rep.hard_fails}
    # 预埋缺陷必须被精确点名
    assert "STRUCT_EPISODE_REQUIRED" in failed   # 缺 episode
    assert "STRUCT_TIME_BOUNDS" in failed         # end=60 超 ep1 上界 38
    assert "STRUCT_HOOK_FACT" in failed           # 空泛悬念
    assert "STRUCT_CTA_FORBIDDEN" in failed       # 点赞/关注
    assert "FUND_NO_METANARRATIVE" in failed      # 镜头


def test_finding_anchors_prompt_quote() -> None:
    rep = A.review_script(_bad_script(), _TRANSCRIPT)
    by_id = {f.rule_id: f for f in rep.findings}
    # 每条 finding 必须带回 prompt 原文（溯源，防止规则静默失效）
    assert by_id["STRUCT_EPISODE_REQUIRED"].prompt_quote
    assert "episode" in by_id["STRUCT_EPISODE_REQUIRED"].prompt_quote


def test_review_copy_catches_missing_slot_and_meta() -> None:
    slots = [
        {"id": "s1", "task": "开场", "start": 0.0, "end": 12.5, "lines": "x"},
        {"id": "s2", "task": "点银两", "start": 24.0, "end": 38.0, "lines": "y"},
    ]
    bad_lines = [
        {"id": "s1", "text": "苏明月被当众羞辱，这镜头看得人牙痒。"},  # s2 漏 + 镜头
    ]
    rep = A.review_copy(bad_lines, slots)
    failed = {f.rule_id for f in rep.hard_fails}
    assert "COPY_COVER_ALL_IDS" in failed
    assert "COPY_NO_METANARRATIVE" in failed


def test_review_copy_good_passes() -> None:
    slots = [{"id": f"s{i}", "task": "t", "start": 0.0, "end": 5.0, "lines": "x"} for i in range(3)]
    lines = [{"id": f"s{i}", "text": "短句文案，无元叙述，声纹已换名。"} for i in range(3)]
    rep = A.review_copy(lines, slots)
    assert rep.passed


def test_propose_aggregates_repeated_hard_fails() -> None:
    recs = []
    for _ in range(3):
        rep = A.review_script(_bad_script(), _TRANSCRIPT)
        recs += A._flat(rep.findings, sample_id="demo")
    props = A.propose_prompt_tweaks(recs, min_hits=2)
    ids = {p["rule_id"] for p in props}
    assert "STRUCT_EPISODE_REQUIRED" in ids
    assert all(p["fail_count"] >= 2 for p in props)
    # 建议必须带当前 prompt 原文
    assert all(p["current_prompt"] for p in props)


def test_real_fanfiction_sample_surfaces_soft_risks() -> None:
    """真实出稿：结构全过但内容为编造时，审计器不能假绿。

    复现 2026-10-10 用户样本：模型为凑「真实锚点」硬造「八千两/九千岁」，
    并用「竟是」抖包袱。无转写时仍须把这些标成 soft 需人工复核。
    """
    import json
    import pathlib
    here = pathlib.Path(__file__).resolve().parent
    sample = json.loads(
        (here.parent.parent.parent / "review_fixtures" / "real_script_user.json")
        .read_text(encoding="utf-8")
    )
    rep = A.review_script(sample, transcript=None)  # 无转写：编造检查跳过，但新软规则必须触发
    flagged = {f.rule_id for f in rep.soft_flags}
    assert "FUND_NO_REVEAL_TELL" in flagged        # segment[2] 「竟是当朝九千岁」
    assert "FUND_NO_INVENTED_ANCHOR" in flagged    # 「八千两」「九千岁」转写外硬锚点
    assert "FUND_CROSS_EPISODE_BRIDGE" in flagged  # ep1→ep2 跨集需人工确认因果
    # 结构上仍判 PASS（无 hard 失守），但绝不能「无脑全绿」
    assert rep.passed
    assert rep.soft_flags  # 至少要有风险提示，禁止吞掉

