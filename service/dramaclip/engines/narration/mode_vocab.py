"""模式词汇表：九模式的唯一清单家与派生集合。

为什么住在 engines：模式是领域词汇，不是 RPC 词汇——选题/裁决/审计/规划执行
（flows）都要按它分流，api 只有受理校验需要读它。改模式名只动这里；消费方
（api/narration 的受理校验、export_audit、前端契约对表）各自单向引入。
"""

from __future__ import annotations

SUPPORTED_MODES = (
    "raw_clip",
    # 高光混剪（highlight_cut）2026-10-27 业主裁决并入纯原片剪辑（raw_clip 单入口，
    # 5 秒均切取消），2026-11-12 完全清除：生成/渲染/消费分支全删，存量方案行由
    # migrations/027 删除，历史推荐缓存由 mode_recommend 读时净化。

    "intro_narration",
    "cross_narration",
    "ultra_short_hook",
    "dialogue_narration",
    "full_narration",
    "subtitle_flow",
    "dual_host_chat",
    "inner_monologue",
)

# 与 TTS 合成并行的两组：剧情解说已由 LLM 剧本驱动，每段都要配音，不再属"无 TTS"。
_NO_TTS_MODES = frozenset({"raw_clip", "subtitle_flow"})
# 零文案模式（=_NO_TTS_MODES）：没有旁白槽位，母题/钩子/句式约束无处落地——
# 选题换零文案专用提示词（只挑跨集冲突链并命名，_REEL_SYSTEM_PROMPT），失败回落
# 单集锚定（_deterministic_variants）。2026-10-20 业主裁决：单集锚定当主路线不
# 合适——吸引力在跨集因果链。
_ZERO_COPY_MODES = _NO_TTS_MODES

# 会产出旁白槽位、因而读 `settings["_style_directives"]` 的模式（copywriter /
# scriptwriter 两侧都只往解说槽位里塞风格指令）。派生自上面两个集合，绝不另立
# 第四份手抄模式清单——纯剪辑作业连口味层的答案都无人可读，不该为它付选题往返。
_NARRATION_MODES = frozenset(SUPPORTED_MODES) - _NO_TTS_MODES

# 剧本驱动的唯一模式。2026-09-12 裁决之后**九个模式都能在一条方案里跨集取画面**
# （Task 3c 的 casting 层给六个规则编排器补上了集身份），所以这个集合不再表示
# "只有它能跨集"——那是一句已经作废的话，留着它就是留下一句关于代码的假话。
# 它现在只表示一件事：**这条方案的时间轴不是 (mode, 取材集) 的纯函数**，
# 因为剧本由模型按角度现写（script_driver.script_dialogue_plan）。于是成稿**前**那道
# 重叠闸门（_reject_same_episode_sibling）对它无效，只能靠成稿**后**的 _worst_overlap 兜。
_SCRIPT_DRIVEN_MODES = frozenset({"dialogue_narration"})


def expected_copy_source(mode: str) -> str:
    """该模式的方案文案应当来自哪里：``llm_script``（LLM 成稿）或 ``rule``（规则预算）。

    「模式 → 来源」的唯一判定接口：verify_modes 与方案卡徽章都从它取判据，不许
    另立第二份手抄模式表（2026-10-16 规格 §1.1；手抄表漏条目的漂移实证——那次
    漏的是高光混剪，该模式已于 2026-11-12 完全移除，教训照旧成立）。
    """
    return "rule" if mode in _NO_TTS_MODES else "llm_script"
