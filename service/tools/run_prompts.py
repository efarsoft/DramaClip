"""真跑系统内提示词：组装真实 system+user → 调模型出稿 → 审计 → 给优化建议。

为什么这么设计：
- 组装提示词用生产代码的 build_*_request（与生成函数同源），不是另写一份——
  你在这看到的就是系统真正发给模型的东西。
- 无 LLM 凭证时（本沙箱默认）用 --mock 跑一条「合规示例稿」把闭环走通，
  并明确标注 MOCK；要拿真实模型出稿，给 llm.base_url/api_key/model 即可。

子命令：
  fixture                                 写 episodes.json（剧本样例）+ slots.json（文案样例）
  run --mode script --transcript E.json [--settings S.json|--mock] [--project 剧名] [--angle 角度]
  run --mode copy   --slots S.json       [--settings S.json|--mock] [--project 剧名] [--mode-label 标签]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dramaclip.engines.narration import scriptwriter as SW
from dramaclip.engines.narration import copywriter as CW
from dramaclip.engines.narration import audit as A
from dramaclip.engines.semantic.llm_client import LlmClient, from_settings, LlmUnavailable


# ---------------------------------------------------------------------------
# 样例
# ---------------------------------------------------------------------------

def _episodes_fixture() -> list[dict]:
    return [
        {
            "number": 1, "duration": 38.0,
            "segments": [
                {"start": 0.0, "end": 12.5, "speaker": "角色A", "text": "苏明月，你这般贱婢也配进我苏府大门？"},
                {"start": 12.5, "end": 24.0, "speaker": "角色B", "text": "姐姐莫怕，这婚书是我替你藏下的。"},
                {"start": 24.0, "end": 38.0, "speaker": "角色A", "text": "八千两银子，够买你半条命了。"},
            ],
        },
        {
            "number": 2, "duration": 30.0,
            "segments": [
                {"start": 0.0, "end": 15.0, "speaker": "角色C", "text": "摄政王到，众人跪迎。"},
                {"start": 15.0, "end": 30.0, "speaker": "角色B", "text": "原来那夜救我的，竟是当朝九千岁。"},
            ],
        },
    ]


def _slots_fixture() -> list[dict]:
    return [
        {"id": "s1", "task": "开场抛反差", "start": 0.0, "end": 12.5, "lines": "苏明月被羞辱"},
        {"id": "s2", "task": "点银两冲突", "start": 24.0, "end": 38.0, "lines": "八千两买半条命"},
        {"id": "s3", "task": "收尾勾全集", "start": 15.0, "end": 30.0, "lines": "九千岁身份揭晓"},
    ]


# ---------------------------------------------------------------------------
# Mock 模型（明确标注，仅用于无凭证时走通闭环）
# ---------------------------------------------------------------------------

def _mock_script(project: str) -> dict:
    return {
        "hook": f"被当众骂作贱婢的苏明月，竟藏着能掀翻整座苏府的婚书。",
        "segments": [
            {"episode": 1, "start": 0.0, "end": 12.5,
             "text": "苏明月被嫡姐当众斥作贱婢，可没人知道，那纸婚书早被妹妹悄悄藏了起来。"},
            {"episode": 1, "start": 24.0, "end": 38.0,
             "text": "八千两银子，买的不止是命，是苏府上下对她的轻贱。"},
            {"episode": 2, "start": 15.0, "end": 30.0,
             "text": "那夜伸手救她的，竟是当朝九千岁。"},
        ],
        "cta": f"她到底能不能翻盘？点击左下角，免费看全集《{project}》。",
    }


def _mock_copy(slots: list[dict]) -> list[dict]:
    text = {
        "s1": "苏明月被当众羞辱，妹妹却把婚书藏得死死的。",
        "s2": "八千两银子，买她半条命。",
        "s3": "那夜救她的，竟是当朝九千岁。",
    }
    return [{"id": s["id"], "text": text.get(s["id"], "（未覆盖）")} for s in slots]


# ---------------------------------------------------------------------------
# 真实提示词组装 + 调用
# ---------------------------------------------------------------------------

def _load_settings(args) -> dict:
    if args.settings:
        return json.loads(Path(args.settings).read_text(encoding="utf-8"))
    env = {
        "llm.base_url": os.environ.get("LLM_BASE_URL", ""),
        "llm.api_key": os.environ.get("LLM_API_KEY", ""),
        "llm.model": os.environ.get("LLM_MODEL", ""),
    }
    if any(env.values()):
        return env
    return {}


def _client_or_none(settings: dict) -> LlmClient | None:
    cfg = from_settings(settings)._config
    if cfg.configured:
        return from_settings(settings)
    return None


def cmd_fixture(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "episodes.json").write_text(json.dumps(_episodes_fixture(), ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "slots.json").write_text(json.dumps(_slots_fixture(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"样例已写入 {out}/：episodes.json slots.json")
    return 0


def cmd_run(args) -> int:
    settings = _load_settings(args)
    client = _client_or_none(settings)
    mode = args.mode
    project = args.project or "苏府风云"
    angle = args.angle or "切入角度：嫡女替嫁的生死局，钩子立在『婚书』上。"

    if mode == "script":
        episodes = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
        system, user = SW.build_script_request(
            episodes, project_name=project, angle_block=angle, style_directives=args.style or ""
        )
        if client is None:
            if not args.mock:
                print("⚠️ 未检测到 LLM 凭证（llm.base_url/api_key/model 均无）。\n"
                      "  真实出稿请提供 --settings 或环境变量 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL；\n"
                      "  本次用 --mock 跑一条合规示例稿走通闭环（结果标注 MOCK）。")
                return 2
            output = _mock_script(project)
            src = "MOCK"
        else:
            output = client.chat_json(system, user, temperature=0.75)
            src = "REAL"
        report = A.review_script(output, _flat_transcript(episodes))
    else:
        slots = json.loads(Path(args.slots).read_text(encoding="utf-8"))
        system = CW.system_prompt(settings, mode=args.mode_label or "")
        user = _copy_user_local(slots, project, args.mode_label or "", angle)
        if client is None:
            if not args.mock:
                print("⚠️ 未检测到 LLM 凭证。提供 --settings 或 LLM_* 环境变量；或加 --mock 走通闭环。")
                return 2
            output = _mock_copy(slots)
            src = "MOCK"
        else:
            output = client.chat_json(system, user, temperature=0.75)
            src = "REAL"
        report = A.review_copy(output, slots, mode=args.mode_label or "")

    print("=" * 70)
    print(f"真实组装的 SYSTEM 提示词（来自 build_*_request，与生成函数同源）")
    print("=" * 70)
    print(system)
    print("\n" + "=" * 70)
    print(f"真实组装的 USER 提示词")
    print("=" * 70)
    print(user)
    print("\n" + "=" * 70)
    print(f"模型出稿（来源={src}）")
    print("=" * 70)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    print("\n" + A.format_report(report))
    print(report.summary_line())
    if args.out:
        Path(args.out).write_text(json.dumps(
            {"source": src, "system": system, "user": user,
             "output": output, "report": report.summary_line()},
            ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\n已落盘 {args.out}")
    return 1 if report.hard_fails else 0


def _flat_transcript(episodes: list[dict]) -> list[dict]:
    out = []
    for ep in episodes:
        for seg in ep.get("segments", []):
            out.append({"episode": int(ep["number"]), **seg})
    return out


def _copy_user_local(slots: list[dict], project: str, mode_label: str, angle: str) -> str:
    """与 copywriter._slot_block 同构的本地镜像（无 casting 依赖，便于无素材演示）。

    注意：system 提示词是 100% 真实的生产代码；此处仅槽位块的装配做了本地镜像。
    """
    lines = [f"项目：{project}", f"模式：{mode_label}", angle, "文案槽位："]
    for s in slots:
        lines.append(f"[{s['id']}] 要做的事：{s.get('task','')}")
        lines.append(f"  画面区间：{s.get('start')}-{s.get('end')}s")
        inside = s.get("lines")
        if inside:
            lines.append("  区间内台词：")
            lines.append(f"    {inside}")
        else:
            lines.append("    （该区间无台词：只按职责写，不得编造）")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="真跑系统内提示词并审计")
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fixture")
    pf.add_argument("--out", default="review_fixtures")
    pf.set_defaults(func=cmd_fixture)

    pr = sub.add_parser("run", help="跑提示词出稿并审计")
    pr.add_argument("--mode", choices=["script", "copy"], required=True)
    pr.add_argument("--transcript", help="episodes.json（script 模式）")
    pr.add_argument("--slots", help="slots.json（copy 模式）")
    pr.add_argument("--settings", help="含 llm.base_url/api_key/model 的 JSON")
    pr.add_argument("--mock", action="store_true", help="无凭证时跑合规示例稿")
    pr.add_argument("--project", default="苏府风云")
    pr.add_argument("--angle", default="")
    pr.add_argument("--style", default="")
    pr.add_argument("--mode-label", default="")
    pr.add_argument("--out", default="")
    pr.set_defaults(func=cmd_run)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
