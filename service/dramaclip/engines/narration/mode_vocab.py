"""模式词汇表：九模式的唯一清单家（ModeSpec 注册表）与派生集合。

为什么住在 engines：模式是领域词汇，不是 RPC 词汇——选题/裁决/审计/规划执行
（flows）都要按它分流，api 只有受理校验需要读它。改模式名只动这里；消费方
（api/narration 的受理校验、export_audit、前端契约对表）各自单向引入。

加/下线一个模式 = 改一行注册 spec：SUPPORTED/_NO_TTS/_NARRATION/_SCRIPT_DRIVEN
四张表全部由注册行派生，不再各自手抄（手抄漏条目的漂移实证——2026-10-16 规格
§1.1，那次漏的是高光混剪；教训是表越多越会漏，一张注册表没有第二处可漏）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModeSpec:
    """单模式的全部注册属性。

    ``tts``：要不要配音（TTS 缺位=纯剪辑/字幕流）。零文案历史上与「无 TTS」
    同值（无配音 ⇔ 无旁白槽位，_ZERO_COPY_MODES 仍是别名不另立第四张表）。
    ``script_driven``：这条方案的时间轴**不是** (mode, 取材集) 的纯函数——
    剧本由模型按角度现写（script_driver.script_dialogue_plan），成稿**前**的
    同集重叠闸门（_reject_same_episode_sibling）对它无效，只能靠成稿**后**的
    _worst_overlap 兜（详见 flows.narration）。
    """

    name: str
    tts: bool
    script_driven: bool


# 注册顺序 = SUPPORTED_MODES 顺序（推荐菜单/方案卡按此序出）。
_MODE_SPECS: tuple[ModeSpec, ...] = (
    ModeSpec("raw_clip", tts=False, script_driven=False),
    # 高光混剪（highlight_cut）2026-10-27 业主裁决并入纯原片剪辑（raw_clip 单入口，
    # 5 秒均切取消），2026-11-12 完全清除：生成/渲染/消费分支全删，存量方案行由
    # migrations/027 删除，历史推荐缓存由 mode_recommend 读时净化。

    ModeSpec("intro_narration", tts=True, script_driven=False),
    ModeSpec("cross_narration", tts=True, script_driven=False),
    ModeSpec("ultra_short_hook", tts=True, script_driven=False),
    ModeSpec("dialogue_narration", tts=True, script_driven=True),
    ModeSpec("full_narration", tts=True, script_driven=False),
    ModeSpec("subtitle_flow", tts=False, script_driven=False),
    ModeSpec("dual_host_chat", tts=True, script_driven=False),
    ModeSpec("inner_monologue", tts=True, script_driven=False),
)

SUPPORTED_MODES = tuple(spec.name for spec in _MODE_SPECS)

# 与 TTS 合成并行的两组：剧情解说已由 LLM 剧本驱动，每段都要配音，不再属"无 TTS"。
_NO_TTS_MODES = frozenset(spec.name for spec in _MODE_SPECS if not spec.tts)
# 零文案模式（=_NO_TTS_MODES）：没有旁白槽位，母题/钩子/句式约束无处落地——
# 选题换零文案专用提示词（只挑跨集冲突链并命名，_REEL_SYSTEM_PROMPT），失败回落
# 单集锚定（_deterministic_variants）。2026-10-20 业主裁决：单集锚定当主路线不
# 合适——吸引力在跨集因果链。
_ZERO_COPY_MODES = _NO_TTS_MODES

# 会产出旁白槽位、因而读 `settings["_style_directives"]` 的模式（copywriter /
# scriptwriter 两侧都只往解说槽位里塞风格指令）。派生自注册表，绝不另立
# 第四份手抄模式清单——纯剪辑作业连口味层的答案都无人可读，不该为它付选题往返。
_NARRATION_MODES = frozenset(SUPPORTED_MODES) - _NO_TTS_MODES

# 剧本驱动的唯一模式（dialogue_narration）。2026-09-12 裁决之后**九个模式都能在
# 一条方案里跨集取画面**（Task 3c 的 casting 层给六个规则编排器补上了集身份），
# 所以这个集合不再表示"只有它能跨集"——那是一句已经作废的话，留着它就是留下一句
# 关于代码的假话。它现在只表示：时间轴不是 (mode, 取材集) 的纯函数（见 ModeSpec）。
_SCRIPT_DRIVEN_MODES = frozenset(spec.name for spec in _MODE_SPECS if spec.script_driven)


def expected_copy_source(mode: str) -> str:
    """该模式的方案文案应当来自哪里：``llm_script``（LLM 成稿）或 ``rule``（规则预算）。

    「模式 → 来源」的唯一判定接口：verify_modes 与方案卡徽章都从它取判据，不许
    另立第二份手抄模式表。
    """
    return "rule" if mode in _NO_TTS_MODES else "llm_script"


def spec_of(mode: str) -> ModeSpec:
    """查单模式注册项；未知模式 KeyError（受理校验在 api 层先行，不该走到这）。"""
    for spec in _MODE_SPECS:
        if spec.name == mode:
            return spec
    raise KeyError(f"未知模式：{mode}")
