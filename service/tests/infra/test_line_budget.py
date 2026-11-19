"""行帽棘轮（W13·门禁缺口收口）：函数 120 行 / 文件 800 行，AST 全量扫描。

背景：行帽超限此前只靠人眼 AST 扫描才发现（2026-11-18 质量审查实锤四处，
其中 write_flow_script 已到 244 行=帽的 2 倍）。本守卫把扫描变成 CI 棘轮：

- **台账是上界不是目标**：每个键的现测值 ≤ 台账值才绿——只许降不许升；
- 台账外的**新增超帽直接红**（写新代码时就控制，而不是留给下一轮审查）；
- 台账键失配（函数改名/删除）也红——逼着顺手清账，不许带着死键漂。

扫 service 生产包（dramaclip/），测试与脚本不扫；口径：函数 = def 行到
end_lineno（含签名与 docstring），文件 = 总行数。"""

from __future__ import annotations

import ast
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[2]
PACKAGE = SERVICE / "dramaclip"

# 棘轮台账：现值锁死只降不升。清一笔账就把对应键删掉；新增超帽必须先记账
# 并写明欠账理由——「先合再还」可以，「不记账」不行。
_FILE_RATCHET: dict[str, int] = {
    "dramaclip/api/models.py": 813,
    "dramaclip/api/narration_plans.py": 1002,
    "dramaclip/engines/exporter/encoder.py": 1240,
    "dramaclip/engines/narration/audit.py": 841,  # +34：包外集号告警规则（W14-A）
    # +3：stderr None 防御（2026-11-18 装测实锤）；+4：xpu 轮镜像 fallback（008eecf）
    # +4：uv 报错带 exit code+stdout 兜底；+16：失败全量输出落盘 uv-last-error.log
    # （Arc 装测二连实锤：exit 1 双流全空，尾部进报错+全量落盘双保险）
    "dramaclip/infra/model_manager/tts_runtime.py": 957,
}

_FUNC_RATCHET: dict[str, int] = {
    "dramaclip/api/analysis_job.py::_analyze_one": 204,
    "dramaclip/api/export_render.py::render_export": 297,
    "dramaclip/api/narration_plans.py::_run_plan_variants": 200,
    "dramaclip/api/narration_plans.py::_plan_one": 136,
    "dramaclip/engines/exporter/encoder.py::cut_segment_args": 209,
    "dramaclip/engines/exporter/encoder.py::_export_plan_once": 426,
    "dramaclip/engines/narration/flow_writer.py::write_flow_script": 148,
    "dramaclip/engines/narration/layout.py::_layout_cross": 190,
    "dramaclip/engines/narration/layout.py::_patch_timeline": 148,
    "dramaclip/engines/narration/modes_w5.py::build_cross": 134,
    "dramaclip/engines/narration/modes_w5.py::build_ultra_short": 138,
    "dramaclip/engines/narration/pipeline.py::build_from_script_episodes": 140,
    "dramaclip/engines/narration/pipeline.py::synthesize_narration_texts": 203,
    "dramaclip/engines/narration/scriptwriter.py::write_script_episodes": 142,
    "dramaclip/engines/tts/engines/edge.py::synthesize": 130,
    "dramaclip/infra/device_profile.py::profile": 264,
    "dramaclip/infra/model_manager/builtin_specs.py::builtin_specs": 384,
    "dramaclip/infra/model_manager/tts_runtime.py::install": 162,
    "dramaclip/service_app.py::run": 133,
}


def _scan() -> tuple[dict[str, int], dict[str, int]]:
    """全量 AST 扫描：返回 (文件行数, 函数行数)，键同台账。"""
    files: dict[str, int] = {}
    funcs: dict[str, int] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(SERVICE).as_posix()
        source = path.read_text(encoding="utf-8")
        files[rel] = len(source.splitlines())
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno + 1
                if length > 120:
                    key = f"{rel}::{node.name}"
                    funcs[key] = max(funcs.get(key, 0), length)
    return files, funcs


def test_files_within_ratchet() -> None:
    files, _ = _scan()
    over = {k: v for k, v in files.items() if v > 800}
    for key, value in over.items():
        budget = _FILE_RATCHET.get(key)
        if budget is None:
            raise AssertionError(
                f"新文件超行帽且未记账：{key} = {value} 行（帽 800）——"
                "拆分或在 _FILE_RATCHET 记账并写明欠账理由"
            )
        assert value <= budget, f"{key} = {value} 行，超出棘轮台账 {budget}（只许降不许升）"
    stale = set(_FILE_RATCHET) - set(over)
    assert not stale, f"台账键已还清账（请删掉死键）：{stale}"


def test_functions_within_ratchet() -> None:
    _, funcs = _scan()
    for key, value in funcs.items():
        budget = _FUNC_RATCHET.get(key)
        if budget is None:
            raise AssertionError(
                f"新函数超行帽且未记账：{key} = {value} 行（帽 120）——"
                "拆分或在 _FUNC_RATCHET 记账并写明欠账理由"
            )
        assert value <= budget, f"{key} = {value} 行，超出棘轮台账 {budget}（只许降不许升）"
    stale = set(_FUNC_RATCHET) - set(funcs)
    assert not stale, f"台账键已还清账（请删掉死键）：{stale}"
