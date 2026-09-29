"""narration.copywriter：槽位 → LLM → 文案。降级禁止，故所有失败路径都必须是异常。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import casting, copywriter
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes_w8 import build_full
from dramaclip.engines.semantic.llm_client import LlmUnavailable
from dramaclip.engines.semantic.models import ConflictScore

_SETTINGS = {
    "llm.base_url": "http://llm.test/v1",
    "llm.api_key": "sk-test",
    "llm.model": "test-model",
    "_project_name": "透视眼",
    "_genre": "复仇",
    "_style_directives": "强节奏，多用短句砸爽点",
}

# Task 4 传的是 pipeline 的模式标签表；这里用一个真标签，不传空串糊过去
_MODE_LABEL = "全片解说"

_SCENES = [
    ConflictScore(scene_index=i, start=i * 12.0, end=i * 12.0 + 10.0, score=s)
    for i, s in enumerate([60, 85, 45, 90])
]

_SEGMENTS = [
    AsrSegment(start=i * 12.0 + 1, end=i * 12.0 + 5, text=f"第 {i} 幕的原话")
    for i in range(4)
]

# 单集夹具：一张只有一集的取材原料表。跨集的用例在下面自己搭两集。
_MATERIAL: casting.MaterialByEpisode = {
    "ep1": casting.EpisodeMaterial(number=1, asr=_SEGMENTS)
}


class FakeLlm:
    """按队列应答 chat_json，记录每次 system/user 供断言。"""

    calls: list[str] = []
    systems: list[str] = []
    queue: list[Any] = []

    def __init__(self, _config: Any, timeout_s: float = 60.0) -> None:
        self.timeout_s = timeout_s

    def chat_json(self, system: str, user: str) -> Any:
        FakeLlm.calls.append(user)
        FakeLlm.systems.append(system)
        item = FakeLlm.queue.pop(0) if len(FakeLlm.queue) > 1 else FakeLlm.queue[0]
        if isinstance(item, Exception):
            raise item
        return item


def _plan():
    return build_full(casting.stamp([(1, "ep1", _SCENES)]), StrategySpec())


def _lines() -> dict[str, Any]:
    return {
        "lines": [
            {"id": f"full-{i + 1}", "text": f"第 {i + 1} 条解说"}
            for i in range(len(_SCENES))
        ]
    }


@pytest.fixture()
def llm(monkeypatch: pytest.MonkeyPatch) -> Any:
    FakeLlm.calls = []
    FakeLlm.systems = []
    FakeLlm.queue = []
    monkeypatch.setattr(copywriter, "LlmClient", FakeLlm)
    return FakeLlm


def test_fills_every_slot_and_flips_planner(llm: Any) -> None:
    llm.queue = [_lines()]
    plan = copywriter.write_plan_copy(
        _plan(), _MATERIAL, _SETTINGS, mode_label=_MODE_LABEL, angle_block=""
    )
    assert plan.planner == "llm_script"
    assert [t.text for t in plan.narration_texts] == [
        "第 1 条解说", "第 2 条解说", "第 3 条解说", "第 4 条解说"
    ]


def test_prompt_carries_slot_brief_and_local_transcript(llm: Any) -> None:
    """台词必须按槽位各自的画面区间分发——只在 prompt 里"出现过"等于没验。"""
    llm.queue = [_lines()]
    copywriter.write_plan_copy(
        _plan(), _MATERIAL, _SETTINGS, mode_label=_MODE_LABEL, angle_block=""
    )
    prompt = llm.calls[0]
    assert "透视眼" in prompt and "复仇" in prompt
    assert "强节奏" in prompt, "口味层指令未注入"
    assert "模式：全片解说" in prompt, "模式标签未进 prompt"
    block = prompt.split("[full-2]")[1].split("[full-3]")[0]
    assert "要做的事：" in block and "高潮" in block, "槽位职责未随本槽进 prompt"
    assert "画面区间：12.0-22.0s" in block, "区间必须取自配对画面段"
    assert "第 1 幕的原话" in block, "台词必须落在自己区间的槽位下"
    assert "第 0 幕的原话" not in block and "第 2 幕的原话" not in block, "槽位之间不许串台词"


def test_slot_without_transcript_forbids_invention(llm: Any) -> None:
    """无转写可依据时（该区间一句台词没有）必须明写"不得编造"：每个槽位都得看到这句。"""
    llm.queue = [_lines()]
    silent = {"ep1": casting.EpisodeMaterial(number=1, asr=[])}
    copywriter.write_plan_copy(_plan(), silent, _SETTINGS, mode_label=_MODE_LABEL, angle_block="")
    prompt = llm.calls[0]
    assert prompt.count("（该区间无台词转写") == len(_SCENES), "每个空区间槽位都要有禁止编造的提示"


def test_missing_slot_raises(llm: Any) -> None:
    llm.queue = [{"lines": [{"id": "full-1", "text": "只写了一条"}]}]
    with pytest.raises(ValueError, match="漏了 3 个槽位"):
        copywriter.write_plan_copy(
        _plan(), _MATERIAL, _SETTINGS, mode_label=_MODE_LABEL, angle_block=""
    )


def test_retries_once_then_raises(llm: Any) -> None:
    llm.queue = [LlmUnavailable("网关 502"), {"lines": []}]
    with pytest.raises(ValueError, match="网关 502") as excinfo:
        copywriter.write_plan_copy(
        _plan(), _MATERIAL, _SETTINGS, mode_label=_MODE_LABEL, angle_block=""
    )
    assert len(llm.calls) == 2, "应重试一次"
    # 槽位 id 只出现在漏答详情里一次：包装语再列一遍等于给队列页刷屏
    assert str(excinfo.value) == (
        "编剧未产出合格文案：LlmUnavailable: 网关 502；"
        "ValueError: 编剧漏了 4 个槽位：full-1, full-2, full-3, full-4"
    )


def test_unconfigured_llm_raises_before_prompt(llm: Any) -> None:
    settings = dict(_SETTINGS)
    settings["llm.model"] = ""
    with pytest.raises(LlmUnavailable, match="文案必须由编剧模型产出"):
        copywriter.write_plan_copy(
            _plan(), _MATERIAL, settings, mode_label=_MODE_LABEL, angle_block=""
        )
    assert llm.calls == []


def test_oversize_line_rejected(llm: Any) -> None:
    """超出 60 字 ×1.2 容忍即判没答：重试一次仍超长就抛，不得把长句塞进成片。"""
    over = "长" * 80
    llm.queue = [
        {"lines": [{"id": f"full-{i + 1}", "text": over} for i in range(len(_SCENES))]}
    ]
    with pytest.raises(ValueError, match="未产出合格文案"):
        copywriter.write_plan_copy(
        _plan(), _MATERIAL, _SETTINGS, mode_label=_MODE_LABEL, angle_block=""
    )
    assert len(llm.calls) == 2, "超长应触发一次重问"


def test_unknown_ids_never_count_as_answers(llm: Any) -> None:
    """模型自己造 id 等于一条没答：不按位置凑数，也不让野生日 id 拿到校验资格。

    四条 id 全不在 plan 里，其中一条还超长——若未知 id 逃不过长度校验，说明
    `key not in wanted` 的丢弃分支没了：报错会被那条不存在的槽位劫持，
    而真正该说的是「我们问的 4 个槽位一个都没回」。
    """
    llm.queue = [{"lines": [
        {"id": "full-9", "text": "模型自造的槽位" + "长" * 80},
        {"id": "full-0", "text": "还是自造的"},
        {"id": "intro-2", "text": "这轮回的压根不是 full_narration 的 id"},
        {"id": "dual-1", "text": "第四条也是"},
    ]}]
    with pytest.raises(ValueError, match="漏了 4 个槽位") as excinfo:
        copywriter.write_plan_copy(
        _plan(), _MATERIAL, _SETTINGS, mode_label=_MODE_LABEL, angle_block=""
    )
    message = str(excinfo.value)
    assert "full-1, full-2, full-3, full-4" in message, "报错须点名我们要的槽位"
    assert "full-9" not in message, "未知 id 应被静默丢弃，不该出现在报错里"
    assert len(llm.calls) == 2, "答非所问同样要重问一次"


def test_empty_answer_counts_as_no_answer(llm: Any) -> None:
    """某槽位交白卷就是没交：漏答报错必须点名它，绝不能把空串当解说填进成片。"""
    blanked = _lines()
    blanked["lines"][1]["text"] = ""
    llm.queue = [blanked]
    with pytest.raises(ValueError, match="漏了 1 个槽位") as excinfo:
        copywriter.write_plan_copy(
        _plan(), _MATERIAL, _SETTINGS, mode_label=_MODE_LABEL, angle_block=""
    )
    assert "full-2" in str(excinfo.value)
    assert len(llm.calls) == 2, "空答同样要重问一次"


def test_trace_lands_on_the_raise_path(llm: Any, tmp_path: Path) -> None:
    """抛异常也必须留痕：那个文件是唯一能事后审计「模型到底被问了什么」的证据。"""
    llm.queue = [{"lines": [{"id": "full-1", "text": "只回了一条"}]}]
    with pytest.raises(ValueError, match="漏了 3 个槽位"):
        copywriter.write_plan_copy(
            _plan(), _MATERIAL, _SETTINGS, mode_label=_MODE_LABEL, angle_block="",
            trace_dir=tmp_path
        )
    traces = list(tmp_path.glob("llm_copy_full_narration_*.json"))
    assert len(traces) == 1, f"失败路径同样要落盘，实得 {traces}"
    payload = json.loads(traces[0].read_text(encoding="utf-8"))
    assert "full-2" in payload["attempts"][0]["error"], "留痕要点名漏答的槽位"
    assert "画面区间" in payload["user"], "留痕要能还原模型实际看到的区间"


def test_slot_without_paired_segment_raises(llm: Any) -> None:
    """槽位没有配对画面段＝编排器漏写 narration_id：抛，绝不退化成"没有区间的槽位"瞎写。"""
    stripped = _plan()
    plan = stripped.model_copy(update={
        "timeline": [
            segment.model_copy(update={"narration_id": None}) for segment in stripped.timeline
        ]
    })
    llm.queue = [_lines()]  # 就算真去问网关，答案也是齐的：红线只能来自"压根不该问"
    with pytest.raises(ValueError, match="full-1 没有配对画面段"):
        copywriter.write_plan_copy(
            plan, _MATERIAL, _SETTINGS, mode_label=_MODE_LABEL, angle_block=""
        )
    assert llm.calls == [], "prompt 都拼不出来，不该浪费一次网关调用"


_ANGLE_BLOCK = (
    "\n本条片的取材角度：复仇线"
    "\n这条角度为什么成立：第 3 集反杀最狠"
    "\n开场钩子首句（第一个槽位据此下笔，可改写措辞但不得换卖点）：他跪着进了门"
)


def test_angle_block_reaches_the_prompt(llm: Any) -> None:
    """角度是 K 条方案唯一的差异化来源：它没进 prompt，K 条就只是同一部片切 K 次。"""
    llm.queue = [_lines()]
    copywriter.write_plan_copy(
        _plan(), _MATERIAL, _SETTINGS, mode_label="全片解说", angle_block=_ANGLE_BLOCK
    )
    prompt = llm.calls[0]
    assert "复仇线" in prompt, "角度名未进 prompt"
    assert "第 3 集反杀最狠" in prompt, "选题理由未进 prompt"
    assert "他跪着进了门" in prompt, "钩子首句未进 prompt"


def test_angle_block_is_not_written_into_the_copy(llm: Any) -> None:
    """角度块是给模型的指令，不是文案：落库的 text 必须仍是模型答的那句。"""
    llm.queue = [_lines()]
    plan = copywriter.write_plan_copy(
        _plan(), _MATERIAL, _SETTINGS, mode_label="全片解说", angle_block=_ANGLE_BLOCK
    )
    assert all("复仇线" not in text.text for text in plan.narration_texts)
    assert all("他跪着进了门" not in text.text for text in plan.narration_texts)


def _two_episode_plan() -> tuple[Any, casting.MaterialByEpisode]:
    """跨集夹具：两个槽位压在**同样的 12.0-22.0s**，只是分属两集。

    秒轴刻意重合，因为活库实测十集的场景起点全部从 `0.0` 开始——集与集的集内相对秒
    互相覆盖是常态而不是边角情况。摊平一张 ASR 表按秒过滤的实现，在这里会把两集的
    对白都塞进每一个槽位。
    """
    scenes = casting.stamp(
        [
            (1, "ep1", [ConflictScore(scene_index=0, start=12.0, end=22.0, score=90)]),
            (2, "ep2", [ConflictScore(scene_index=0, start=12.0, end=22.0, score=88)]),
        ]
    )
    plan = build_full(scenes, StrategySpec())
    material: casting.MaterialByEpisode = {
        "ep1": casting.EpisodeMaterial(
            number=1, asr=[AsrSegment(start=13.0, end=16.0, text="第一集的原话")]
        ),
        "ep2": casting.EpisodeMaterial(
            number=2, asr=[AsrSegment(start=13.0, end=16.0, text="第二集的原话")]
        ),
    }
    return plan, material


def test_a_slot_is_grounded_in_its_own_episodes_dialogue(llm: Any) -> None:
    """跨集时间轴上，槽位只能读**它那一集**的台词（规格 §1 跨集的前置条件）。

    这是本轮最关键的一条用例：错的取材不会报错、不会降级，成片看着完全正常，
    而解说讲的是另一集的事。system prompt 明写「情节、细节、称谓只能来自给定台词」，
    所以模型会老老实实照着**喂错的那份台词**写——缺陷在喂料侧，不在模型侧。

    前两个断言钉的是**夹具前提**：两集的秒轴必须重合，否则摊平实现也能碰巧答对，
    这条用例就变成一条永远绿、什么也没守着的断言（B6 同一类）。
    """
    plan, material = _two_episode_plan()
    assert [seg.episode_id for seg in plan.timeline] == ["ep1", "ep2"], "夹具前提塌了"
    assert [(seg.start, seg.end) for seg in plan.timeline] == [(12.0, 22.0)] * 2, (
        "夹具前提塌了：两集的秒轴必须重合，否则摊平实现也能碰巧答对"
    )
    llm.queue = [
        {
            "lines": [
                {"id": text.id, "text": f"{text.id} 的解说"}
                for text in plan.narration_texts
            ]
        }
    ]
    copywriter.write_plan_copy(
        plan, material, _SETTINGS, mode_label=_MODE_LABEL, angle_block=""
    )
    prompt = FakeLlm.calls[0]
    head, _, tail = prompt.partition("[full-2]")
    assert "第一集的原话" in head and "第二集的原话" not in head, (
        "第一个槽位读到了别的集的台词"
    )
    assert "第二集的原话" in tail and "第一集的原话" not in tail, (
        "第二个槽位读到了别的集的台词"
    )
    assert "第1集" in head and "第2集" in tail, (
        "跨集时间轴上槽位不报集名，等于没报区间——模型无从判断相邻两槽是不是同一条线"
    )


def test_a_slot_whose_episode_is_missing_from_the_material_raises(llm: Any) -> None:
    """缺键 ≠「这一集没有台词」：静默当成没台词会让编剧写出一段什么都不说的解说。

    `_slot_block` 本来就有"该区间无台词转写"这一支（素材事实，合法，见上面那条
    `test_slot_without_transcript_forbids_invention`），所以缺键必须走**另一条**路。
    `match` 只写到「槽位 full-2：集 ep2」为止，不写后半句：`dialogue_of` 与 `label_of`
    各有一句自己的消息，写死后半句会让这条用例绑死"哪个查找先抛"，而两者都抛才对。
    两条消息各自由 `test_casting.py` 钉住。
    """
    plan, material = _two_episode_plan()
    del material["ep2"]
    llm.queue = [_lines()]
    with pytest.raises(ValueError, match=r"槽位 full-2：集 ep2"):
        copywriter.write_plan_copy(
            plan, material, _SETTINGS, mode_label=_MODE_LABEL, angle_block=""
        )
    assert llm.calls == [], "缺料就该在发请求之前拦住，不该先付一次成稿"


_FLOOR = "【解说基本功——逐条强制遵守】\n只准写短句。"


def _copy(**prompts: str) -> str:
    FakeLlm.calls = []
    FakeLlm.systems = []
    FakeLlm.queue = [_lines()]
    copywriter.write_plan_copy(
        _plan(), _MATERIAL, {**_SETTINGS, **prompts}, mode_label=_MODE_LABEL, angle_block=""
    )
    return FakeLlm.systems[0]


def test_default_copy_prompt_carries_the_floor(llm: Any) -> None:
    assert "【解说基本功——逐条强制遵守】" in _copy()


def test_floor_override_reaches_the_copy_prompt(llm: Any) -> None:
    """基本功卡是编剧与填词共用的：导入期把文本拼死，这张卡对填词就是死的。"""
    system = _copy(**{"prompt.scriptwriter_fundamentals": _FLOOR})
    assert "只准写短句。" in system
    assert "悬念管理" not in system


def test_copy_structure_override_replaces_only_the_structure(llm: Any) -> None:
    system = _copy(**{"prompt.copywriter_system": "只回 JSON。"})
    assert system.startswith("只回 JSON。")
    assert "lines 必须覆盖全部槽位" not in system
    assert "【解说基本功——逐条强制遵守】" in system
