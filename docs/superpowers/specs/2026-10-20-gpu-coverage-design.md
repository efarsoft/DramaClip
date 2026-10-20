# DramaClip 全流程 GPU 覆盖与 CPU 线路核对 · 设计规格

**日期**：2026-10-20 · **状态**：待用户审阅 · **上位文件**：`docs/superpowers/specs/2026-10-16-ui-truth-and-polish-design.md`（降级留痕「账在库」与界面口径）、`docs/05-开发路线图.md`（业主自维护，本文件不合并）
**起因**：业主原话「进行调整和优化，看看 GPU 加速有没有覆盖到 ASR、TTS、视频剪辑全流程，另外需要同步核对 CPU 线路」。
**范围裁决**：业主明确选择「全量覆盖」——统一设备处理、Kokoro GPU、AI 标注与视频修复、人声分离 GPU（允许新增依赖/模型）、真机验证全部在范围内。
**路线**：P1（零新依赖：统一回执 + ASR/TTS + AI 标注折叠 + CPU 可见性）→ P2（ORT GPU 人声分离）→ P3（老卡时间盒 spike + 验真脚本 + 文档）。顺序固定；P3 的 GPU 结论只认实测。

---

## 0. 根因、实测边界与批次

### 0.1 四条根因（每条可反证）

1. **安装态冒充运行态，本次实际算力不可见。**
   - IndexTTS / CosyVoice 的 worker 就绪行本来带 `device`，父进程读完就丢：`indextts2.py::_synth_one` 与 `cosyvoice.py::_synth_one` 只 `json.loads(proc.stdout.readline())`，不保存设备与原因。
   - Kokoro 两条路径都只构造模型、从不 `.to(device)`：`workers/kokoro_worker.py` 的 `KModel(...) → KPipeline(...)`，`engines/kokoro.py::_ensure_pipeline` 同形；`kmodel.device` 回显的 `cpu` 只证明默认值，不证明推理设备。
   - ASR 的默认值本身就是两套：`config.DEFAULTS["asr.device"] = "auto"`，但 `engines/analysis/runtime.py::_build_transcriber` 给 faster-whisper 的缺省是 `"cpu"`，`api/engines.py::_asr` 自检入口的缺省也是 `"cpu"`；`selftest.py::_build_asr` 对 SenseVoice/Paraformer 干脆不传 `device`，与构造器支持的参数矛盾。
   - 自检只看「出了字/出了声」，不看实际走了哪条线：`selftest.py::run_asr` 只拼文本判 `ok`，`run_tts` 只验时长。GPU 回退 CPU 时自检仍全绿。

2. **显式 CUDA 仍静默回退，承诺与行为不一致。**
   - `transcriber.py::FasterWhisperEngine._create` 与 `transcribe`、SenseVoice/Paraformer 的进程内路径、`workers/funasr_worker.py`，都在 CUDA 类异常时无条件改跑 CPU——包括用户显式选 `cuda` 的情况。
   - 日志里有一行 warning，但作业结果、自检结果和引擎卡都不带「已回退」；用户看到的仍是「GPU 引擎可用」。
   - 这与本项目已定的算力语义冲突：`auto` 才允许回退，显式 `cuda` 是承诺，失败必须报错。

3. **AI 标注把硬编成果整片重编，GPU 编码收益在最后一步蒸发。**
   - `engines/exporter/encoder.py::_export_plan_once` 在 loudness 之后调用 `ai_label.apply`；`ai_label.py::apply` 是独立一遍 `-c:v libx264 -preset medium -crf 18` 的整片重编，`-c:a copy` 只保住音频。
   - 即使 Phase A/B 全程 NVENC，开启 AI 标注后成片仍被 x264 重编一次；段级复用签名也完全没有标注输入，改标注文案不会触发重编（重编发生在后处理，绕过了段缓存）。

4. **人声分离从接线处就没有设备概念。**
   - `workers/separation_worker.py::separate` 只构造 `Separator(...)`，不传 device、不覆盖 `onnx_execution_provider`、不读实际 session provider。
   - `tts_runtime.py` 在 CosyVoice 依赖里硬钉 `onnxruntime==1.18.0`（CPU 轮）；本机 `tts-venv` 的 torch 也是 CPU 轮，`audio-separator` 的自动判定只会落 CPU。
   - 分离结果因此从未有机会使用 GPU，也从未向用户说明「这次到底走的什么后端」。

### 0.2 本机与框架的硬边界（先钉死，避免把 unsupported 写成 pass）

| 项 | 实测事实 | 本机结论 |
|---|---|---|
| GPU | Quadro M4000 8GB，驱动 582.78，max CUDA 13.0，算力 **sm_52** | 硬件在场，但下列框架有硬下界 |
| faster-whisper / CTranslate2 | CTranslate2 4.8.2 最低算力 **sm_61** | 本机 **GPU 不可用**，只能 CPU |
| tts-venv（IndexTTS/CosyVoice/Kokoro） | Python 3.11，torch 2.8.0+cpu；`_gpu_variant` 在 >=7.0 才装 cu128；torch 2.8 cu128 最低算力 **sm_70** | 本机 **GPU 不可用**，只能 CPU；P3 另行时间盒验证老卡 cu126 |
| service/.venv（dev funasr） | Python 3.12，torch 2.14.1+cu126，`cuda.is_available()=True` | funasr 的 GPU 路径**可实测** |
| 视频编码 | FFmpeg NVENC/QSV/VideoToolbox 黑帧真试编 | NVENC 必须真试编通过才认，不按显卡型号猜 |
| 人声分离 ONNX Runtime | 现有 `cuda_runtime` 为 cuBLAS 12.4 + cuDNN 8.9；ORT 1.18 GPU 与 cuDNN 8 匹配；新版 ORT 可能要求 cuDNN 9 | 版本与 provider 必须由真实安装 + 真实 session 探测决定，不凭记忆钉 |

**不可验证项写 `unsupported`，不计入通过。** 需要 CC >= 7.0 的机器补验 whisper/TTS GPU；本机不能给出「通过」结论。

### 0.3 批次与验收口径

| 批次 | 内容 | 验收 |
|---|---|---|
| **P1 零新依赖** | 统一 `ComputeReport` 契约与落库；ASR 默认值/门禁/实际设备；TTS hello 捕获 + Kokoro `.to(device)` + `tts.device`；AI 标注折叠进段滤镜并从签名生效；CPU 线路测试与界面可见性 | 单测/集成测试全绿；本机 CPU 全链真跑；本机可验的 GPU 路径（dev funasr、NVENC）真跑；不可验项标 `unsupported` |
| **P2 新依赖** | 人声分离 ORT GPU：worker `--device`、provider 覆盖、真实 session 探测、安装期探测、回执与 UI | 本机真实分离：CUDA provider 可用则 `pass`，不可用则 `unsupported` + 原因；CPU 路径必须 `pass` |
| **P3 收口** | 老卡 torch 2.14.1+cu126 隔离 spike（仅时间盒，不承诺）；`scripts/verify_gpu_coverage.py`；文档与真机验收 | 脚本逐项输出 `pass / fail / unsupported`；`unsupported` 不算通过；CC>=7 机器补验记入文档 |

### 0.4 口径

- **`unknown ≠ ok`**：成功路径的 `actual` 不得为 `unknown`。
- **`unsupported ≠ pass`**：硬件/框架不支持是一条诚实结论，不是绿灯。
- **回退只在 `auto` 下发生**；`fallback=true` 只表示「先试了 GPU、失败后落 CPU」，硬件不支持直接落 CPU 记 `fallback=false`。
- **行号是写作时点的方便定位，不是判据**；判据是函数名/字段名 + 文中给出的可复跑命令。
- **P1 不新增依赖**；P2 的 ORT 版本在真实探测前不写死。

---

## 1. 统一算力契约（P1）

### 1.1 `ComputeReport` 形状

新模块 `service/dramaclip/infra/compute.py`，只做三件事：设备请求归一化、报告构造与不变量校验、显式 CUDA 失败的统一异常。引擎自己不各拼一套 JSON。

```json
{
  "component": "asr.whisper",
  "requested": "auto",
  "resolved": "cpu",
  "actual": "cpu",
  "fallback": true,
  "reason": "CUDA 初始化失败：no kernel image is available …",
  "device": "cpu"
}
```

字段取值：

| 字段 | 允许值 | 含义 |
|---|---|---|
| `component` | `asr.whisper` / `asr.funasr` / `tts.indextts2` / `tts.cosyvoice` / `tts.kokoro` / `tts.edge` / `tts.cloud` / `tts.separation` / `video.encode` | 出账的部件 |
| `requested` | `auto` / `cuda` / `cpu` | 用户/设置请求 |
| `resolved` | `cuda` / `cpu` / `cloud` / `unsupported` | 运行前策略判定 |
| `actual` | `cuda` / `cpu` / `cloud` / `unknown` | 运行后证据；成功路径不得为 `unknown` |
| `fallback` | bool | 仅「试过 GPU 后失败落 CPU」为 true |
| `reason` | string | 人话原因；成功且无回退时可为空 |
| `device` | string | `cuda:0` / `cpu` / `cloud` 等实际设备串 |

**不变量**（`compute.py` 内校验，测试逐条锚定）：

1. `requested="cuda"` 且能力/运行时不满足 → 抛 `ComputeUnavailableError`，**不得**产出 `actual="cpu"` 的报告。
2. `requested="cpu"` → `actual="cpu"`，且不得触发 CUDA 初始化/探测。
3. `fallback=true` → `resolved` 必须是曾尝试的 `cuda` 且 `actual="cpu"`，`reason` 非空。
4. 硬件/框架不支持（如 CT2 在 sm_52、torch cu128 在 sm_70 以下）→ `resolved="cpu"`、`fallback=false`、`reason` 说明是硬边界。
5. 云端引擎 → `actual="cloud"`，不冒充本机 GPU/CPU。

### 1.2 `auto / cuda / cpu` 语义

| requested | 能力 | 运行时 | 行为 | 报告 |
|---|---|---|---|---|
| `auto` | 支持 | 支持 | 用 GPU | `resolved=cuda, actual=cuda, fallback=false` |
| `auto` | 支持 | 失败 | 回退 CPU 一次 | `resolved=cuda, actual=cpu, fallback=true, reason=原文` |
| `auto` | 不支持 | — | 直接 CPU，不空试 | `resolved=cpu, actual=cpu, fallback=false, reason=硬边界` |
| `cuda` | 不支持 | — | **报错** | 抛 `ComputeUnavailableError` |
| `cuda` | 支持 | 失败 | **报错**，不回退 | 抛 `ComputeUnavailableError`（带原文） |
| `cpu` | — | — | 只走 CPU，不探 CUDA | `resolved=cpu, actual=cpu` |

**能力探测必须是真探测**：torch 用最小 CUDA 运算；CT2 用实际构造；ORT 用实际 session；视频用黑帧真试编。`device_profile` 的 `ready` 只表示硬件+安装态，不能当任务实际 GPU 证据。

### 1.3 落库、协议与单一写方

- **迁移**：新增 `service/dramaclip/infra/storage/migrations/024_compute_receipts.sql`，给 `jobs` 与 `export_jobs` 各加 `compute TEXT`（JSON 数组）。`023` 已被 2026-10-16 UI 真相规格预留（`export_degraded`），本批不用；若并行批次先占 023，本批顺延并在 `service/tests/infra/storage/test_db.py` 的有序全等清单同步。
- **单一写方**：
  - `infra/jobs.py` 增加 `set_compute(job_id, reports)` 与读取列；`get/list_recent` 返回 `compute`。
  - `infra/storage/repos/exports.py` 增加 `set_compute(export_job_id, reports)`；`mark_completed` 不负责拼报告。
  - 自检结果继续落 `models/selftest.json`，每条结果加 `compute`。
  - 方案配音的汇总写 `PlanData.compute`（`plan_data` JSON，无需迁移）。
- **协议**：`protocol/ts/index.ts` 新增 `ComputeReport`，并给 `JobInfo`、`ExportJob`、`SelftestResult`、`TtsPreviewResult`、`TtsCleanReferenceResult` 加可选 `compute`；`protocol/schemas/{jobs,export,engines,tts}.json` 登记出参。Router 不校验出参，但类型与 schema 必须同步，`test_contract_sync` 保持绿。
- **账在库**：作业进行中的通知流只做即时滚动；任务终态读数据库的 `compute`。不把 `log.append` 当真相源。

### 1.4 界面口径

- **引擎页自检卡**：显示「本次实际：GPU（cuda:0）」或「本次实际：CPU」；`fallback=true` 用警示金显示「已回退 CPU：<原因>」；`unsupported` 显示「此卡不支持（原因）」，**不得点成绿**。
- **机器/引擎卡**：把「装了什么轮子/运行库」与「本次实际用了什么」分成两层。`profile.ready`、变体标记、`ttsReady` 只能说明安装态；运行态只认 `ComputeReport`。
- **试听与清洗**：`tts.preview`、`tts.clean_reference` 返回体带 `compute`，卡片在产物旁展示实际设备；清洗质量报告与算力报告分开展示，互不替代。
- **导出**：成片卡/任务详情展示 `video.encode` 的 requested/resolved/actual/fallback。`export.encoder=auto` 的帮助文案改为「按平台真试编选择硬编（NVENC/QSV/VideoToolbox），全部不可用才 libx264」，不再只说 NVIDIA。
- **TTS 设备选择**：新增 `tts.device`（`auto|cuda|cpu`，默认 `auto`），在配音设置区暴露；帮助文案与 ASR 的 `asr.device` 同义。云端引擎忽略该键并在报告中记 `cloud`。

---

## 2. ASR（P1）

### 2.1 默认值与传递链

- `config.DEFAULTS["asr.device"]` 保持 `"auto"`；同步改注释：auto = 能力+运行时都过才 GPU，失败回退并记账；显式 cuda = 承诺。
- `runtime.py::_build_transcriber`：faster-whisper 改为 `settings.get("asr.device", "auto")`；SenseVoice/Paraformer 保持传 device。
- `api/engines.py::_asr`：缺省从 `"cpu"` 改 `"auto"`。
- `selftest.py::run_asr`：`device` 缺省改 `"auto"`；`_build_asr` 对 SenseVoice/Paraformer 传 `device`，不再吞掉。
- 所有生产调用点都显式传设置值，不靠函数默认替调用方回答。

### 2.2 能力门禁与显式 CUDA

- 新增 `AsrEngine.compute()`（协议默认 `None`；各引擎实现）。
- **faster-whisper**：
  - `_create` 与 `transcribe` 记录实际成功的 device；`requested="cuda"` 时任何 CUDA 类失败直接抛 `ComputeUnavailableError`，不构造 CPU 模型。
  - `requested="auto"` 时保留现有回退，但必须记录 `fallback=true` 与原始异常；不再只写一行 warning。
  - `_compute_for` 的「非 CPU + int8 → auto」映射保留；它是精度档映射，不是设备回退。
- **SenseVoice/Paraformer（进程内）**：`_resolve_torch_device` 的 auto 探测保留；显式 cuda 失败不得改 `kwargs["device"]="cpu"`，直接抛。
- **funasr worker**：`_probe_device` 对显式 cuda 也做真实探针；探针失败发 `{"ready": false, "error": ...}` 并退出，父进程启动失败。`auto` 探针失败照旧落 CPU，但 hello 必须带 `requested/actual/fallback/reason`。
- **云端 ASR**：报告 `actual="cloud"`；不参与本地设备门禁。

### 2.3 自检断言

`run_asr` 返回体加 `compute`，并在以下情况判 `ok=false`：

- 请求 `cuda` 但实际不是 cuda（引擎应已抛错；这里是最后一道防假绿）。
- 请求 `cpu` 但实际不是 cpu。
- `actual="unknown"`。
- 请求 `auto` 且回退 CPU：**仍可 `ok=true`**，但 `compute.fallback=true`、`reason` 必须进结果，界面按回退展示。

### 2.4 测试

- 重写 `service/tests/infra/test_gpu_and_fallback.py` 中把「显式 cuda 静默回退」当预期的两条：
  - auto + CUDA 失败 → CPU 且 `fallback=true`；
  - cuda + CUDA 失败 → 抛错，不产生 CPU 结果。
- 新增自检断言测试：伪造 `compute` 为 unknown/cpu 时 `run_asr` 判红。
- 保留 `test_legacy_int8_is_never_sent_to_a_gpu`、`test_gpu_variant_two_tiers`、`test_profile_sm52_blocks_whisper_but_not_funasr`。

---

## 3. TTS（P1）

### 3.1 设备参数与 hello 捕获

- 新增 `tts.device` 设置；`factory.create(engine, models_dir, *, api_key="", model="", device="auto")` 把 device 传给所有本地引擎。
- IndexTTS / CosyVoice：
  - `_ensure_worker` 用请求的 device 启动 worker，不再写死 `"auto"`。
  - 模块级握手表从「只记进程」扩成「进程 → 就绪信息」；第二个引擎实例复用时也能拿到 device/reason（当前 `_HELLOED_FOR` 只记进程，复用实例会跳过 readline 而不知道 device）。
  - worker hello 扩为 `{"ready": true, "requested": ..., "device": ..., "fallback": ..., "reason": ...}`；`ready=false` 时父进程抛启动失败。
  - `compute()` 从 hello 构造报告；未启动 worker 时返回 `None`，不猜。
- `funasr_worker` 的 hello 同形补字段（ASR 与 TTS 共用协议习惯，不另起一套）。

### 3.2 Kokoro GPU

- `KokoroEngine.__init__(model_dir, device="auto")`。
- **worker 路径**（`workers/kokoro_worker.py`）：配置里带 device；`_probe_device` 与 funasr worker 同款（auto 真探针、显式 cuda 探针失败即失败）；`KModel(...).to(device).eval()`；hello 带 requested/actual/fallback/reason。
- **进程内路径**（`engines/kokoro.py::_ensure_pipeline`）：同样 `.to(device).eval()`；显式 cuda 失败抛错，auto 回退 CPU 并记账。
- `kmodel.device` 只能作为证据之一；最终报告以实际 `torch.device` 为准。
- 模型/音色存在性判据不变；GPU 不支持不影响 CPU 可用性。

### 3.3 自检、试听与方案配音

- `selftest.run_tts(..., device="auto")`：工厂带 device；合成成功后读 `engine.compute()`，写入结果；显式 cuda 必须 actual=cuda，否则判红。
- `api/tts.py::preview`：带 device；**试听缓存 key 加入 device 与 model**（今天只哈希 engine/voice/text，换设备/换模型会命中旧缓存）。缓存命中时报告带 `reason="缓存命中"` 与缓存时的 compute；缓存旁写 `.compute.json`，不把「这次没推理」说成「这次跑了 GPU」。
- `api/tts.py::clean_reference`：P1 走 fast 档时不涉及；P2 把分离的 compute 并入返回体。
- 方案配音：`_EnginePool` 接收 device 并传给 `create_tts`；每段成功后收集实际 compute，按引擎去重汇总到 `PlanData.compute`。全部命中缓存时 `compute` 为空并如实显示「本次全部命中缓存，未推理」。
- 云端 TTS（Edge/DashScope）：报告 `cloud`；`tts.device` 对其无效，界面不得显示本机 GPU。

### 3.4 UI 与 profile

- `TtsTab` 增加 `tts.device` 选择；自检/试听结果旁展示实际设备与回退原因。
- `MachinePanel` / `assetState`：安装态（变体标记、运行库、`ttsReady`）与运行态（最近一次 compute）分开；最近一次为 CPU 时不得给 GPU 绿灯，最近一次为 cuda 时也不因变体标记为 `unknown` 而抹掉证据（显示「本次实测 GPU」）。
- `device_profile.indextts2_gpu` / `vocal_separation_gpu` 的 hint 改为「安装后由运行时实测确认」，不再把安装完成写成 GPU 已生效。

---

## 4. 视频导出（P1）

### 4.1 AI 标注折叠进段滤镜

- `ai_label.py` 拆成：
  - `prepare(work_dir, out_size) -> AiLabelSpec`：找随包字体（缺失仍**硬失败**）、写 textfile、生成 `vf` 与**标注指纹**（文案 + 字号 + 边距 + 字体文件内容 hash；不含临时 textfile 路径）。
  - `label_vf` 保持纯函数形状，供 `cut_segment_args` 使用。
  - 删除 `apply()` 与整片 libx264 后处理。
- `encoder.py::cut_segment_args` 在 ASS 之后追加标注 `drawtext`；标注在每段烧一次，Phase B `-c copy` 拼接，不再整片重编。
- `_export_plan_once` 在段循环前 `prepare` 一次；`_SegmentJob.inputs` 仅在开启标注时加入 `ai_label` 指纹。关闭时不加键，保证未开启标注的旧缓存不失效。
- 任一段的标注 `drawtext` 失败 → 该段失败 → 现有段级回退/整片统一重跑逻辑接管；不允许静默交付无标注成片。
- 删除 `_export_plan_once` 末尾的 `burn_ai_label` 后处理与「烧制 AI 标注」进度点；`api/export.py` 的 `burn_ai_label` 传参改为传标注规格/开关，语义不变（默认关闭的政策不动）。

### 4.2 编码回执与回退可见

- `export_plan(..., compute_sink: Callable[[ComputeReport], None] | None = None)`：不改返回类型（大量测试与调用方把它当 `Path`）。
- 记录：
  - `requested`：`export.encoder` 的值（`auto` 或显式 codec）；
  - `resolved`：`auto` 经真试编选中的 codec，或显式 codec；
  - `actual`：最终成片实际 codec；
  - `fallback`：本轮发生过段级硬编失败并统一重跑 libx264；
  - `reason`：首个失败段的错误摘要与回退段数。
- 段级回退/整片统一重跑是既有的可用性保护，**不取消**；但必须进 `compute` 并在成片卡可见，不允许只留在日志。
- `api/export.py` 在导出完成时把报告写入 `export_jobs.compute` 与 `jobs.compute`。
- `export.encoder=libx264`（CPU 线）不调用 `pick_hw_encoder`；测试断言不触发硬编探测。`auto` 的探测仍走黑帧真试编。

### 4.3 测试

- 重写 `service/tests/engines/exporter/test_ai_label.py`：
  - 段滤镜包含 `drawtext`，且不存在 `ai_label.apply` 后处理；
  - 字体缺失在导出前硬失败；
  - 标注指纹进段签名；关闭标注时签名不变。
- 新增导出 compute 测试：全 NVENC → actual=nvenc；一段失败后统一重跑 → actual=libx264、fallback=true、reason 非空。
- 更新任何断言「AI 标注后处理存在」的旧测试。

---

## 5. 人声分离 GPU（P2）

### 5.1 worker 设备参数

- `vocal_separation.clean_reference(models_dir, src, *, device="auto", cuda_dll_dir=None)`：
  - 命令行追加 `--device auto|cpu|cuda`；可选 `--cuda-dll-dir <data/models/cuda>`。
  - 返回 `SeparationResult(path, compute)`（不再只返回 `Path`）；`api/tts.clean_reference`、`auto_voice`、测试同步改。
- `separation_worker`：
  - **在 import onnxruntime / audio_separator 之前**注入 CUDA DLL 目录：`os.add_dll_directory` + PATH 前置（`cublas`、`cudnn` 子目录）。PATH 会被子进程继承，`add_dll_directory` 不会，所以必须 worker 自己做。
  - `--device cpu`：`onnx_execution_provider=["CPUExecutionProvider"]`，不探 CUDA。
  - `--device cuda`：仅 `["CUDAExecutionProvider"]`；session 初始化或推理失败即失败，不回 CPU。
  - `--device auto`：先探测 CUDA provider；可用则尝试 CUDA，失败后用 CPU 完整重跑一次，回执 `fallback=true` 与原因。
  - 在 `Separator(...)` 构造后、`load_model` 前覆盖 `separator.onnx_execution_provider`。为拿**实际** provider，临时包裹 `onnxruntime.InferenceSession` 捕获 session 并读 `get_providers()`——不能只看 `get_available_providers()`；`audio_separator` 的 session 藏在 lambda 闭包里，不能靠属性读取。
  - 协议应答扩为 `{"ok": true, "out": ..., "requested": ..., "actual": ..., "fallback": ..., "reason": ..., "providers": [...]}`；失败仍是一行 `{"ok": false, "error": ...}`。
- 主进程 `_collect` 解析并校验：成功产物路径、actual 不能是 unknown；显式 cuda 但 actual=cpu 视为协议违约。

### 5.2 安装侧

- 从 `_COSYVOICE_EXTRAS` 移除 `onnxruntime==1.18.0` 硬钉；按变体安装：
  - CPU 变体：`onnxruntime==<pin>`；
  - GPU 变体：`onnxruntime-gpu==<pin>`，并与 `audio-separator[gpu]` 的依赖约束对齐（两者互斥，不能同时装）。
- **pin 由实测决定**：候选先 1.18.0（匹配现有 cuDNN 8.9），失败再试与 torch cu128/cuDNN 9 对齐的新版；只有真实 session 探测通过的版本才写进代码。规格不预写未经实测的版本号。
- 安装完成后做**最小 ONNX CUDA session 探测**（生成一个极小的 Add 模型，创建 `CUDAExecutionProvider` session 并跑一次），把结果写入 status/marker：
  - 通过：`ort_gpu=true`、provider 列表；
  - 失败：CPU ORT 保留，记录 `ort_gpu=false` 与原因，**不拖垮整个 TTS 运行环境**；界面显示「分离 GPU 不可用：<原因>」。
- `status()` 增加 ORT 变体与 provider；`device_profile.vocal_separation_gpu.ready` 由「安装态 + 探测 marker」决定，实际任务仍以回执为准。
- `cuda_runtime` 与 ORT 的 DLL 目录关系写进安装提示：GPU 分离需要 CUDA 运行库；缺失时明确引导「安装 CUDA 运行库」，不静默落 CPU 后说「已完成」。

### 5.3 UI

- 引擎页「人声分离」卡展示：安装态（CPU/GPU ORT）、最近一次实际 provider、回退原因。
- `MachinePanelEnv.test.tsx` 的 `demucs_gpu` fixture 改为 `vocal_separation_gpu`；角色文案从「Demucs」改为「MDX-Net / ONNX Runtime」。
- 清洗按钮结果旁显示「本次分离：GPU（CUDAExecutionProvider）」或「CPU（原因）」。

---

## 6. CPU 线路（全批次）

CPU 不是「GPU 失败后的垃圾桶」，是必须独立可验的一等线路：

| 环节 | CPU 口径 | 验收 |
|---|---|---|
| ASR faster-whisper | `asr.device=cpu`，CT2 CPU + int8/auto | 真转写随包样例；不初始化 CUDA |
| ASR funasr | `asr.device=cpu`，进程内/worker 都直接 CPU | 真转写；worker 不探 CUDA |
| TTS IndexTTS/CosyVoice | `tts.device=cpu`，torch CPU | 真合成一句；worker hello actual=cpu |
| TTS Kokoro | `tts.device=cpu`，`.to("cpu")` | 真合成；无 CUDA 调用 |
| 人声分离 | `--device cpu`，ORT CPU provider | 真分离一条短参考；provider 列表只含 CPU |
| 视频导出 | `export.encoder=libx264` | 真导出；不触发硬编探测；compute actual=libx264 |
| AI 标注 | 与编码器无关 | CPU 导出开启标注仍走段滤镜，无 libx264 后处理 |

**测试约束**：CPU 路径用 monkeypatch/探针断言「没有尝试 CUDA」；不允许只凭 `device="cpu"` 字符串通过。

---

## 7. 验证与验收

### 7.1 验真脚本（P3）

`scripts/verify_gpu_coverage.py`，逐部件输出：

```json
{"component": "tts.kokoro", "requested": "cuda", "status": "unsupported",
 "actual": "unknown", "reason": "torch 2.8 cu128 最低算力 sm_70，本机 sm_52"}
```

- `status` 只允许 `pass / fail / unsupported`；`unsupported` 不计入通过。
- GPU 项必须真跑最小工作负载（样例转写/短句合成/黑帧真编/短参考分离），不得只读 profile。
- CPU 项同表逐项真跑。
- `--require component=pass` 用于发布门禁；未满足退出非零。
- 脚本输出同时写 `docs` 验收记录（不含用户素材路径）。

### 7.2 本机验收矩阵

| 部件 | M4000 本机 | 结论口径 |
|---|---|---|
| ASR whisper GPU | 不可用（CT2 sm_61 下界） | `unsupported`；CPU `pass` |
| ASR funasr GPU | service/.venv cu126 可跑 | 真转写 `pass`；打包 tts-venv 另记 |
| TTS IndexTTS/CosyVoice GPU | 不可用（torch cu128 sm_70 下界） | `unsupported`；CPU `pass` |
| TTS Kokoro GPU | 同上 | `unsupported`；CPU `pass` |
| 视频 NVENC | 黑帧真试编决定 | 通过才 `pass`，否则 CPU `pass` + `unsupported` |
| AI 标注 + 硬编 | 段滤镜后仍用硬编 | 真导出抽帧验证标注在位 |
| 人声分离 ORT GPU | 真实 session 决定 | 通过才 `pass`，否则 `unsupported`；CPU `pass` |

CC >= 7.0 机器的 whisper/TTS GPU 补验单列，未跑不写通过。

### 7.3 测试清单

- `service/tests/infra/test_compute_contract.py`（新）：报告不变量、显式 cuda 不回退、unknown 成功判红。
- `service/tests/infra/test_gpu_and_fallback.py`：按 §2.4 重写。
- TTS worker 协议测试：hello 字段、Kokoro `.to(device)`、显式 cuda 失败。
- `service/tests/engines/exporter/test_ai_label.py`：按 §4.3 重写。
- `service/tests/engines/tts/test_vocal_separation.py`：命令行参数、`_collect` 的 compute/违约、返回类型。
- 协议同步与 UI 测试：`MachinePanelEnv.test.tsx`、`assetState`、`TtsTab`、`JobRow`/`ExportsCard`。
- 全量 `pytest` 与 `ruff` 在本批收口时跑；不以「只跑了新增测试」代替。

---

## 8. 风险与开放项

1. **ORT GPU 版本未定**：现有 cuDNN 8.9 与 ORT 1.18 匹配，但 sm_52 是否真有 CUDA EP 内核必须实测；新版 ORT 可能要求 cuDNN 9。P2 先做时间盒探测，未通过就保留 CPU 并把原因写进 UI/文档，不硬写一个「看起来能跑」的 pin。
2. **老卡 torch spike 不承诺**：torch 2.14.1+cu126 在 service/.venv（Python 3.12）可用，不代表 tts-venv（Python 3.11）与 IndexTTS/CosyVoice 全链可用；P3 只在隔离 venv 做最小推理，通过才考虑 `cuda-legacy` 变体，不通过维持 CPU 并记录。
3. **AI 标注折叠改变烧制时机**：从「整片后处理」变为「逐段滤镜」，需真机抽帧确认标注位置/可读性/与字幕不冲突；失败仍硬失败。
4. **缓存与签名**：标注指纹只在开启时进签名；试听缓存加 device/model；方案配音缓存不加 device（音频内容不变），但回执只记录真实推理过的段。
5. **迁移号冲突**：023 已被 UI 真相规格预留；本批用 024。若并行批次抢号，按 `test_db.py` 全等清单顺延。
6. **同树同分支**：提交只 `git add` 明确路径，严禁宽 add；开工前查 `git status`；不覆盖并行在改的 profile/UI 修正。
7. **用户可见文案**：不得出现「消重/抗比对」类表述；AI 标注默认关闭的政策不变；`unsupported` 不得被界面写成「已启用 GPU」。
8. **本机不可验项**：whisper GPU、TTS GPU 在 M4000 上无法通过；必须保留 `unsupported`，等待 CC>=7 机器补验。

---

## 9. 明确不做

- Demucs：上游权重仅科研授权，商业产品不可用；继续用 MDX-Net + ONNX Runtime。
- 云端引擎的设备选择/GPU 声明：云端只报 `cloud`。
- 视频解码与滤镜的 GPU 化（NVDEC/scale_cuda）：现有设计边界，本批不动；只修编码与 AI 标注重编。
- AI 标注默认策略、合规口径、画质门（020）与 UI 真相批次的其他欠账。
- 与算力覆盖无关的重构、命名整理、依赖升级。
