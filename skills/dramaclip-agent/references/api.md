# Agent 网关 API 参考

基址：`http://127.0.0.1:8340`（`--port` 可换）。除 `/health` 外全部要求
`Authorization: Bearer <AGENT_TOKEN>`。所有请求/响应均为 UTF-8 JSON。

错误码：401 鉴权失败；404 未知端点；422 业务校验失败（`error` 带人读原因）；
503 LLM 未配置或不可达（仅出稿类端点）。

## GET /health

无需 token。`{"ok": true, "service": "dramaclip-agent"}`

## POST /tools/audit_script

审查解说剧本。审计器规则：空钩、剧透、跨集因果、集号缺失、编造锚点、元叙述、
数字写法、人称切换等（hard=一票否决，soft=需人工复核）。

请求体：
```json
{
  "script": {
    "hook": "开场钩子",
    "segments": [{"episode": 1, "start": 0.0, "end": 12.5, "text": "该片段解说文案"}],
    "cta": "结尾引导语"
  },
  "transcript": [{"episode": 1, "start": 0.0, "end": 12.5, "speaker": "角色A", "text": "台词"}],
  "transcript 也可为 null（跳过编造类检查，其余照查）": null
}
```

响应：`{"target": "script", "passed": bool, "findings": [{rule_id, layer, severity,
passed, message, location, prompt_quote, needs_human}], "meta": {}}`

## POST /tools/audit_copy

审查逐槽文案。请求体：
```json
{
  "lines": [{"id": "s1", "text": "该槽位文案"}],
  "slots": [{"id": "s1", "task": "要做的事", "start": 0.0, "end": 12.5, "lines": "区间内台词"}],
  "mode": "ultra_short_hook 时行长上限放宽到 240 字，其余 60 字"
}
```

响应：同 audit_script（`target: "copy"`）。常用 rule_id：
`COPY_COVER_ALL_IDS`（槽位全覆盖）、`COPY_LINE_CAP`（行长超限，硬伤）。

## POST /tools/draft_titles

六类句式候选标题 ×8 + 发布文案 + 话题标签（一次 LLM 往返产出三样）。
需要 llm.* 配置（见 SKILL.md「配置 LLM」），否则 503。

请求体：
```json
{"narration_texts": ["解说文案第一段", "第二段"], "timeout_s": 120}
```

响应：
```json
{
  "titles": [{"text": "标题", "selected": true}, {"text": "…", "selected": false}],
  "caption": "发布文案（1~2 句钩子短句）",
  "tags": ["题材情绪标签", "高流量行为标签"]
}
```

第一 selected 标题即封面字层用的那条。
