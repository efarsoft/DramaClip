---
name: dramaclip-narration
description: 短剧解说成片的文案写作、候选标题与发布物料、质量审查方法论及配套工具。当需要为 DramaClip 方案写或改解说文案/钩子/CTA、生成候选标题与发布文案标签、审查文案（AI 味/剧透/编造/格式），或理解本项目的文案规则与研究实证时使用。
---

# DramaClip 解说文案

短剧推广解说（导看全集形态）的文案方法论 + 可执行工具。**规则文本的单一真相源是引擎常量**：
`service/dramaclip/engines/narration/` 下的 `scriptwriter.py` / `titles.py` / `llm_prompts.py`。
`references/prompt-cards.md` 由 `service/tools/export_skill.py` 自动导出（文件头有生成标记），勿手改；
改动规则一律改源常量后重跑导出，漂移会被 `service/tests/tools/test_export_skill.py` 拦下。

## 任务路由

| 任务 | 路径 |
|------|------|
| 理解文案规则/文风/题材侧重 | 读 `references/prompt-cards.md`（规则快照） |
| 看研究实证（句式库/开场/揭晓词/剪辑节奏） | 读 `references/research-findings.md`（带日期） |
| 为方案真实出稿并审计 | `uv run python tools/run_prompts.py run … --from-db`（service/ 目录下） |
| 审查一份剧本/文案 | `uv run python tools/narration_review.py audit …` |
| 改提示词规则 | 改引擎常量 → 同步 audit.py 引文与测试锚点 → 重跑 export_skill → 跑门禁 |

## 出稿与审查（工具自查，不要凭记忆执行规则）

审计器（`dramaclip/engines/narration/audit.py`）是文案质量的兜底网：空钩/编造锚点/跨集因果/
行长超限等都有硬软检查。任何文案改动都应过一遍审查，人只复核 soft 项。

```bash
cd service
# 真实出稿（剧本链）——settings 直接读本机数据库，无需手填密钥
uv run python tools/run_prompts.py run --mode script \
  --transcript review_fixtures/episodes.json --from-db --project 剧名 --out out.json

# 真实出稿（逐槽填词链）
uv run python tools/run_prompts.py run --mode copy --slots review_fixtures/slots.json \
  --from-db --mode-label 片头解说 --out out.json

# 审查
uv run python tools/narration_review.py audit --script out.json --transcript review_fixtures/transcript.json
```

## 纪律（本项目踩过的坑）

1. **改提示词必同步三处**：audit.py 的 prompt_quote/正则、钉规则文本的测试锚点、本 skill 的导出文档。
   漏任何一处就是规则漂移——审查器会拿旧规则打回合格稿，文档会教旧规则。
2. **反幻觉高于文风**：转写里没有的情节/数字/人名/地名一律不写；宁可少说不许编圆。
3. **揭晓词已放开**（业主裁决 2026-10-13）：竟/却/原来/没想到是平台标配，禁的是
   「他竟然」式无具体事实的空钩，不是词汇。
4. **剧透精化定义**：反转的「发生」可前置（预告式开场正是设计）；谜底与人物结局扣在全集里。
5. 产出物（提交/文档/注释）不出现外部项目来源。
