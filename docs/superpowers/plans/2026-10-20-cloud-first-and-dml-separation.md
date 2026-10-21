# 云端优先档 + 人声分离 DML · 规划（0.2.3 候选）

**日期**：2026-10-20 · **状态**：规划稿，待业主确认后转实施计划 · **上位文件**：[xpu-directml-adaptation-eval §7](../specs/2026-10-20-xpu-directml-adaptation-eval.md)（更优解论证）
**目标**：把「非 NVIDIA 主机也有 AI 提速」从适配矩阵问题转化为两个小批——①云端优先档产品化（已建成的云端引擎缺的是入口与引导）；②人声分离切 DirectML（唯一当天可用的跨厂商 GPU 通道）。不照顾开发机老硬件，但开发机 RX 5500 XT 恰好可作 DML 真机回归卡。

---

## 批 A：云端优先档产品化（≈1 天，不碰 AI 栈）

### 现状事实

- 云端引擎已建成并真机验收：百炼 ASR（qwen/paraformer，字级 speaker_id）+ CosyVoice 云端音色；registry `_is_cloud` 引擎接线即视为已安装。
- 默认值本地优先：`asr.engine="faster_whisper"`、`tts.engine="edge"`；key 键 `asr.api_key` / `tts.api_key`。
- 设备真相源：`device_resolve`（厂商探测已按多厂商批升级为 CIM+nvidia-smi 两路）。

### 任务分解

- **A1 选型推荐**：引擎中心与工作台新增推荐逻辑——宿主**无 NVIDIA 独显**且 `asr.api_key` 已配 → ASR 云端引擎标「推荐」徽标；无 N 卡且未配 key → 非阻塞引导卡（开通步骤三行 + 成本预估 + 「去设置 key」直达）。有 N 卡不出推荐（本地已够好，不打扰）。
- **A2 成本预估**：引导卡内嵌静态公开定价换算（ASR ≈ 元/小时素材、TTS ≈ 元/万字），文案标注「按官方账单为准」；不接计费 API、不缓存价格。
- **A3 默认值纪律**：不改任何默认引擎——推荐是建议，花钱的决定留给用户。

### 验收门

- 无 N 卡 + 有 key：推荐徽标出现，选云端跑通一集真机分析。
- 无 N 卡 + 无 key：引导卡出现、直达设置，不出现在有卡机器上。
- 有 N 卡：零 UI 变化。

## 批 B：人声分离 DML（≈1~1.5 天，含真机对拍）

### 现状事实

- 分离走 audio-separator + ORT：NVIDIA = CPU 版 ort 包 + cuda_runtime DLL 注入 CUDA EP；`separation_worker._provider_plan` 已有 requested 语义（cpu 永不碰 GPU、显式 cuda 无 EP 直接失败）；hello 带算力回执。
- `onnxruntime` 与 `onnxruntime-directml` 是互斥包（同名 import），DML 是「装哪个包」的安装器决策。
- `tts_runtime.ort_state` 已有安装期真实 session 探测，`device_profile.separation_ort` 消费它。

### 任务分解

- **B1 安装变体三选一**：tts_runtime 按 `device_resolve` 厂商装 ort——NVIDIA/无卡=现状（CPU 包 + CUDA DLL）；AMD/Intel=onnxruntime-directml。可重入：已装包与目标变体不符时自动换装；`ort_state` 扩 `dml` 形状（安装期真实 DML session 探测）。
- **B2 worker 通道**：`_provider_plan` 扩 DML——available 含 `DmlExecutionProvider` 且 requested≠cpu → 计划走 DML；hello/回执 `actual="dml"`。**显式 cuda 而机器只有 DML → 如实失败，不拿 DML 冒充 CUDA 承诺。**
- **B3 契约与界面**：`ComputeReport.actual` 允许值扩 `"dml"`（requested 枚举不动，auto 下 DML 合法，fallback 语义不变）；`assert_success` 同步；UI `computeLabel` 认 dml（「本次实际：GPU（DirectML）」）。
- **B4 真机验证门（硬门）**：RX 5500 XT 真跑 DML——RTF 对比 CPU 必须有实质收益；分离产物 CPU vs DML 对拍（业主抽听 + 转写下游 CER 无退化）。任一不过 → DML 整条退回、如实 `unsupported`，本批只剩批 A。

### 风险

- 双包互斥：换变体=重装依赖组，安装器必须可重入、失败可回退（复用六阶段经验）。
- DML 数值漂移：B4 对拍是硬门，不交付「不崩溃但音质漂」的通道。
- 核显本收益存疑：批 A 的引导把这类用户导向云端；批 B 不对核显承诺提速，文案按实测说话。

## 依赖与顺序

A、B 相互独立，可并行或任选先后；B 被真机门约束，A 无外部依赖建议先行。

## 明确不做

XPU / torch-directml / ZLUDA / whisper 非 NVIDIA 加速 / ASR 走 ONNX（sherpa-onnx DML 未支持、funasr_onnx 有缺口）/ 0.2.2 范围内任何事。
