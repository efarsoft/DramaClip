---
name: dramaclip-produce
description: 短剧成片生产链一条龙执行——把已导入素材的剧从「分析→规划→出片」无人值守跑完，并查询各阶段任务状态。当需要为 DramaClip 项目批量出片、跑完整生产链、或查询分析/规划/出片任务的进度与结果时使用。
---

# DramaClip 生产链

复用服务内网关（`/tools/produce_chain` 一条龙 + 独立阶段端点），与桌面端同一份库函数，契约零漂移。**本 skill 不改提示词不改规则**——文案质量请用 `dramaclip-narration`。

## 前置条件

- 服务已启动（网关需要服务内 Router；独立 CLI 会如实回 501 不假绿）
- 项目已建且素材已导入（`project_id` 在手）

## 一条龙执行

```text
工具：/tools/produce_chain
入参：project_id（必填）、modes（非空数组，如 ["raw_clip"] 免文案 / ["full_narration"] 需文案 LLM）、k（每模式条数，默认 1）
返回：analysis_job_id / plan_job_id（各阶段任务，按 job_id 查进度）
```

- 分析阶段幂等：已分析过的集自动跳过，不重转写
- 模式选择：未配文案 LLM 时用 `["raw_clip"]`（纯原片）或 `["subtitle_flow"]`（金句流）——两个免文案模式
- 配了文案 LLM：可选全部九种模式，K=3 起步（候选互异 + 评分排序）

## 任务状态查询

| 端点 | 入参 | 用途 |
|---|---|---|
| `jobs.get` / `jobs.list` | job_id / project_id | 单任务进度与终态 |
| `analysis.status` | job_id | 分析任务阶段明细 |
| `narration.list_plans` | project_id (+batch_id) | 产出方案列表 |
| `export.list` | project_id | 出片记录与自检成绩单 |

任务终态：completed / failed / cancelled。失败行 error 字段是原文原因，处置见对应页面。

## 出片

规划产出方案后按 plan_id 提交导出：

```text
工具：export.submit
入参：plan_ids（数组）
返回：exports[]（export_id + job_id）——出片完成后作品进「作品库」
```

## 失败处置

- 失败原因看 job.error 原文，不要凭错误类型猜
- 下载类失败（「连接被拒」）：代理/VPN 方向排查后重试，断点会续
- 规划批失败：按当前选择整批重跑（桌面端与网关同链路）
- 反复失败带同一 reason：停手检查环境，不要盲目重投
