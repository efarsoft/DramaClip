"""审计器单测：守住「规则锚定 prompt 原文」+ 硬/软判定正确。

不与 LLM 交互，纯确定式审查。
"""

from __future__ import annotations

from typing import Any

from dramaclip.engines.narration import audit as A
from dramaclip.engines.narration.audit import (
    review_script,  # noqa: F401 - 追加用例经 review_script 直呼
)

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

    复现 2026-10-10 用户样本：模型为凑「真实锚点」硬造「八千两/九千岁」。
    揭晓腔规则已按业主裁决移除（竟/居然合法），无转写时仍须把编造锚点、
    跨集因果标成 soft 需人工复核。
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
    assert "FUND_NO_INVENTED_ANCHOR" in flagged    # 「八千两」「九千岁」转写外硬锚点
    assert "FUND_CROSS_EPISODE_BRIDGE" in flagged  # ep1→ep2 跨集需人工确认因果
    # 结构上仍判 PASS（无 hard 失守），但绝不能「无脑全绿」
    assert rep.passed
    assert rep.soft_flags  # 至少要有风险提示，禁止吞掉



def _seg_text(text: str) -> dict[str, Any]:
    return {"episode": 1, "start": 0.0, "end": 2.0, "text": text}


def test_narrative_texture_flags_suspense_and_imagery() -> None:
    """悬问连发 + 意象超配额 → 软标记（needs_human），不拦片。"""
    script = {
        "hook": "他背着一口锅",
        "segments": [
            _seg_text("三千两黄金说没就没？"),
            _seg_text("两千斤铁锅挡下名剑？"),
            _seg_text("三千两借据烧成灰？"),
            _seg_text("两千斤铁锅裂了纹？"),
            _seg_text("三千两银票成了废纸？"),
        ],
        "cta": "点击左下角看全集",
    }
    report = A.review_script(script, [])
    by_id = {f.rule_id: f for f in report.findings}
    assert by_id["NARR_SUSPENSE_QUOTA"].passed is False
    assert by_id["NARR_SUSPENSE_QUOTA"].needs_human is True
    assert by_id["NARR_IMAGE_QUOTA"].passed is False, "三千两出现三段，超配额"


def test_narrative_texture_healthy_passes() -> None:
    """配额内 + 有情绪落点 → 不标记。"""
    script = {
        "hook": "他背着一口锅下了山",
        "segments": [
            _seg_text("他攥紧了指节，把炖软的肉端上桌"),
            _seg_text("师傅们连干了三碗，谁也没说话"),
            _seg_text("山下的集市比想象里吵得多"),
            _seg_text("他愣在原地，钱袋子还攥在手里"),
            _seg_text("一条街之外，有人锁了大门"),
        ],
        "cta": "点击左下角看全集",
    }
    report = A.review_script(script, [])
    for f in report.findings:
        if f.rule_id in ("NARR_SUSPENSE_QUOTA", "NARR_IMAGE_QUOTA", "NARR_EMOTION_BEAT"):
            assert f.passed is True, f.rule_id


def test_person_intro_repeat_flags_second_full_intro() -> None:
    """同一人物两次全套介绍 → FUND_PERSON_INTRO_ONCE 软标记（需人工），不拦片。"""
    script = {
        "hook": "她替嫁进了将军府",
        "segments": [
            _seg_text("苏明月，将军府嫡女，却在府里连下人都不如。"),
            _seg_text("她熬了整整三年。"),
            _seg_text("苏明月，将军府嫡女，今天终于要反击了。"),
        ],
        "cta": "点击左下角看全集",
    }
    report = A.review_script(script, [])
    by_id = {f.rule_id: f for f in report.findings}
    finding = by_id["FUND_PERSON_INTRO_ONCE"]
    assert finding.passed is False
    assert finding.severity == "soft" and finding.needs_human is True
    assert "苏明月" in finding.message and "×2" in finding.message


def test_person_intro_healthy_passes_and_prior_carried() -> None:
    """无重复 → 通过；前集已介绍过的人物本稿再走全套 → CARRIED 软标记；
    无 prior 数据时 CARRIED 规则不参审（不该装作查过）。"""
    healthy = {
        "hook": "她替嫁进了将军府",
        "segments": [
            _seg_text("苏明月，将军府嫡女，却在府里连下人都不如。"),
            _seg_text("王承恩，司礼监秉笔太监，是她在宫里唯一的靠山。"),
            _seg_text("两人立下血誓，共赴绝路。"),
        ],
        "cta": "点击左下角看全集",
    }
    report = A.review_script(healthy, [])
    by_id = {f.rule_id: f for f in report.findings}
    assert by_id["FUND_PERSON_INTRO_ONCE"].passed is True
    assert by_id["FUND_PERSON_INTRO_ONCE"].needs_human is False
    assert "FUND_PERSON_INTRO_CARRIED" not in by_id

    prior = ["上一条视频里，苏明月，将军府嫡女，刚被退了婚。"]
    carried_report = A.review_script(healthy, [], prior_texts=prior)
    carried = {f.rule_id: f for f in carried_report.findings}
    assert carried["FUND_PERSON_INTRO_ONCE"].passed is True, "本稿内各介绍一次不算重复"
    assert carried["FUND_PERSON_INTRO_CARRIED"].passed is False
    assert "苏明月" in carried["FUND_PERSON_INTRO_CARRIED"].message
    assert "王承恩" not in carried["FUND_PERSON_INTRO_CARRIED"].message, (
        "只报前集介绍过的人物"
    )


def test_metanarrative_catches_chinese_numeral_form() -> None:
    """数字中文化先于内联审查跑：「第3集」出口已成「第三集」——零容忍规则必须认中文数词。"""
    script = {
        "hook": "她替嫁进了将军府",
        "segments": [_seg_text("第三集，她终于反击。")],
        "cta": "点击左下角看全集",
    }
    report = A.review_script(script, [])
    meta = [f for f in report.findings if f.rule_id == "FUND_NO_METANARRATIVE"]
    assert meta and meta[0].passed is False, "「第三集」是元叙述，中文数词形态不得漏检"


def test_time_bounds_prefers_episode_durations_over_transcript_tail() -> None:
    """整集时长注入后，摘录尾之外的合法尾场不再硬判超界（与清洗层同一真相源）。"""
    script = {
        "hook": "她背着一口锅",
        "segments": [{"episode": 1, "start": 110.0, "end": 118.0, "text": "尾场打斗，她赢了。"}],
        "cta": "",
    }
    transcript = [{"episode": 1, "start": 0.0, "end": 105.0, "speaker": "A", "text": "台词"}]
    old_scope = A.review_script(script, transcript)
    new_scope = A.review_script(script, transcript, episode_durations={1: 120.0})
    by_old = {f.rule_id: f for f in old_scope.findings}
    by_new = {f.rule_id: f for f in new_scope.findings}
    assert by_old["STRUCT_TIME_BOUNDS"].passed is False, "旧口径（摘录尾 105s）确实会误判"
    assert by_new["STRUCT_TIME_BOUNDS"].passed is True, "整集时长口径放行合法尾场"


def test_phrase_monotony_flags_three_same_head_or_tail() -> None:
    """连续三段同头/同尾＝模板感（批1 宣称的「句式雷同」判据补齐）。"""
    script = {
        "hook": "她替嫁进了将军府",
        "segments": [
            _seg_text("他竟敢欺她失势。"),
            _seg_text("他竟敢退她婚约。"),
            _seg_text("他竟敢断她生路。"),
            _seg_text("山下的集市比想象里吵得多。"),
        ],
        "cta": "点击左下角看全集",
    }
    report = A.review_script(script, [])
    mono = [f for f in report.findings if f.rule_id == "NARR_PHRASE_MONOTONY"]
    assert mono and mono[0].passed is False
    assert "他竟" in mono[0].message


def test_episode_jump_flags_non_adjacent_leap() -> None:
    """相邻段集号跨度 >1：相邻优先承诺失守，点名交人工（soft）。"""
    script = {
        "hook": "她背着一口锅",
        "segments": [
            {"episode": 1, "start": 0.0, "end": 2.0, "text": "铺垫。"},
            {"episode": 4, "start": 0.0, "end": 2.0, "text": "大跨度跳集的爆点。"},
        ],
        "cta": "点击左下角看全集",
    }
    report = A.review_script(script, [])
    jump = [f for f in report.findings if f.rule_id == "STRUCT_EPISODE_JUMP"]
    assert jump and jump[0].passed is False
    assert jump[0].severity == "soft"


def test_copy_line_cap_accepts_production_tolerance() -> None:
    """review 与生产同容差（cap×1.2）：61–72 字的生产放行稿不得在审查里恒 REJECT。"""
    report = A.review_copy(
        [{"id": "a", "text": "字" * 65}], [{"id": "a"}], mode="full_narration"
    )
    line = [f for f in report.findings if f.rule_id == "COPY_LINE_CAP"]
    assert line and line[0].passed is True, "65 字 ≤ 72（60×1.2）生产容差，审查不得翻脸"


def test_all_prompt_quotes_are_literal_substrings() -> None:
    """守卫（注册表单源版）：规则原文只存 prompt_rules 一处，字面一致由装配构造
    恒真——这条守卫查的是三件仍然需要人守的事：
    ① audit 引用的每个 key 在注册表里存在（拼错 key 当场爆，不静默）；
    ② 注册表每条原文仍是装配后 prompt 常量的字面子串（防有人绕开注册表手改
       常量，让 {key} 占位与注册表值各活各的）；
    ③ 注册表没有孤儿条目（每条都被 audit 引用——注册表烂掉的起点就是没人
       记得某条还在不在用）。"""
    import ast
    import inspect

    from dramaclip.engines.narration import copywriter as C
    from dramaclip.engines.narration import scriptwriter as S
    from dramaclip.engines.narration.prompt_rules import RULE_TEXTS

    texts = []
    for mod in (S, C):
        for name in dir(mod):
            value = getattr(mod, name)
            if isinstance(value, str) and len(value) > 30:
                texts.append(value)

    tree = ast.parse(inspect.getsource(A))
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "prompt_quote":
            if not isinstance(node.value, ast.Subscript):
                continue  # f-string 动态 quote（行长两条）由现有用例覆盖
            key_node = node.value.slice
            if isinstance(key_node, ast.Constant):
                used.add(str(key_node.value))
    unknown = sorted(used - set(RULE_TEXTS))
    assert unknown == [], f"audit 引用了注册表不存在的 key：{unknown}"

    orphans = sorted(set(RULE_TEXTS) - used)
    assert orphans == [], f"注册表存在无人引用的孤儿条目（删掉或接线）：{orphans}"

    homeless = [
        key for key, text in RULE_TEXTS.items()
        if not any(text in candidate for candidate in texts)
    ]
    assert homeless == [], f"以下注册表原文不再出现在任何 prompt 常量中：{homeless}"


def test_hook_payoff_flags_unfulfilled_anchor() -> None:
    """钩子抛出「玉佩」正文全部未再现＝标题党悬空（软标记需人工）。"""
    script = {
        "hook": "他攥着那块玉佩，追了三条街",
        "segments": [_seg_text("她转身离府，再没回头。"), _seg_text("马车出了城门。")],
        "cta": "点击左下角看全集",
    }
    report = A.review_script(script, [])
    payoff = [f for f in report.findings if f.rule_id == "FUND_HOOK_PAYOFF"]
    assert payoff and payoff[0].passed is False
    assert "玉佩" in payoff[0].message


def test_hook_payoff_passes_when_anchor_recurs() -> None:
    """钩子锚点（三千两）在正文再现＝兑现；纯抽象钩子无锚点不判。"""
    fulfilled = {
        "hook": "她背着一口锅，欠下三千两",
        "segments": [_seg_text("三千两借据烧成灰，她一无所有。")],
        "cta": "点击左下角看全集",
    }
    by_id = {f.rule_id: f for f in A.review_script(fulfilled, []).findings}
    assert by_id["FUND_HOOK_PAYOFF"].passed is True

    abstract = {
        "hook": "谁能想到她会这样反击",
        "segments": [_seg_text("她掀了桌子，全场安静。")],
        "cta": "点击左下角看全集",
    }
    by_id2 = {f.rule_id: f for f in A.review_script(abstract, []).findings}
    assert by_id2["FUND_HOOK_PAYOFF"].passed is True, "锚点抓不到的抽象钩子不判（宁漏勿冤）"
