# audio.cpp 全量音频迁移方案

- 日期：2026-10-22
- 状态：方向已定并规划 v0.3 实施（业主 2026-10-22 终裁：所有**本地**音频处理任务直接走 audio.cpp，旧实现直接丢弃；**云端模型接入能力必须保留=硬约束**；D4 已拍=v0.3.0 专属轨）。本文把裁决翻译为执行序，余 D1/D2/D3/D5 待拍
- 关联：specs/2026-10-20-xpu-directml-adaptation-eval.md（分离 DML 三选一将被本方案取代）；调研全过程对话在案（audio.cpp 全模型分册审计）

## 0. 已钉死的事实基础（设计依据，来源=源头文档核对）

- audio.cpp v0.9.2，Apache-2.0（引擎本体），单 CLI（`audiocpp_cli --task tts/clon/asr/align/vad/diar/sep/...`）+ HTTP server（`audiocpp_server`，OpenAI 兼容 `/v1/audio/speech`、`/v1/audio/transcriptions(+details)`、`/v1/audio/alignments`、`/v1/tasks/run`），LRU 模型驻留 + 显存守护 + 懒加载内置，**无鉴权**（须绑定 127.0.0.1 随机端口）
- Windows 预编译：CPU 27.5MB / Vulkan / CUDA 12.4(443MB)/13.3；后端 `--backend cpu/cuda/vulkan/metal/best`
- GGUF：HF `audio-cpp/audio.cpp-gguf` + ModelScope 双源，端点可重定向——我方注册表已 GGUF-ready（builtin_specs 三档范本），接入=加 ModelSpec 行；它家 `audiocpp_model_manager` 对我方为重复建设，不用
- **ASR 功能面（97 模型分册全量审计结论）：「中文 × 字级时间戳 × 热词」交集 = 0。** 由此 ASR 适配器形态钉死为：Qwen3-ASR(0.6B/1.7B) + Qwen3 Forced Aligner 两段管线（词级时间戳），热词走 `--text` 上下文 prompt 通道
- MMS Forced Aligner：CC-BY-NC-4.0 非商业 + 中文输入直接拒收 → **禁入**
- 量化质量告警模型特异（VeVo2 非 fp32 相似度下降、ACE-Step 低精度可能失败、Qwen3-TTS q8 速度增益仅 3.6-3.8%）→ 统一 q8_0 起步 + 真机听感验收
- 周更 + 🚨 破坏性标记常态化 → **锁 tag v0.9.2 部署，升级走显式窗口**
- 算力声明为「可能」非「事实」：CUDA 12 下限=sm_52（M4000 踩线，上游有内核告警，音频模型核 Maxwell 无人验过）；RDNA1 Vulkan 有 whisper.cpp #3611 崩溃先例 → 老 GPU 结论只能真机出，三态回退 CPU

## 1. 目标态

本地音频 AI 全域（TTS/克隆/ASR/对齐/VAD/说话人轮次/分离/降噪增强）收敛为**一个 audiocpp_server 常驻子进程**（llama-server 同构，`engines/vision/runtime.py` 模式：随机端口 + `/health` 就绪 + 任务路由）；引擎中心、注册表、下载链、ComputeReport 不动。

**云端接入能力为硬约束（业主 2026-10-22 补充裁决）**：云端 ASR / TTS / 说话人分离、云端视觉回退、云端优先档能力感知引导（GTX10/M4000 等旧卡与未下载环境建议云端，5a07763 链路）**全链保留、迁移零触碰**。audio.cpp 只替代「本地」这半边——引擎选择面最终形态 = 本地 audio.cpp 引擎 × 云端引擎双轨并存；本地引擎就绪态（engine_ready / 后端三态）接回既有能力感知引导，audio.cpp 未就绪（未下载/后端不可用）时云端建议照常生效。

| 现役 | 目标（audio.cpp） | 量化 | 许可 | 能力门/备注 | 批次 |
|---|---|---|---|---|---|
| kokoro（轻 TTS，voices/*.pt） | Kokoro-82M GGUF | BF16+Q8 | Apache-2.0 | 音色锁 54 预设包，.pt 槽退役；产品音色改走克隆参考 | **批1 入册** |
| IndexTTS2 / CosyVoice3（torch 重 TTS） | IndexTTS2/2.5 GGUF（`--voice-ref` 克隆） | original+F16+Q8 | bilibili Model Use License | 5GB torch 痛点归零；沿用现役 IndexTTS2 既有许可判定，批2 前复核一次 | 批2 |
| CosyVoice3 | CosyVoice3 GGUF | F32+Q8 | Apache-2.0 | 批2 候选；另有 Qwen3-TTS 0.6B/1.7B/CustomVoice/VoiceDesign（Apache，VoiceDesign=文字造音色新能力） | 批2 候选 |
| Paraformer-large（主）+ SenseVoice + whisper | Qwen3-ASR-0.6B/1.7B + Qwen3-ForcedAligner-0.6B 两段 | F16+Q8 | Apache-2.0 | 中文+热词（context prompt）+词级时间戳（两段拼出交集）；whisper 路径退役 | **批1 入册·主位** |
| （对照档，现役同门 FunASR 家族） | Fun-ASR-Nano-2512 | F16+Q8 | Apache-2.0 | 纯文本，**无字级时间戳/热词——不进出片链主位**；转写质量 A/B 对照基线 | **批1 入册·备选** |
| fsmn-vad | FireRedVAD / PulseVAD | F32 | MIT | pause_split 本就引擎无关，保留 | 批2 |
| CAM++ diarization | MOSS-Transcribe-Diarize（一体化） | BF16+Q8+Q4_K | Apache-2.0 | 轮次切分；无声纹识别。~~Sortformer~~（CC-BY-NC-4.0，许可闸否决——对 10-22 粗表的修正） | 批2 |
| MDX 卡拉OK分离（ORT 三选一） | HTDemucs / HTDemucs-6stems | F16+Q8 | MIT | 候选还有 BS-RoFormer（Apache）/ Mel-Band-RoFormer（MIT）/ MossFormer2（Apache）；**换模型不只是换引擎**，TTS 参考清洗重验入验收 | 批2 |
| （无） | DeepFilterNet2 / GTCRN 降噪增强 | — | 待核 | 新增可选：重 BGM 素材 ASR 前置增强，默认关 | 批2 待核 |
| ACE-Step 1.5（music-venv，torch） | ACE-Step1.5-GGUF | BF16+Q8 | MIT | **伏笔**：音乐生成长期可收敛进 audio.cpp；今日落地栈不动 | 伏笔 |

许可闸禁入名单（GGUF 目录全量核对，2026-10-24）：Sortformer-Diar、MMS-Forced-Aligner、Hviske、Voxtral-4B-TTS、ControlFoley、OmniVoice、VeVo2（NC-ND）、OpenWakeWord（NC-SA）、CrisperWhisper——CC-BY-NC 系一律不挂架。备选池（许可绿、能力待核）：Higgs-Audio-v3-STT（Apache）、VibeVoice-ASR（MIT）、Nemotron-ASR（OpenMDW）、Cohere-Transcribe（Apache）、FireRedTTS3（Apache）、MOSS-TTS（Apache）、Irodori（MIT）、VibeVoice（MIT）、AudioSR 超分（Apache，新能力候选）。

对照底账来源：HF `audio-cpp/audio.cpp-gguf` 目录全量核对（2026-10-24，80+ 家族）；量化/体量为目录页口径，入册时以 HF tree API 实测钉 `download_files` 白名单。

音色语义映射：`voices/<name>.pt` → server `voice_dir` 参考音频库（`GET /v1/audio/voices`）；设置键 `tts.voice.<engine>` 沿用，值域换成音色库 ID。

## 2. 执行序（三步；「直接丢弃」落在第三步——删除跟在验收后面，是同一裁决的执行顺序，不是新增条件）

### 第一步：适配器（纯新增，不碰旧路径）

- `engines/audio/` 新域：`AudioCppSession`（server 生命周期：Popen 拉起 + 随机端口 + `/health` 轮询 + 模型配置装载 + `unload_models` 显存释放 + 退出回收），注册进 factory / analysis.runtime → registry.engine_ready 自动点亮
- TTS 适配器：`/v1/audio/speech`（OpenAI 兼容）；克隆任务 `--voice-ref`；输出 pcm16/float32
- ASR 适配器（形态已钉死）：`/v1/audio/transcriptions` 拿文本 → `/v1/audio/alignments`（或 ASR 内建 `forced_aligner_path`）拿词级时间戳 → **词级→字级 WordSpan 降级策略**（词内均匀插值；0.6s 字间隙聚句、llm_refine 窗口映射、pause_split 平移链路全部不动）；热词表 → context prompt 拼装（`--text`）
- VAD/分离/降噪：`/v1/tasks/run`
- 注册表策略（2026-10-25 讨论定稿）：上游清单为唯一数据源，我方**不做人工目录维护**——上游清单同步器机械生成 ModelSpec 行，人只做两件机器做不了的判断：①商用许可判定（NC=不挂架，红线）；②管线能力标注（字级时间戳/热词通道/任务面，依据=97 模型审计「中文×字级时间戳×热词」交集=0）。引擎中心只上架「标注可用于出片链」的模型。业主原始提案「直接用上游列表不筛选」如实入档：被 97:0 交集审计与 NC 许可红线否决裸跟随，折中即本节。同步器实现细节待拍板（D6，见 §5）
- 首批入册清单（批1，按上表）：qwen3-asr-0.6b / qwen3-asr-1.7b / qwen3-aligner-0.6b / kokoro-82m-gguf / fun-asr-nano-2512（备选对照）；diar/sep/VAD 与重 TTS 全部批2
- **前置检查项：逐模型商用许可核对**（docs/model_licenses.md 分族登记，部分社区模型 CC-BY-NC——商用红线必须逐个过，含 Qwen3-ASR/Aligner/IndexTTS2/Kokoro/HTDemucs）
- **云端零触碰**：本步不改动任何云端适配器与云端优先档引导；仅把本地引擎就绪态接回既有能力感知链路（见目标态硬约束）
- ComputeReport 惯例照出；老卡/AMD 三态（cuda/vulkan/cpu）如实回执；compute 词汇 `resolved/actual` 增加 `"vulkan"`（`_REQUESTED` 不动）
- **批次范围（2026-10-25 实施计划钉死）**：批1=ASR 两段（Qwen3-ASR+Aligner）+ Kokoro GGUF + Fun-ASR-Nano 备选对照 + `AudioCppSession` 常驻会话 + 许可表；批2=diar/sep/VAD 适配器与重 TTS 入册；RPC 安装器随 D3；对照底账全量核对日=2026-10-24

### 第二步：默认切换 + 大明十集真机验收

- 设置迁移：旧引擎 ID → 新引擎映射表，`tts.voice.*`/`asr.*` 值域转换
- 验收判据（全部真机、以大明素材为准）：

| 项 | 测法 | 通过线 |
|---|---|---|
| ASR 文本与人名 | 大明热词表（李若琏/高文才/王承恩等）context prompt 通道命中率 vs 现役 hotword 通道 | 人名错漏 ≤ 现役水平，业主过目 |
| 字幕对齐 | 新管线 vs 现役 paraformer 管线段起点偏差分布（p50/p95） | 偏差以实测基线定阈，字幕观感业主真机定 |
| TTS 听感 | 同文本同参考，新引擎 vs 现役 | 业主真机过目（q8_0 档） |
| 分离 | TTS 参考清洗质量 A/B（换模型了） | 清洗后参考可用性不降 |
| 老 GPU | GTX10 CUDA 真跑；5500XT Vulkan 真跑 | 任一后端可用即达标，失败回退 CPU 如实回执 |
| 全链 | 大明十集成品 e2e + 既有测试套适配 | 绿 |

### 第三步：焚烧现场（验收通过后执行）

删除清单：
- `engines/tts/engines/kokoro.py` + `engines/tts/workers/kokoro_worker.py`，及 cosyvoice / indextts 对应引擎与 worker
- `engines/analysis/transcriber.py` 的 funasr / whisper 路径、`funasr_worker.py`
- `engines/tts/workers/separation_worker.py` + `engines/tts/vocal_separation.py`（ORT 路径）
- `infra/model_manager/tts_runtime.py` 的 `_install_ort` / `_ort_install_plan` / `ort_state` 与 **tts-venv 全套编排**（uv sync、torch 单份、PYZ 断言跟进瘦身）
- `infra/model_manager/worker_bridge.py` 的 `VenvWorker`（四常驻 worker 全退后整桥退役）
- `data/runtimes/tts-venv` 清理入口

存量用户迁移：
- 设置回退兜底保一个版本（旧值不认识的引擎 ID 映射到新默认，不报死）
- 旧模型文件（kokoro .pth / SenseVoice / CAM++ / MDX onnx）在引擎退役后成死重 → 资产库提供「清理旧引擎资产」一键入口

## 3. 不删清单（底盘，与裁决无冲突）

注册表 + 下载器（audio.cpp 模型=加行，ModelScope 优先+镜像回退+断点续传+统一进度面照用）；引擎协议层（TtsEngine/AsrEngine + EngineCaps 诚实回执）；ComputeReport/GPU 探测；云端引擎全家（bailian ASR/TTS、云端视觉回退——audio.cpp 只替代本地）；pause_split / llm_refine / hotwords 挖掘管线（引擎无关；热词消费端从模型 hotword= 槽位改接 context prompt）。

## 4. 风险登记

| 风险 | 处置 |
|---|---|
| 中文「词」级对齐粒度行为未文档化 | 第二步先测粒度；B 计划=词内均匀插值 + llm_refine 窗口兜底 |
| context prompt 热词效力未知 | 验收指标之一；不足则双通道（prompt + OCR 融合加权） |
| 量化听感退化 | q8_0 起步、业主听感验收； unacceptable 再升 bf16 |
| v0.9.x 周更破坏性变更 | 锁 tag v0.9.2；升级=显式窗口+全链回归 |
| server 无鉴权 | 仅 127.0.0.1 随机端口，vision 先例照抄 |
| RDNA1 Vulkan 崩溃先例（whisper.cpp #3611） | 三态探测，失败即 CPU，如实回执 |
| sm_52 CUDA 未经验证 | 真机出结论；不可用不影响目标态（CPU/云端兜底已在） |
| 模型商用许可 | 第一步前置检查项，逐模型过 |

## 5. 裁决记录与余留裁决点（D4 已拍，余 D1/D2/D3/D5 待拍）

- **D1 默认 TTS（待拍）**：建议 IndexTTS2 主力（克隆对位现役重 TTS）+ Kokoro 快速档
- **D2 挂法（待拍）**：建议常驻 server（LRU/显存守护白拿，多任务共享会话；一次性 CLI 仅作诊断）
- **D3 二进制分发（待拍）**：建议混合——CPU+Vulkan 包（27.5MB 级）随安装器，CUDA 包走下载链按需
- **D4 排期轨道：已拍（2026-10-22）——v0.3.0 专属版本**。0.2.3 的 W2-W9 照走不占主轴；迁移为 v0.3 主轴，适配器可先行
- **D5 删除时机（待拍）**：建议验收过即删（本方案第三步），设置回退兜底保一个版本
- **D6 上游清单跟随机制（2026-10-25 新增，待拍）**：清单同步器（上游清单→ModelSpec 机械生成）+ 两条机械闸门（许可/能力标注）——细节见第一步「注册表策略」；拍板前批1 沿用审计钉死的手工入册清单
- **已定硬约束（业主 2026-10-22）**：云端模型接入能力必须保留（见目标态）
