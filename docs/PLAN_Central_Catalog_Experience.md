# DramaClip — 中央模型目录体验闭环计划（用户指令“你帮我规划和实施”）

**目标（质量第一 + 傻瓜化极致）**  
让用户“安装完成就能用”高质量本地引擎（Fun-CosyVoice3、Kokoro、SenseVoice、pyannote 3.1 等），体验与参考项目 OmniVoice-Studio 对齐。

**核心理念（严格遵守）**
- 中央真相来源：`app/config/models.yaml`（已符合参考项目结构）
- 统一下载：`huggingface_hub.snapshot_download` + `app/services/model_manager.download_hf_model`
- 每引擎声明式依赖：`required_model_repo`
- 诚实 `is_available()` + 安装提示
- **不硬锁任何单一模型为默认**（质量由实际输出决定）
- pyannote 作为可选高精度路径完全暴露（catalog + IPC + UI 开关）

---

## 当前状态审计结论（2026-04 最新）

**已完成（良好对齐参考项目）**
- models.yaml 结构 + 质量中性描述
- TTSBackend ABC + _LazyRegistry + required_model_repo（cosyvoice/kokoro 已声明）
- registry.list_backends() 自动聚合 required_models + installed 状态
- speaker_diarization_service 完整 pyannote 路径（_load_pyannote_model、_diarize_with_pyannote、真实声学特征 SpeakerProfile）
- analyze_handler 已支持 options.use_pyannote_diarization + 配置回退
- hf_progress.py（listener + emit + 尝试 monkey-patch）
- model_manager 已实现 load_model_catalog / download_hf_model / list_central_catalog_models

**关键阻塞 / 待闭环（本次规划重点）**
1. **下载路径分裂**：`model.download` RPC 仍走旧的 `download_model(model_id)` 分发逻辑，未完全打通到 `download_hf_model(repo_id)` + 结构化 hf_progress。
2. **前端缺少“中央模型管理”统一视图**：用户看不到全 catalog（TTS/ASR/Diarization 一起）、无法一键下载所有条目、进度可视化弱。
3. **pyannote 开关未暴露**：后端能力已就绪，前端/用户无感知。
4. **命名污染残留**：tts/backends/ 目录下仍有 cosyvoice3*.pyc；前端 TTSTab 引擎选项仍含旧名。
5. **pyannote 结果反哺分析链路** 验证不足。

---

## 分阶段实施计划（推荐顺序）

### Phase 1: 基础对齐与快速胜利（1-2 天工作量）
- 清理 tts/backends 下所有 cosyvoice3* 残留文件（源 + pyc）
- 统一 TTSTab 引擎选项：只保留 `cosyvoice`（标准命名），移除 `cosyvoice2_local` 等旧入口
- 增强 `model_download`（system_handler.py）：
  - 如果 model_id 是 central catalog 中的 repo_id → 直接调用 `download_hf_model(repo_id=...)`
  - 否则回退旧逻辑（保持兼容）
- 让 `list_central_catalog_models` 返回的每个条目都带 `downloadable: true` + 精确 `check_*` 状态（按 role 分派）
- **验收**：`system:ttsBackendsList` 返回的 required_models 状态准确；调用 `model.download` + repo_id 能触发统一 HF 下载 + 进度通知

### Phase 2: 中央模型管理 UI（最高用户价值，2-3 天）
新建或重度重构 `src/components/settings/CentralModelsTab.tsx`（或 ModelsTab）

功能：
- 从 `modelApi.list()` 获取 `central_catalog`
- 按 role 分组展示（TTS 区 / ASR 区 / Diarization 区）
- 每行显示：label、repo_id、size_gb、quality_notes / note、已安装 ✓（绿）/ 待下载（黄）
- 一键“下载”按钮（调用 modelApi.download(repo_id)）
- 实时进度条（结合 modelDownloads 状态 + ipcClient.onProgress 结构化事件）
- pyannote 行特殊处理：显示“需要 HF Token（gated model）”警告 + 链接到 https://huggingface.co/pyannote/speaker-diarization-3.1
- 支持取消 + 删除
- 搜索 / 过滤

同时在 SettingsPage “模型” Tab 下默认展示这个新组件（或独立 Tab）。

**验收标准**：
- 用户能从 UI 看到 Fun-CosyVoice3、pyannote/speaker-diarization-3.1 等全部条目
- 点击下载后有结构化进度（百分比 + 阶段 + 文件名）
- 下载完成后状态立即变为“已安装”，TTS/ASR 可用性随之更新

### Phase 3: pyannote 开关完整暴露（1 天）
- 在 Analysis Settings / 项目分析选项中增加清晰开关：
  - “说话人分离引擎”：聚类（默认，轻量） / pyannote 3.1（高精度，需模型 + HF Token）
- 开关变化 → 写入 unified_config + 透传到 analyze_start 的 options
- UI 增加风险提示（gated + 内存占用）
- **验收**：前端开关能真正让 analyze 任务走 `_diarize_with_pyannote` 路径，并返回完整 SpeakerProfile + speaker_timeline

### Phase 4: pyannote 结果反哺下游分析（可选但推荐，质量优先）
- 在 highlight / emotion / rhythm scorer 中消费 diarization_result.speakers / segments
- 实现简单 speaker-aware 特性（例如“主要角色情绪权重更高”“对话节奏加分”）
- 或至少保证 speaker_timeline 进入 NarrationPipeline 上下文

### Phase 5: 端到端验证 + 文档
- py_compile 所有修改文件
- 手动黄金流程：
  1. Settings → 中央模型 → 下载 Kokoro（小）+ Fun-CosyVoice3（可选）
  2. 下载 pyannote（若有 HF Token）
  3. 新建短剧项目 → 分析时勾选 pyannote
  4. 切换 TTS engine 到 cosyvoice → 生成旁白 → 成片
- 更新 README / docs/UnifiedConfig_Guide.md 说明“如何让高质量本地引擎可用”
- 清理 model_manager.py 中过时注释和旧常量

---

## 风险与缓解

- **pyannote 是 gated model**：必须在 UI 明确提示用户先去 HF 同意协议 + 填 HF_TOKEN（环境变量或配置项）。后端已有优雅降级。
- **大模型下载时间长**（CosyVoice 2GB+）：必须有取消 + 断点续传（snapshot_download 已支持）。
- **Windows 符号链接问题**：download_hf_model 已传 `local_dir_use_symlinks=False`。
- **依赖地狱（cosyvoice 官方包）**：is_available() 诚实返回“需 git clone + pip -r requirements”，不假装“一键 pip 就能用”。长期可考虑 SubprocessBackend（参考项目方案）。
- **ModelScope 国内加速**：保留作为 SenseVoice / Whisper 的可选 fallback（已在 model_manager 中有迹象）。

---

## 立即可开始的第一个可执行任务（推荐）

**P1.1** 清理命名污染 + 让 `model_download` 智能路由到 `download_hf_model`（对中央 catalog 条目）。

这个改动最小、风险最低，却能立刻让后端“中央目录”真正可操作。

之后直接进入 Phase 2 UI 构建（用户能立刻看到效果）。

---

**本计划严格遵循用户历史指令**：
- 成品质量第一、不锁定 CosyVoice 为默认
- 严格 1:1 参考 OmniVoice-Studio 的 catalog + required_model_repo + honest is_available 理念
- 所有模型走标准 huggingface_hub.snapshot_download

准备好后直接回复“开始执行 Phase X” 或 “优先做 Phase 2 UI” 或提出调整意见。
