"""复述测试（closed-book retell）：文案可懂度的黑盒质检。

方法（外部方法论校准）：把纯文本解说稿交给一个不带任何上下文的 LLM，
让它模拟「普通观众只听一遍、不能回看」，做两件事——闭卷复述主线（谁、
想干什么、结局），标注感受流（哪里跟不上、人物记混、信息太密）。复述
不出来的地方就是稿子没讲明白的地方，这是「听懂了没」的直接度量。

定位：软质检。结论写 trace 供审计与观测，不阻塞出片；不达标的重写循环
（优先删和拆，不是补）是后续批次。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from dramaclip.engines.semantic.llm_client import LlmClient

# 感受流卡点 ≥ 此数判 fail：单点卡顿可能是观众个体差异，密集卡点说明稿子没写明白
_FAIL_CONFUSIONS = 4


@dataclass
class RetellReport:
    """复述测试结论：复述全文 + 感受流卡点 + 代码判定的 verdict。"""

    retell: str
    confusions: list[dict[str, str]] = field(default_factory=list)
    has_goal: bool = False
    has_ending: bool = False
    passed: bool = False
    reasons: list[str] = field(default_factory=list)

    def summary_line(self) -> str:
        if self.passed:
            return f"复述测试通过（卡点 {len(self.confusions)} 处）"
        return (
            f"复述测试未通过（{'；'.join(self.reasons)}"
            f"；卡点 {len(self.confusions)} 处）"
        )

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


_SYSTEM_PROMPT = """你是一位从没看过这部短剧的普通观众。下面给你一段「解说视频的文字稿」。
规则：只能按顺序读一遍（模拟只听一遍语音、不能回看、不能暂停），读完后凭记忆作答，不许翻回去核对。

读完后只输出 JSON（不要多余文字）：
{
  "retell": "用自己的话复述主线：主角是谁、想要什么、遇到什么、结局如何。没记住就写『没记住』",
  "confusions": [
    {
      "quote": "让你卡住的原句片段（必须能从原文找到）",
      "issue": "unclear|persona_mix|dense|boring|jump",
      "note": "一句话说明为什么卡"
    }
  ],
  "has_goal": true 或 false（听完是否清楚主角想要什么）,
  "has_ending": true 或 false（听完是否清楚故事结局）
}
issue 含义：unclear=没讲明白；persona_mix=人物记混或指代不清；dense=信息太密；
boring=流水账走神；jump=跳接突兀。
confusions 只记真实的卡点，没有就给空数组；不要为了凑数编造卡点。"""


def retell_check(text: str, client: LlmClient) -> RetellReport:
    """纯文本稿 → 无上下文复述测试。LLM 输出畸形按降级处理（软质检不硬断）。"""
    answer = client.chat_json(_SYSTEM_PROMPT, text, temperature=0.2)
    if not isinstance(answer, dict):
        raise ValueError("复述测试输出不是 JSON 对象")
    retell = str(answer.get("retell") or "").strip()
    raw_confusions = answer.get("confusions")
    confusions = [
        {
            "quote": str(item.get("quote") or "")[:120],
            "issue": str(item.get("issue") or "unclear"),
            "note": str(item.get("note") or "")[:120],
        }
        for item in (raw_confusions or [])
        if isinstance(item, dict)
    ]
    has_goal = bool(answer.get("has_goal"))
    has_ending = bool(answer.get("has_ending"))

    reasons: list[str] = []
    if not has_goal:
        reasons.append("主角目标不明")
    if not has_ending:
        reasons.append("结局不明")
    if len(confusions) >= _FAIL_CONFUSIONS:
        reasons.append(f"卡点达 {len(confusions)} 处")
    return RetellReport(
        retell=retell,
        confusions=confusions,
        has_goal=has_goal,
        has_ending=has_ending,
        passed=not reasons,
        reasons=reasons,
    )
