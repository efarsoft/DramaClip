# XPU / DirectML 适配 · 评估规格

**日期**：2026-10-20 · **状态**：评估稿，待业主范围裁决 · **上位文件**：[windows-multi-vendor-gpu-design](2026-10-20-windows-multi-vendor-gpu-design.md)（厂商探测与本批边界）、算力回执契约（gpu-coverage-design §1）
**起因**：业主问题链「Intel 核显能否 CUDA → Arc 支持 PyTorch(XPU) → ZLUDA 如何 → 评估专门做 XPU/DirectML 适配的专项规格」。

---

## 0. 结论先行

1. **「DirectML 适配 torch 栈」被生态否决**：torch-directml 处于维护模式，最后一版 2024-09，钉死 PyTorch ≤2.3.1；我们的 TTS 三引擎与 funasr 钉 torch 2.8，进不去。Microsoft 官方战略已转向 ONNX Runtime 路线。
2. **唯一活着的 DML 通道是 onnxruntime 的 DirectML EP**，它恰好覆盖我们的两个 ONNX 原生资产：人声分离（MDX ONNX，切 EP 即用）与 funasr 的 ONNX 导出路线（paraformer 官方有 ONNX 模型；SenseVoice 官方有导出示例但 funasr_onnx 包支持曾有缺口）。
3. **Intel XPU 技术可行、商业上不划算**：torch/torchaudio 的 Windows XPU 轮已在官方 index 可装，但受益人群是「Arc 独显（≥8GB）用户」——国内创作者装机里的极小众；核显本受共享内存带宽限制，ASR/TTS 收益存疑。
4. **建议的专项形状**：只做「人声分离 DML（低垂果实）+ funasr-ONNX ASR 真机验证后决策」，XPU 全栈与 whisper/DirectML 明确不做。若第 2 项真机验证不过，本专项收缩为只有第 1 项。
5. **与多厂商批的衔接点**：厂商探测（CIM + nvidia-smi 两路合并，已提交）直接决定安装器的 ort 变体三选一；算力回执契约需兼容性扩展（`actual` 增加 `dml`）。
6. **本专项不改变 0.2.2 发布与「AI 引擎 GPU 加速 = NVIDIA CUDA only」定则**——若立项也是 0.2.3+ 的事。

## 1. 外部生态事实（每条可反证，2026-10 实查）

| # | 事实 | 证据 |
|---|---|---|
| 1 | torch-directml 维护模式，最后一版 0.2.5.dev240914（2024-09），支持 PyTorch ≤2.3.1；仓库横幅明示 maintenance mode | PyPI 项目页、microsoft/DirectML README |
| 2 | PyTorch 官方 XPU 轮覆盖 Windows，`--index-url .../whl/xpu` 可装 torch+torchaudio（2.7 起社区实测，2026 持续）；IPEX 已停止独立开发并入主线 | PyTorch XPU 文档、Intel 社区指引 |
| 3 | onnxruntime（CPU/CUDA 版）与 onnxruntime-directml 是**两个互斥的 python 包**（同名 import，不能同 venv 共存）——DML 支持是「按宿主装哪个包」的安装器决策，不是运行时开关 | ORT 官方发行矩阵、UVR DirectML 版先例 |
| 4 | funasr ONNX 路线存在：paraformer-large 官方 ONNX 模型在 ModelScope；SenseVoice 官方 export.py 示例在库，但 funasr_onnx 包 0.3.1 曾不支持 SenseVoice（issue #1909） | modelscope 模型页、FunASR 仓库 |
| 5 | ZLUDA 不构成本专项选项：v6 后商业资助再度断供转为个人项目，cuDNN 是多年缺口，且我们三栈全踩 | vosen 博客 2026 Q1&Q2 |

## 2. 逐引擎适配面

| 引擎 | 现状栈 | XPU 路（Intel） | DML 路（AMD+Intel） | 建议 |
|---|---|---|---|---|
| 人声分离 | ORT CPU EP + CUDA DLL（MDX ONNX） | —（无 XPU 构建） | **切 DML 包 + EP 名**，模型零改动 | **做**（半天~一天级） |
| ASR funasr | torch（进程内/worker） | 理论可行：xpu 轮 + 设备名迁移，算子覆盖待验 | funasr-ONNX + DML EP：需 SenseVoice/cam++/VAD 三模型导出与精度对拍 | 真机验证后决策 |
| ASR whisper | ctranslate2 | 无移植 | 无移植 | **不做**（辅引擎，CPU 即可） |
| TTS IndexTTS2/CosyVoice/kokoro | torch 2.8 钉死（worker） | 理论可行，同上但权重 5GB+ 级 | torch-directml 死路 | **不做**（批处理场景 CPU 可接受） |
| 视频编码 | ffmpeg 真试编 | — | — | 已由多厂商批覆盖，不在本专项 |

## 3. 机型基准与收益上限（诚实量化）

- **AMD 独显用户**：分离 DML + ASR-ONNX DML 双收益，是本专项唯一的质变人群。
- **Intel 核显本（最大保有量）**：DML 在共享内存架构上受带宽限制，ASR 类负载可能不比 CPU 快多少——**上线前必须真机对比 RTF，跑不赢 CPU 就不上**，宁可如实「此设备走 CPU」。
- **Arc 独显用户**：XPU 全家桶理论可行，但人群极小，撑不起重演一遍 CUDA 变体工程（安装矩阵/探针/自检/回执）的成本。
- **主场景耗时大头是 TTS 与导出**；云端 ASR 普及后 ASR 已非瓶颈——本专项的边际收益天然有限，这是「做小不做大」的根本理由。

## 4. 工程量与契约影响

- 安装矩阵：tts-venv 的 ort 侧从「cpu / cpu+cuda DLL」扩为**按宿主三选一**（NVIDIA=现状；AMD/Intel=onnxruntime-directml）；选型错误需重装，安装器要给变更入口。
- 算力回执契约：`ComputeReport.actual` 允许值增加 `"dml"`（requested 枚举不动，`auto` 下 DML 不可用回落 CPU 照旧记账）；`assert_success` 同步。
- 真算探针：DML 装后跑一次真实 session 小算子（与 CUDA DLL 安装期探测同构），失败如实 `unsupported`。
- UI：设备选项与能力文案按宿主厂商与已装变体说话（衔接多厂商批的文案收口）。

## 5. 风险

- **DML 静默错结果**：翻译/EP 层的数值差异可能「不崩溃但结果漂移」——上线门禁必须含 CPU vs DML 转写/分离的 CER/听感对拍，对拍不过不上。
- **funasr-ONNX 缺口**：SenseVoice 导出精度、cam++ 说话人标签、VAD 时间戳三者都要在 ONNX+DML 下复验；任一不齐就整条退回 CPU，不做半吊子。
- **双包互斥**：切换变体=重装 venv 依赖组，安装器必须可重入且失败可回退（复用现有六阶段安装经验）。

## 6. 范围裁决点（业主逐项确认）

1. **人声分离 DML**：做 / 不做 —— 建议做（AMD 独显用户唯一质变项，工程量最小）。
2. **funasr-ONNX ASR**：真机验证后再决策 / 直接不做 —— 建议验证（半天的验证成本换一个明确的 yes/no）。
3. **XPU（torch 全栈）**：不做 / 缓做 —— 建议**不做**，除非 Arc 独显用户成为真实客群。
4. **whisper 非 NVIDIA 加速**：不做 —— 建议不做。

## 7. 追问后的更优解：云端优先档 + 本地只收 ONNX 果实（2026-10-20 业主追问「有没有更好的方案」后补）

业主补充约束：不需要照顾开发机老硬件。把「目标」从「给 AMD/Intel 显卡找本地 GPU 补丁」还原为「大部分主机都有 AI 提速」后，答案分层：

1. **云端优先档是非 N 卡主机的正解，且引擎侧已建成并真机验收**（百炼 ASR 带字级说话人、CosyVoice 云端音色）。缺的不是适配，是**产品化**：无 NVIDIA 独显且已配 key 时自动推荐云端链路、未配 key 时引导开通并给成本预估——一个设置/UX 批次，不碰任何 AI 栈。质量还优于任何本地 GPU（模型更新、无显存墙），且完全不看机器新旧。
2. **本地栈只收 ONNX 真果实**：人声分离 DML（真可行，§6.1）+ kokoro 官方 ONNX 权重（kokoro-onnx 路线待验）。ASR 本地非 N 卡维持 CPU（质量已打磨：停顿切分/热词/护栏），要快走云端。
3. **新证据钉死 ASR 的 DML 也不成熟**：sherpa-onnx（ONNX ASR 生态旗舰）Windows 只有 CUDA 轮，DirectML 至今是 open feature request（k2-fsa #3269，2026-03）——「ONNX 收敛=免费拿到 DML」的假设在 ASR 上不成立。
4. 重 TTS（IndexTTS2/CosyVoice）非 N 卡本地无解也不必有：云端有同源模型且质量更好。

**代价如实**：云端按量计费（成本预估进引导）；本地免费档=CPU。与其做一个横跨 XPU/DirectML/双包互斥/逐引擎对拍的适配专项，不如做「云端优先档产品化 + 分离 DML」两个小批。

## 8. XPU 工作量评估（2026-10-21 业主要求补账单）

### 8.1 任务拆解

| # | 项 | 内容 | 估时 |
|---|---|---|---|
| 1 | 安装矩阵第三变体 | tts_runtime torch 组按宿主厂商加 xpu index（官方 xpu 轮自包含，无需 oneAPI 套件）；变体标记/自检/可重入同步 | 1~1.5 天 |
| 2 | 契约与解析 | requested 词汇维持 auto/cuda/cpu、`resolved/actual` 扩 "xpu"（同 dml 先例）；device_profile caps 措辞按后端感知；自检与真算探针加 `torch.xpu.is_available()` 分支 | 1 天 |
| 3 | worker/引擎迁移 | 四个 worker（funasr/indextts/cosyvoice/kokoro）设备探测与 `.to(device)` 迁移；排查各引擎内部硬编码 `.cuda()`/`torch.cuda.*` 调用并替换为设备无关写法 | 2~4 天 |
| 4 | 逐模型算子覆盖验证 | 每个模型在 XPU 上真跑一遍：CosyVoice 流匹配/hift、IndexTTS2 自定义部件、kokoro、SenseVoice——**缺算子即运行期炸，可能要求 CPU 兜底或上游补丁（不设上限的风险项）** | 2~3 天 |
| 5 | 真机硬门 + 回归 | 复用 DML 同款双轴门（提速 + 产物对拍）；全量回归与文档 | 1~2 天 |
| 6 | funasr 上游就绪度核查 | `AutoModel(device="xpu")` 的透传与内部 cuda 特判——上游无官方 XPU 支持声明，此步结果可能推翻 3/4 的估时 | 0.5 天（先行） |

**合计：约 1.5~2 周**（若收缩到只做 funasr ASR：3~4 天 + 验证）。

### 8.2 决定性约束：没有验证硬件

开发机现有三块「Intel 相关」硬件全部不能跑 XPU 后端（要求 Arc / Data Center GPU / Meteor Lake+ 核显）：Quadro M4000 是 N 卡、RX 5500XT 是 A 卡、Comet Lake 核显是 Gen9.5（XPU 明确不支持）。**没有 Arc A770/A380 级别的测试卡或 Core Ultra 机器，第 4/5 步无法诚实执行**——DML 批的「提速+位级对拍」硬门就是为此设计的，不能在 XPU 上降级为「应该能跑」。

### 8.3 结论

工作量本身（1.5~2 周）不是拦路虎，**「无验证硬件 + 无已知 Arc 客群」才是**。维持 §6/§7 裁决：XPU 不做；若将来拿到 Arc 测试卡且客群成立，按 §8.1 账单立项，先行做第 6 项（0.5 天）确认 funasr 上游就绪度再决定其余投入。

## 明确不做

- 不动 0.2.2 发布计划；不改 CUDA-only 定则的对外口径；不引入 torch-directml；不引入 ZLUDA；macOS（CoreML/MPS）另立规格。

## 9. 状态变迁（2026-10-25 两阶段）

### 9.1 收口（同日上午，已被 §9.2 推翻）

初版结论为「专项关闭」：分离 DML 已落地留用至 v0.3 焚烧、funasr-ONNX 关闭、XPU 维持不做、AMD/Intel 加速命题移交 audio.cpp Vulkan 后端。

### 9.2 业主推翻（2026-10-25 晚）：XPU 核显/独显专项重启，实现先行

业主裁决：**推翻收口，实现 XPU**；AMD 显卡路线（DML-ONNX）拍板排除（复杂度考量）；Intel 核显/独显（Arc/Meteor Lake+）走 PyTorch XPU 轮；**真机验证挂起——业主稍后提供开发机**，实现先行、验证按 playbook 后补。audio.cpp 迁移（v0.3）不受影响：XPU 变体是现役 torch 栈的安装期决策，v0.3 焚烧清单照旧。

**已落地（同日批次）**：

| 项 | 内容 |
|---|---|
| D3D 检测层 | `infra/d3d_probe.py`：纯 ctypes 枚举 DXGI 适配器（厂商/设备 PCI ID + 专用显存，软件/虚拟机剔除，失败回退 CIM 并留 stderr 痕）；采纳 Const-me/Whisper 系 fork 的厂商 ID 形态（0x1002/0x10DE/0x8086/0x15AD） |
| gpu.snapshot | DXGI 为主合并 CIM（名称补驱动版本），`classify_vendor` 支持 PCI ID 精判 |
| compute 契约 | `resolved/actual` 词汇 + `"xpu"`（dml 同款先例；requested 词汇不变） |
| device_profile | Intel XPU 双门（vendor intel + torch 变体 xpu + 快照含 Arc/Ultra 级适配器）→ funasr/indextts2 caps 点亮 XPU；whisper（ctranslate2 无后端）与分离维持现状；新增 `torch_device` 字段 |
| device_resolve | auto ready → `torch_device`（nvidia=cuda / intel+xpu 轮=xpu / 其余 cpu） |
| 安装矩阵 | `_gpu_variant()` 三分支：Intel Arc/Ultra 级 → xpu 轮（官方 xpu index，torch/torchaudio 2.8.0 与现役钉版精确匹配）；进程内 `torch_variant()` 词汇扩展 |
| worker/引擎 | 四 worker + kokoro/transcriber 进程内探针加 xpu 支（`torch.xpu.is_available()` + mini-op，失败如实回退 CPU）；funasr 1.4.16 源码级原生透传（§8.1 第 6 项上游就绪度核查在源头层面通过） |

**未验证风险（开发机到位后按 playbook 关闭）**：逐模型算子覆盖（CosyVoice 流匹配/IndexTTS2 自定义部件/kokoro 在 XPU 上未验，缺算子即运行期炸 → 显式 cpu 设置回退）；RTF 收益未测（核显共享内存带宽，跑不赢 CPU 就不上）。

**验证 playbook（开发机到位后执行）**：
1. `torch.xpu.is_available()` + `torch.xpu.get_device_name(0)` 记录设备；
2. 四 worker 自检（引擎页逐个跑通）；
3. paraformer@xpu vs cpu：大明一集 CER + 段起点偏差 p50/p95 + RTF；
4. TTS 听感（q8/bf16 语义在 GGUF；torch 栈直接同权重对比）+ RTF；
5. 任一引擎算子缺口 → 该引擎显式回 CPU（`asr.device`/`tts.device` 设置），其余保留 XPU；
6. 结论回写本节。

**AMD DML-ONNX：业主拍板排除（复杂度考量）**——funasr-ONNX/kokoro-onnx 不做，5500XT 的分离 DML 已落地成果留用。**UI 显式 xpu 选项**：auto 默认已自动上 XPU，显式选项待协议加 `torch_device` 字段后另行小批。

### 9.3 AMD 路线终裁与 spike 记录（2026-10-25 晚）

业主再度拍板：**AMD 路线选「等 v0.3 Vulkan」**（原排除升级为终裁）；spike 已在本机 5500XT 真跑，发现归档：

- **funasr 官方导出器深坑**：`AutoModel.export(type=onnx)` 的图内 `make_pad_mask` 钉死常量 512 帧（约 5 秒），`max_seq_len` kwarg 经 deepcopy 链**不生效**（内层模型 `export_rebuild_model` 重新绑定导出面，实例级 patch 被覆盖）；正确 patch 点= `funasr.models.paraformer.export_meta` 模块函数（已实测可注入 alphas/peaks 输出）。输入 >~200 帧即 ScatterND 形状错——**官方单图导出对长音频就是坏的**，与社区 fork（QuadraV 修复版）修复对象一致。
- **时间戳可随图带出**：patch `export_meta.export_forward` 返回 predictor 的 `alphas`/`pre_peak_index` 后，导出物含字边界帧数据（本机实测 [1, L+1] 形状）。
- **热词不可导出**：SeACo 热词模块无 ONNX 导出通道——任何 ONNX 化路线的公共缺口。
- **终裁**：不修官方导出器、不引 sherpa-onnx 拆分图自研编排；AMD 用户现阶段转写/配音走 CPU 或云端引擎，本地加速等 v0.3 Vulkan。spike 导出物（865MB）已清理；脚本要点存本节。
