"""提示词 → 生成内容 审查 / 复核 CLI。

子命令：
  fixture              生成样例（transcript.json + bad_script.json + slots.json + bad_lines.json）
  audit --script S.json --transcript T.json [--log L.jsonl]
                      审查剧本链路输出
  audit --copy L.json --slots S.json [--mode m] [--log L.jsonl]
                      审查逐槽文案输出
  suggest --log L.jsonl
                      从累积审查记录提 prompt 加固建议（持续优化）

审查规则锚定回 prompt 原文，见 dramaclip/engines/narration/audit.py。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dramaclip.engines.narration import audit as A


def _load(p: str) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _append_log(path: str, records: list[dict]) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _sample_fixture() -> dict:
    """古装/方言错位命名样本，制造可审查的真实场景。"""
    transcript = [
        {"episode": 1, "start": 0.0, "end": 12.5, "speaker": "[角色A]", "text": "[角色A]：苏明月，你这般贱婢也配进我苏府大门？"},
        {"episode": 1, "start": 12.5, "end": 24.0, "speaker": "[角色B]", "text": "[角色B]：姐姐莫怕，这婚书是我替你藏下的。"},
        {"episode": 1, "start": 24.0, "end": 38.0, "speaker": "[角色A]", "text": "[角色A]：八千两银子，够买你半条命了。"},
        {"episode": 2, "start": 0.0, "end": 15.0, "speaker": "[角色C]", "text": "[角色C]：摄政王到，众人跪迎。"},
        {"episode": 2, "start": 15.0, "end": 30.0, "speaker": "[角色B]", "text": "[角色B]：原来那夜救我的，竟是当朝九千岁。"},
    ]
    # 故意带缺陷的剧本：缺 episode、超界、空泛 hook、cta 空喊点赞、未换名、元叙述
    bad_script = {
        "hook": "他竟然藏着惊天秘密，后续更精彩！",
        "segments": [
            {"episode": 1, "start": 0.0, "end": 12.5, "text": "在这镜头里，苏明月被[角色A]当众羞辱。"},
            {"start": 13.0, "end": 60.0, "text": "八千两银子买半条命，[角色A]狠辣尽显。"},
            {"episode": 2, "start": 0.0, "end": 30.0, "text": "摄政王到场，局势陡变。"},
        ],
        "cta": "点个赞关注我，下集更精彩！",
    }
    slots = [
        {"id": "s1", "task": "开场抛反差", "start": 0.0, "end": 12.5, "lines": "[角色A]羞辱苏明月"},
        {"id": "s2", "task": "点银两冲突", "start": 24.0, "end": 38.0, "lines": "八千两买半条命"},
        {"id": "s3", "task": "收尾勾全集", "start": 15.0, "end": 30.0, "lines": "九千岁身份揭晓"},
    ]
    bad_lines = [
        {"id": "s1", "text": "苏明月被当众羞辱，这镜头看得人牙痒。"},
        {"id": "s3", "text": "那夜救她的，竟是当朝九千岁。"},
    ]
    return {"transcript": transcript, "bad_script": bad_script, "slots": slots, "bad_lines": bad_lines}


def cmd_fixture(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fx = _sample_fixture()
    (out / "transcript.json").write_text(json.dumps(fx["transcript"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "bad_script.json").write_text(json.dumps(fx["bad_script"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "slots.json").write_text(json.dumps(fx["slots"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "bad_lines.json").write_text(json.dumps(fx["bad_lines"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"样例已写入 {out}/：transcript.json bad_script.json slots.json bad_lines.json")
    return 0


def cmd_audit(args) -> int:
    if args.script:
        script = _load(args.script)
        transcript = _load(args.transcript) if args.transcript else []
        report = A.review_script(script, transcript)
    else:
        lines = _load(args.copy)
        slots = _load(args.slots) if args.slots else []
        report = A.review_copy(lines, slots, mode=args.mode or "")
    print(A.format_report(report))
    print()
    print(report.summary_line())
    if args.log:
        recs = A._flat(report.findings, sample_id=args.sample or "cli")
        _append_log(args.log, recs)
        print(f"已追加 {len(recs)} 条记录到 {args.log}")
    return 1 if report.hard_fails else 0


def cmd_suggest(args) -> int:
    if not Path(args.log).exists():
        print(f"无日志 {args.log}，先跑 audit --log")
        return 2
    records = [json.loads(l) for l in Path(args.log).read_text(encoding="utf-8").splitlines() if l.strip()]
    props = A.propose_prompt_tweaks(records, min_hits=args.min_hits)
    if not props:
        print("暂无反复失守（fail>=%d）的硬规则，prompt 暂不需加固。" % args.min_hits)
        return 0
    print(f"# 持续优化建议（基于 {len(records)} 条审查记录）\n")
    for p in props:
        print(f"## {p['rule_id']}  失守 {p['fail_count']} 次")
        print(f"- 当前 prompt 原文：_{p['current_prompt']}_")
        print(f"- 建议：{p['action']}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="提示词→内容 审查/复核/持续优化")
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fixture", help="生成样例")
    pf.add_argument("--out", default="review_fixtures")
    pf.set_defaults(func=cmd_fixture)

    pa = sub.add_parser("audit", help="审查生成内容")
    pa.add_argument("--script", help="剧本 JSON")
    pa.add_argument("--transcript", help="台词转写 JSON（剧本审查用）")
    pa.add_argument("--copy", help="逐槽 lines JSON")
    pa.add_argument("--slots", help="槽位 JSON（文案审查用）")
    pa.add_argument("--mode", default="")
    pa.add_argument("--log", help="审查记录累积文件 jsonl")
    pa.add_argument("--sample", default="cli")
    pa.set_defaults(func=cmd_audit)

    ps = sub.add_parser("suggest", help="提 prompt 加固建议")
    ps.add_argument("--log", default="review_log.jsonl")
    ps.add_argument("--min-hits", type=int, default=2)
    ps.set_defaults(func=cmd_suggest)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
