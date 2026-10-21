# Windows 多厂商 GPU 覆盖 · 设计规格

**日期**：2026-10-20 · **状态**：待实施 · **上位文件**：[2026-10-20-gpu-coverage-design.md](2026-10-20-gpu-coverage-design.md)（全流程算力覆盖的既有契约）
**起因**：业主原话「需要兼顾大部分主机，而不是局限于我这一个」。
**范围裁决**（2026-10-20 业主逐项确认）：

- 目标平台是 Windows + macOS，但打包交给 GitHub CI/CD、本地只有 Windows 机 → **按方案 A 拆分**：本批只做 Windows 三厂商（NVIDIA / AMD / Intel），macOS 另立规格。
- **定则（2026-10-20 业主裁决）：AI 引擎（ASR / TTS / 人声分离）的 GPU 加速只支持 NVIDIA CUDA。** 非 NVIDIA 主机上的 ASR/TTS **走 CPU 并明确说明**；不做 DirectML / ROCm / torch-directml / CoreML 试验；人声分离维持 CUDA-only（有 NVIDIA 卡走 CUDA，否则 CPU，不引入第二套 GPU 后端；设备如何解析见 §3.5）。
- 视频编码的硬编候选扩展到 AMD（AMF）与 Intel（QSV），是否可用仍由**真试编**判定。**硬编码器不属于 CUDA 承诺**，不受上一条定则约束。
- **机型基准（2026-10-20 业主原话「不用管这台机器，兼顾大部分机型就好」）**：设计输入是主流机型类别——无独显/核显本、NVIDIA RTX 20/30/40/50 与 GTX 16（算力 ≥7.0）、NVIDIA GTX 10 及更早（算力 <7.0 的存量段）、AMD RX 独显。**开发机（Quadro M4000 老卡 + Radeon RX 5500 XT 双卡 + GameViewer 虚拟显示适配器）只作回归机，不作任何厂商判据**，它的算力档、双卡枚举顺序、虚拟适配器都不构成设计前提。

**本批不改变**：打包配置、CI 工作流、依赖清单、分发形态。本文件不合并进 `docs/05-开发路线图.md`。

---

## 0. 结论先行

1. 现有「GPU 覆盖」事实上是「NVIDIA 覆盖」：`gpu.py` 只查 `nvidia-smi`，AMD/Intel 主机被报成「未检测到 NVIDIA」；视频编码候选只有 NVENC/QSV，AMD 主机明明可用 AMF 却落到 libx264。
2. 本批把**探测**、**视频硬编**、**界面口径**、**验真脚本**四处统一到「宿主厂商」这一事实源；AI 推理加速仍然只承诺 NVIDIA CUDA。
3. 非 NVIDIA 主机不是「不支持」而是「这部分走 CPU」：视频剪辑可能仍有硬编收益，ASR/TTS 明确走 CPU，人声分离明确仅支持 CUDA。
4. AMD/Intel 的代码路径在本批实现，但是否真可用**只认真试编和外部真机回执**；没有回执前不写「已通过」。
5. 「NVIDIA 主机」不是一个齐质的档位：ASR（ctranslate2）、TTS（torch）、人声分离（ONNX Runtime）三条栈的**最低算力线各不相同**，一个 `tts.device` 装不下两套栈。§3.5 把人声分离的设备决定权从 `tts.device` 收回，改成恒按 `auto` + 如实回执，并把降级链修成 CUDA → CPU → 滤镜；§3.6 把 ASR/TTS 两条有设备开关的栈收口到**一个解析入口 + 一张能力表**（分离与视频编码各有自己的运行时试用型解析），回执沿用既有的 `jobs.compute` / `export_jobs.compute` 账本，不另立 settings 键。

---

## 1. 现状与根因（每条可反证）

| # | 现状 | 证据 | 后果 |
|---|---|---|---|
| 1 | 宿主只认 `nvidia-smi` | `service/dramaclip/infra/gpu.py::detect` 仅遍历 `_smi_paths()`；无输出即 `vendor="none"` | AMD/Intel 主机在总览显示「未检测到 NVIDIA」，状态栏显示「无独立显卡 · CPU 模式」，事实错误 |
| 2 | 视频候选缺 AMF | `encoder._HW_CANDIDATES_BY_PLATFORM["win32"] == ("h264_nvenc", "h264_qsv")` | AMD 独显主机自动导出直接回退 libx264，硬编收益归零 |
| 3 | 验真脚本写死 NVENC | `scripts/verify_gpu_coverage.py::_nvenc_probe` 与 `_video_encode_cuda` / `_video_ai_label_cuda` 均硬编码 `h264_nvenc`；`_HW_ENCODERS` 不含 `h264_amf` | AMD 主机即使 AMF 可用也会被判 `unsupported`/`fail`，发布门禁失真 |
| 4 | 文案与判据混用 | `GpuCard.tsx`、`useGpuInfo.ts`、`MachinePanel.tsx`、`StatusBar.tsx` 多处 `vendor !== 'nvidia'` 的文案默认「无 NVIDIA = 无 GPU」；`TtsTab.tsx:354` 用 `ortGpu.reason.includes('未检测到 NVIDIA')` 决定是否显示「重跑安装」 | 非 N 卡用户被劝退；改一句后端文案就能悄悄改变 UI 行为 |
| 5 | 设备选项永远有 CUDA | `AsrTab.tsx` / `TtsTab.tsx` 的 `PARAMS` 是模块级常量，不读宿主事实 | AMD/Intel 用户可以选择一个必然失败的承诺项 |
| 6 | 设备档位把非 N 卡一律当「无显卡」 | `device_profile.tier_of` 非 nvidia 直接 `none`；`_TIER_LABELS["none"]="未检测到 NVIDIA 显卡"`；推荐语/提示语均按 CUDA 写 | 文案误导，且「有 AMD 卡」与「真没卡」无法区分 |
| 7 | 人声分离的设备继承自 `tts.device` | `api/tts.py:62`、`api/tts.py:100` 把 `tts.device` 原样传给 `vocal_separation.clean_reference`；显式 `cuda` 在 worker 里不重试 CPU（`separation_worker.py:122-126`） | 见 §3.5：torch 与 ONNX Runtime 是两套独立加速栈，算力下限不同，一个开关必然在部分主流存量机上错 |

**既有硬事实**（写作时实测，供判据引用）：

- 随包 FFmpeg 8.1.1 的编码器列表包含 `h264_nvenc`、`h264_amf`、`h264_qsv`、`h264_videotoolbox`；**列表里有 ≠ 真能编**。
- 开发机上试编 `h264_amf` 在 `encoder->Init()` 失败（error 5）。该机器 CIM 同时枚举出 Radeon RX 5500 XT，所以**这条失败不能归因于「没有 AMD 设备」**，真实原因未查；本批不拿它当 AMF 判据，AMF 可用性只由外部 AMD 真机回执决定。
- `ctranslate2` 最低算力 sm_61、tts-venv 的 CUDA 轮最低 sm_70 等边界见上位规格 §0.2，本批不改变。

---

## 2. 宿主探测（`gpu.py`）

### 2.1 数据形状

`GpuInfo` 增加适配器清单；原有字段语义不变：

```jsonc
{
  "ready": true,
  "vendor": "amd",                 // nvidia | amd | intel | other | none | unknown(待定态)
  "name": "AMD Radeon RX 6600",
  "driver_version": "31.0.12027.9001",
  "max_cuda_version": "",          // 仅 NVIDIA 且 nvidia-smi 可读时非空
  "memory_total_mb": 0,            // 仅 NVIDIA 且 nvidia-smi 可读时可信；非 N 卡恒为 0
  "compute_cap": "",
  "adapters": [
    { "name": "AMD Radeon RX 6600", "vendor": "amd", "driver_version": "31.0.12027.9001" },
    { "name": "Intel(R) UHD Graphics 770", "vendor": "intel", "driver_version": "31.0.101.5333" }
  ]
}
```

- **不采信 `Win32_VideoController.AdapterRAM`**：该字段是 UInt32，现代显卡普遍饱和/失真；非 NVIDIA 的显存宁可为 0（未知），不写假数。
- `ready` 语义保持现状：`false` = 探测尚未完成或失败；`true` = 已得出本轮结论（不代表有 GPU）。
- 待定态 `_PENDING_FIELDS` 增加 `"adapters": []`，与现有一致返回。

### 2.2 Windows 探测流程

`detect()` 改为两路事实合并，**不新增依赖**：

1. **CIM 枚举所有显示适配器**（Windows）：
   ```
   powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command
   "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;
    Get-CimInstance -ClassName Win32_VideoController |
    Select-Object Name,DriverVersion | ConvertTo-Json -Compress"
   ```
   - 固定脚本、无用户输入插值；`CREATE_NO_WINDOW`；超时 10s。
   - 输出可能是单个对象或数组，两种都解析；`Name`/`DriverVersion` 缺失按空串处理。
   - 解析前去掉 UTF-8 BOM；非法 JSON 视为本次 CIM 失败。
2. **nvidia-smi**：沿用现有 `name/driver_version/memory.total/max_cuda/compute_cap` 查询与解析。
3. **合并**：
   - CIM 适配器先过滤虚拟/基础显示设备；
   - 若 nvidia-smi 有结果且 CIM 里没有 NVIDIA 条目，补一条 NVIDIA 适配器；
   - 若两者都有 NVIDIA，用 nvidia-smi 的 `name`/`driver_version` 覆盖该条（CUDA 细节只来自 smi）；
   - 主适配器按 **NVIDIA > AMD > Intel > other** 选择；同级保持 CIM 返回顺序；
   - `vendor/name/driver_version` 取主适配器；`max_cuda_version/memory_total_mb/compute_cap` 仅当主适配器是 NVIDIA 且 smi 可读时填充，否则为 `""/0/""`。

### 2.3 分类与过滤

- 虚拟/基础设备过滤（名称大小写不敏感，含即剔除）：
  `Microsoft Basic Display Adapter`、`Microsoft Basic Render Driver`、`Microsoft Remote Display Adapter`、`Microsoft Hyper-V Video`、`VMware`、`VirtualBox`、`Parsec`、`Citrix`、`Virtual Display`、`Mirage`。
- 厂商分类（按顺序匹配名称）：
  - `nvidia`：`nvidia` / `geforce` / `quadro` / `tesla` / `rtx` / `gtx`
  - `amd`：`amd` / `radeon` / `ati`
  - `intel`：`intel`
  - 其余：`other`
- 非 Windows 平台本批不调用 CIM，保持既有 smi 路径（macOS/Linux 不在本批范围）。

### 2.4 失败与待定语义

- CIM 失败（无 PowerShell、超时、非法 JSON）：不抛错，`adapters=[]`，继续用 nvidia-smi；两者都无 → `vendor="none"`。
- CIM 看到 NVIDIA、但 nvidia-smi 不可用：`vendor="nvidia"`，`name/driver_version` 用 CIM 值，CUDA 三项为空。**不得**据此断言「驱动太旧」——见 §3.3。
- 探测自身异常由 `prefetch` 吞掉并保持待定态（现有行为不变）；`detect()` 仍只由后台线程调用。
- 扫描命令不写入日志原文，避免把主机用户名等路径带进日志。

### 2.5 可测试的纯函数切分

为免测试只能整段桩 subprocess，`gpu.py` 明确切出：

- `classify_vendor(name: str) -> str`
- `is_virtual_adapter(name: str) -> bool`
- `parse_cim_output(raw: str) -> list[dict[str, str]]`（严格：非法 JSON 抛 `ValueError`）
- `choose_primary(adapters) -> dict | None`
- `_query_cim_adapters() -> list[dict]`（吞异常）
- `_query_nvidia_smi() -> dict | None`（从现有 `detect()` 内联逻辑抽出）

`detect()` 只做合并与输出组装。

---

## 3. 设备档位与文案（`device_profile.py`）

`profile()` 的判据仍是**硬件事实 + 运行时安装态**，不读 UI、不猜。

### 3.1 分档

- `tier_of(vendor, memory_total_mb)`：仅当 `vendor == "nvidia"` **且显存 > 0** 时按现有阈值分档；其余一律 `none`。
- 新增别名：`nvidia_hw = (vendor == "nvidia")`（只要有 N 卡硬件，不论显存/驱动是否可读）。
- `is_nvidia` 继续表示「N 卡且显存可读」，用于 CUDA 能力判定。

### 3.2 档位标签与推荐（按厂商）

| vendor / 状态 | `tier_label` | `recommendation` |
|---|---|---|
| `unknown`（探测中） | `显卡探测中…` | `显卡状态探测中：本地引擎均可先用 CPU 运行` |
| `nvidia`，显存可读 | 现有四档 | 现有逻辑；但补两个诚实分支（§3.3） |
| `nvidia`，显存=0 | `NVIDIA 显卡 · 显存信息不可读` | `NVIDIA 显卡在场但显存信息不可读：重装 NVIDIA 驱动后重试，或改用云端引擎`（若 `nvidia-smi` 整体不可用，按 §3.3 的驱动不可读分支优先） |
| `amd` | `AMD 显卡 · 视频硬编，AI 引擎走 CPU` | `视频导出可用本卡硬件编码（AMF，导出时真试编）；ASR/TTS 加速需 NVIDIA CUDA，当前走 CPU，可改用云端引擎` |
| `intel` | `Intel 显卡 · 视频硬编，AI 引擎走 CPU` | `视频导出可用本卡硬件编码（QSV，导出时真试编）；ASR/TTS 加速需 NVIDIA CUDA，当前走 CPU，可改用云端引擎` |
| `other` | `其他显卡 · AI 引擎走 CPU` | `视频导出会在真试编后选择硬编或 libx264；ASR/TTS 加速需 NVIDIA CUDA，当前走 CPU` |
| `none` | `未检测到独立显卡` | 现有：`推荐启用云端引擎（百炼）：本地 GPU 加速不可用或显存不足` |

### 3.3 驱动引导的三个诚实分支

现有代码把「读不到 CUDA 上限」与「CUDA 上限低于 12」混成一种。改为：

- `driver_old = nvidia_hw and max_cuda_version != "" and not _cuda_major_ok(...)`
  → `needed=true`，reason 保持「驱动支持的 CUDA 上限 {x} 低于 12…」。
- `driver_unknown = nvidia_hw and max_cuda_version == ""`
  → `needed=true`，reason：`未能读取 NVIDIA 驱动的 CUDA 上限（nvidia-smi 不可用或查询失败），无法确认 CUDA 12 支持：请重装 NVIDIA 驱动后重试`。
- 其余 `needed=false`。

推荐语同步修正一个既有假话：`nvidia_hw` 且 `driver_old` 时，不再说「本地 GPU 引擎可启用（安装 CUDA 运行库后生效）」，改为
`驱动支持的 CUDA 上限 {x} 低于 12：先更新 NVIDIA 驱动，或改用云端引擎`。
`nvidia_hw` 且 `driver_unknown` 时改为
`NVIDIA 驱动信息不可读（nvidia-smi 不可用或查询失败）：修复驱动后重试，或改用云端引擎`。

优先级：`driver_unknown` > 显存不可读 > `driver_old` > 常规分档。`nvidia-smi` 整体不可用时，显存也必然读不到，推荐语只报驱动不可读这一条根因，不重复报「显存不可读」。

### 3.4 CUDA 能力提示（`caps.*.hint`）

非 NVIDIA 时不再复用「需 4GB+ 显存且驱动支持 CUDA 12+」这类对 AMD/Intel 无意义的句子。逐项：

| cap | unknown | amd / intel / other | none |
|---|---|---|---|
| `faster_whisper_gpu` | `显卡状态探测中：转写暂走 CPU` | `转写 GPU 加速需要 NVIDIA CUDA，当前走 CPU` | 同 amd 列 |
| `indextts2_gpu` | `显卡状态探测中：音色克隆暂走 CPU` | `音色克隆 GPU 加速需要 NVIDIA CUDA，当前走 CPU` | 同 amd 列 |
| `funasr_gpu` | `显卡状态探测中：转写暂走 CPU` | `转写 GPU 加速需要 NVIDIA CUDA，当前走 CPU` | 同 amd 列 |
| `vocal_separation_gpu` | `显卡状态探测中：人声分离暂走 CPU` | `人声分离 GPU 加速仅支持 NVIDIA CUDA，当前走 CPU` | 同 amd 列 |
| `local_visual_2b/4b/8b` | `显卡状态探测中` | `本地视觉模型需要 NVIDIA CUDA，当前不可用` | 同 amd 列 |

NVIDIA 主机的提示保持现有逻辑；新增 `driver_unknown` 时，CUDA 四项提示为「未能读取 NVIDIA 驱动信息，无法确认 CUDA 12 支持」。NVIDIA 但算力不满足某条栈的下限时（§3.5）：`indextts2_gpu` 的 hint 写「此卡算力 sm_{cc} 低于 torch cu128 下界 sm_70，音色克隆走 CPU」，`faster_whisper_gpu` 保持既有 sm_61 文案，`vocal_separation_gpu` 不设下限（ORT 已在 sm_52 实测可用）。人声分离的早退分支同样按此顺序：非 NVIDIA → 厂商文案；NVIDIA 驱动不可读 → 驱动文案；然后才走现有显存/运行库/ORT 分支。

### 3.5 人声分离的设备不得复用 `tts.device`

三条 AI 推理各自绑一套运行时，**算力下限不是一个数**：

| 运行时 | 承担的引擎 | GPU 可用下限 | 证据强度 |
|---|---|---|---|
| `ctranslate2` | ASR（Whisper / SenseVoice） | sm_61 | 上位规格 §0.2 已实测 |
| `torch` cu128 | TTS（IndexTTS2 / CosyVoice） | sm_70 | `tts_runtime._gpu_variant` 注释：sm_52 装得上、算子无内核（2026-10-16 实测） |
| `onnxruntime` CUDA EP | 人声分离（MDX-Net） | ≤ sm_52（sm_52 实测可用，官方下限未核对） | 开发机 `separation.cuda` 回执 `actual=cuda`；结论只用作「ORT 的下限明显低于 torch 的 sm_70」，不据此承诺更低档 |
| FFmpeg 硬编 | 视频导出 | 不看算力，只看真试编 | 本规格 §4 |

**这不是老卡特例，是存量段的通病**：算力落在 sm_61～sm_69 的卡（GTX 10 / Pascal）上，ASR 能走 GPU、TTS 的 torch 只能走 CPU、分离的 ORT 能走 GPU——三条栈各在一档，用户看到的却只有一个「运行设备」。再往老（Maxwell 及更早）掉，ASR 也回 CPU，但 TTS 与分离仍然分裂。用户为「让 IndexTTS 别报 CUDA 失败」把 `tts.device` 设成 CPU 时，会顺手把可用的 GPU 分离也关掉；设成 CUDA 时，反过来让分离在「ORT 装的是 CPU 轮」的机器上硬失败——而这类机器非常常见，因为 CUDA 运行库是独立作业，**先装运行环境、后装 CUDA 库**的次序会留下 CPU 轮 ORT 标记（`tts_runtime._install_ort` 的 `want` 判据）。

规定：

- `tts.device` 只承诺 torch 那条栈（IndexTTS2 / CosyVoice 合成）。
- 人声分离自己解析设备，**恒按 `auto` 起步**：ORT 有 CUDA EP 就用，失败按 `auto` 语义完整重跑 CPU 并在回执写明原因；没有 CUDA EP 直接 CPU 并在回执写明。调用方（手动清洗 / 自动提取 / 导出预检）不再传 `tts.device`。
- 不给分离加第三个下拉（YAGNI）：后端事实已由安装探针落进 `ort_state`，界面显示「本次：GPU / CPU（原因）」即可，用户不需要重复表达一次意愿。
- 相应地，`auto_voice.py` 的降级链修正为 **CUDA 分离 → CPU 分离 → 滤镜**：显式设备继承造成的「CUDA 一失败就跳滤镜」不再是可达路径，滤镜只留给 CPU 分离也失败的情况。这条改动的验收见 §12。
- 本条只修订上位规格 §5.1 的**调用侧取数**：worker 的 `--device` 协议、`vocal_separation.clean_reference(device=...)` 参数形状与回执契约都不变，改的是「谁决定传什么」。
- 清洗留痕入库口径：沿用既有算力账本 `jobs.compute` / `export_jobs.compute`（024 迁移，`JobStore.set_compute` / `exports_repo.set_compute`）——不新建表、不加迁移、**不写 settings**（初稿的 `tts.voice.receipt` 作废：那是给已有账本再造一份真相源）：
  - 手动清洗（`tts.clean_reference`）与自动提取（`tts.auto_voice`）在操作开始时建一条 `voice_clean` 任务行（`ref_id` = 产物路径），成功把本次报告写进 `jobs.compute` 并置完成，失败把原因写进 `error` 并置失败；
  - 出片预检（`api/export.py::_ensure_clone_voice`）不另建任务行：清洗报告并入该导出已有的 `reports` 数组，与 `video.encode` 同账；
  - 方法（分离 / 滤镜）由 component 区分：分离成功写 worker 原报（`tts.separation`，`actual` 由 session provider 证明）；滤镜兜底写 `tts.reference_clean.filter`（`requested=auto`、`resolved=cpu`、`actual=cpu`、`reason` 写明分离失败原因与「已用滤镜清洗」）；用户主动选 fast 时同一 component，reason 写「用户选择快速滤镜清洗」；
  - 生命周期如实：`jobs` 的「清空已完成」按既有语义会清除这些任务行——回执与其它引擎账同生命周期，不承诺跨清理持久；需要长期档案时另行立项（§9）。**通知流与 toast 仍不作真相源**。

### 3.6 唯一设备解析入口（本批内建）

现状是「能力表只给界面看，引擎各读各的设置」：`device_profile.profile()` 已有 per-engine 的 `caps`（也已有 ctranslate2 的 sm_61 下限），但引擎/API 侧多处直接读 `asr.device` / `tts.device`，界面又自己按 vendor 决定选项——同一件事三套判据。本批收口为：

- **能力表补全运行时事实**：
  - `indextts2_gpu.ok` 增加 torch cu128 的 sm_70 下限（运维门禁已存在：`tts_runtime._gpu_variant` 在算力 <7.0 时只装 CPU 轮）；`ready` 改为真结论（`ok` 且 tts-venv 的 torch 变体为 `cuda`），不再恒 `False`。
  - `funasr_gpu` 不写静态下限：它可能跑在打包态的 tts-venv（cu128，sm_70）或 dev 态的主进程 torch（构建不同，本机 sm_52 实跑在 GPU）——`ready` 已按两种实况分别探测，静态下限会造出假阴性。
  - 每个 cap 增加 `reason`（机器可读的不可用原因）；`hint` 仍只面向用户。`resolve` 只读 `ok` / `ready` / `reason`，**不解析 `hint` 文案**——§1 根因 4 的教训。
  - `profile()` 增加可选入参 `torch_variant: str | None`（由调用方按自己的 `data_dir` 读入），避免 `system.health` 与解析入口各自用全局 data_dir 得出不同结论；缺省时保持现有探测。
- **新增 `service/dramaclip/infra/device_resolve.py`**：

```python
@dataclass(frozen=True)
class DeviceResolution:
    component: str      # asr.faster_whisper / asr.sensevoice / asr.paraformer /
                        # tts.indextts2 / tts.cosyvoice
    cap: str            # 对应 device_profile.caps 的键
    requested: str      # auto | cuda | cpu（用户意图）
    resolved: str       # cuda | cpu
    actual: str         # cuda | cpu（预期设备，不是运行证据）
    device: str         # 传给引擎/worker 的设备串
    reason: str         # 为何不是 cuda（auto 落 CPU 时必填）
    downgraded: bool    # auto 下硬件 ok 但运行时未就绪，本次解析落 CPU

def resolve(component: str, requested: str | None, data_dir: Path) -> DeviceResolution
```

规则：

- `cuda` 是承诺：cap 不 `ready` 时立刻抛 `compute.ComputeUnavailableError(reason)`，在拉起模型/worker 之前失败，错误里说清算力下界或未装的运行时。
- `cpu` 恒 CPU。
- `auto`：`cap.ready` → cuda；否则 cpu 并写 reason（`cap.ok` 为真而 `ready` 为假时 `downgraded=true`）。
- 快照未就绪（`ready=false`、`vendor=unknown`）：**不得据此判 CPU**——返回 `device="auto"`、`reason="显卡状态探测中，交给引擎自判"`，由引擎自身的 auto 语义运行，下一次调用走正常解析；防止服务刚启动的待定态被固化成 CPU。
- 解析结论是**预期**；回执的 `actual` 永远来自运行证据（worker hello / session provider / 引擎回报），`resolve` 不得代签。`unknown ≠ ok` 不变。
- 调用点收敛为三处：`engines/analysis/runtime._build_transcriber`、`engines/tts/factory.create`、`api/engines._asr/_tts`（自检直连）。其余入口只传用户意图字符串，不再各自判断。
- **不纳入 resolve 的两类**：
  - 人声分离没有设备开关，恒以 `auto` 交给 worker（§3.5）——worker 的 provider 探测本身就是它的解析器，且会把「CUDA EP 缺失 / CUDA 试跑失败」的真实原因写进回执；在入口预解析成 `cpu` 反而会丢掉原因。
  - 视频编码已有自己的解析器（`encoder.pick_hw_encoder`，真实试编 + 会话缓存）——下限不可预知，只能试。
  两者与 resolve 共同遵守的是「解析 → 运行证据 → `ComputeReport`」这一契约，而不是同一张判据表。
- 效率：`gpu.snapshot()` 已是进程缓存，caps 是只读少量 marker 的纯函数；**不做第二层缓存**，避免运行环境刚装好后仍读旧结论。

---

## 4. 视频硬件编码（`encoder.py`）

### 4.1 候选序

```python
_HW_CANDIDATES_BY_PLATFORM = {
    "win32": ("h264_nvenc", "h264_amf", "h264_qsv"),
    "darwin": ("h264_videotoolbox",),   # 本批不改，macOS 另立规格
}
_HW_CANDIDATES_LINUX = ("h264_nvenc", "h264_qsv")  # 本批不改
```

顺序理由：N 卡主机第一次就命中；AMD 主机在 nvenc 黑帧试编失败后第二次命中；Intel 核显最后兜底。所有候选都失败才回 libx264。

### 4.2 AMF 质量参数

```python
if video_codec == "h264_amf":
    return [
        "-usage", "transcoding",
        "-quality", "quality",
        "-rc", "cqp",
        "-qp_i", "22", "-qp_p", "22", "-qp_b", "24",
    ]
```

- `transcoding` 对齐文件导出而非低延迟场景；`quality` 优先画质。
- `cqp + 22` 与 NVENC 的 `vbr/cq 22`、QSV 的 `global_quality 22` 对齐；B 帧 `24` 为常规略降。
- 参数只在这一处定义：正式段编码与探针共用 `_video_codec_params()`，不得各写一份。

### 4.3 真试编、缓存与回退

- 探针形状不变：0.1s 256×256 黑帧 + 正式质量参数 + `-f null -` + 15s 超时。
- `pick_hw_encoder()` 首个真试编通过者胜出，会话级缓存（全失败缓存哨兵 `""`）。
- AMF 在 NVIDIA 机器上失败属于预期：继续试下一个候选，不影响最终选中 NVENC；探测自身的任何异常按该候选不可用处理。
- `_HW_ENCODERS` 增加 `h264_amf`，使段级回退与整片 libx264 统一重跑的判定同样覆盖 AMF（判定即 `_HW_ENCODERS` 成员检查，`_fallback_eligible()` 读 `-c:v` 后的 codec）。
- 用户显式固定某编码器时行为不变：不探测、直接使用；若该段真编失败，仍走既有「段级回退 + 整片 libx264 重跑 + 回执写明原因」的可见降级链。

### 4.4 设置与回执

- `settings.export.encoder` 选项：
  `自动（推荐）` / `NVIDIA GPU（NVENC）` / `AMD GPU（AMF）` / `Intel 核显（QSV）` / `纯 CPU（libx264）`。
- 帮助文案：
  `自动=按平台真试编选择硬编（NVENC / AMF / QSV / VideoToolbox），全不可用才 libx264；固定编码器不探测，失败会按段级回退并在回执中写明`。
- `_compute_requested` 已把任何非 auto/cpu 值映射为 `cuda`，AMF 无需改；`compute.py` 模块注释里的示例编码器清单补 `amf`。
- `video.encode` 回执的 `actual` 允许 `h264_amf`；`resolved` 记录首轮选中编码器，`actual` 记录最终成片编码器。

---

## 5. 验真脚本（`scripts/verify_gpu_coverage.py`）

1. `_HW_ENCODERS` 增加 `"h264_amf"`；`judge_actual` 对 `video.*` 的 `requested="cuda"` 接受 NVENC/AMF/QSV/VideoToolbox。
2. 删除 `_nvenc_probe()` 的硬编码，改为：
   - `_select_hw_encoder() -> str`：按 `encoder._hw_candidates()` 的顺序逐个跑 `encoder._hw_probe_args(codec)`（30s 超时），返回第一个成功者；全失败抛 `Unsupported`，reason 列出每个候选的失败原文（截断）。
   - 候选序与参数**必须读 encoder 的同一处函数**，脚本不另写表。
3. `_video_encode_cuda` / `_video_ai_label_cuda`：先选编码器，再用该编码器跑真实 1s 段编码；返回实际 codec 作为 `actual`。
   - 组件名保持 `video.encode.cuda` / `video.ai_label.cuda` 不变（发布门禁的既有键）。
   - 对 `video.*`，`requested="cuda"` 的语义是「请求硬件编码」；`actual` 说出到底是 NVENC、AMF 还是 QSV。
4. `_environment()` 增加 `host_gpu`：调用 `gpu.detect()` 记录 vendor/name/driver/adapters（不含用户素材路径），让验收 JSON 自带宿主事实。
5. 记录纪律不变：`pass` 必须有实际编码器证据；`unsupported` 必须写原因；`unknown ≠ ok`，`unsupported ≠ pass`。

---

## 6. 界面事实（桌面端）

原则：**分支只读宿主事实（`gpu_info.vendor`），绝不解析后端文案。**

### 6.1 协议与机器数据

- `protocol/ts/index.ts`：
  - 新增 `export type GpuVendor = 'nvidia' | 'amd' | 'intel' | 'other' | 'none' | 'unknown';`
  - 新增 `GpuAdapter { name; vendor: GpuVendor; driver_version }`；
  - `GpuInfo` 增加 `readonly adapters?: readonly GpuAdapter[]`（可选，兼容旧服务）。
- `desktop/src/features/engines/machineFit.ts`：
  - `MachineSpecs` 增加可选的 `gpu?: GpuInfo` 与 `caps?: DeviceCaps`（`health.device_profile.caps` 原样带下）；
  - `specsFromHealth()` 把两者一并带下，供 ASR/TTS 设备选项与说明使用。

### 6.2 设备选项（ASR / TTS 共用）

新增 `desktop/src/features/engines/deviceOptions.ts`，两 tab 共用同一逻辑。判据不是 vendor，而是后端已经算好的 caps（§3.6）：

- 选项可用性读所选引擎对应 cap 的 **`ready`**（现在就能用）——`cuda` 是承诺，界面只提供会被 resolve 接受的值。引擎 → cap 的映射只写在 `deviceOptions.ts` 这一处：ASR 为 `faster_whisper_gpu`（faster_whisper）/ `funasr_gpu`（sensevoice、paraformer）；TTS 为 `indextts2_gpu`（indextts2、cosyvoice）。
- `caps` 缺失或 `machine.gpu` 未就绪（探测中）→ 保留 CUDA 选项，不做假阴性。
- `cap.ready === false` → 只给「自动 / CPU」，并展示 `cap.reason`：`ok === false` 表示算力不满足该栈下限（永久，如 GTX 10 上的 torch 栈）；`ok === true` 表示只是运行时未装（装上后 health 刷新即出现 CUDA）。**不能只看 vendor**：N 卡也可能不支持某条栈（§3.5 的下限表）。
- 若已保存的 `asr.device` / `tts.device` 是 `cuda`，仍展示该项但 `disabled`，标签为 `CUDA（{cap.reason || '本机不可用'}）`，让陈旧设置可见、可改走，而不是静默吞掉或渲染成空白。
- 模块级 `PARAMS` 里的静态设备选项改为组件内按 machine + 引擎选择生成；其余参数不变。
- 该选项只管 ASR / TTS 两条栈，**不管理人声分离**（§3.5）：`tts.clean_reference`、`tts.auto_voice` 与导出预检的自动提取（`api/export.py::_ensure_clone_voice`）三处调用一律传 `auto`，不再读 `tts.device`。

### 6.3 文案矩阵

| 位置 | 宿主 | 文案 |
|---|---|---|
| `GpuCard.statusOf` | 非就绪 | `检测中…`（不变） |
| | NVIDIA | 现有两句（不变） |
| | amd / intel / other | `未检测到 NVIDIA 显卡 · 转写将以 CPU 运行` |
| | none | `未检测到独立显卡 · 转写将以 CPU 运行` |
| `GpuCard.metaOf` | NVIDIA | 现有型号/驱动/CUDA 上限（不变） |
| | amd | `{name} · 驱动 {driver} · 视频导出可用 AMD 硬件编码（AMF，导出时真试编）` |
| | intel | `{name} · 驱动 {driver} · 视频导出可用 Intel 硬件编码（QSV，导出时真试编）` |
| | other | `{name} · 驱动 {driver} · 视频导出将真试编可用的硬件编码器` |
| | none | `ASR/TTS 加速需要 NVIDIA CUDA；视频导出将真试编，全不可用回退 libx264` |
| `StatusBar.gpuLabel` | 未就绪 | `待检测`（不变） |
| | NVIDIA | 现有「型号 · 驱动」 |
| | amd / intel / other | `{name} · 驱动 {driver || 未知}` |
| | none | `未检测到独立显卡 · CPU 模式` |
| `MachinePanel` 显卡格 | ready + NVIDIA | 现有型号/显存/CUDA |
| | ready + 非 NVIDIA 且有 name | `{name} · 驱动 {driver}` |
| | ready + none | `未检测到独立显卡 · 走 CPU` |
| | 未 ready | `显卡待检测…`（不再冒充「未检测到 NVIDIA」） |
| `MachinePanel` CUDA 行 | installed + NVIDIA | `已安装 · 转写可走 GPU 加速`（不变） |
| | installed + amd/intel/other | `已安装 · 本机无 NVIDIA 显卡，不会启用` |
| | installed + none | `已安装 · 未检测到独立显卡，不会启用` |
| | installed + unknown | `已安装 · 显卡状态探测中` |
| | 未装 + NVIDIA | 现有「未安装 · 转写走 CPU，可在本页…下载」 |
| | 未装 + amd/intel/other | `未安装 · 转写加速需要 NVIDIA CUDA，无需安装，当前走 CPU` |
| | 未装 + none | `未安装 · 未检测到独立显卡，无需安装，转写走 CPU` |
| | 未装 + unknown | `未安装 · 显卡状态探测中，暂按 CPU 运行` |
| `MachinePanel` 判定尾句 | 可行 | `；本地引擎均为 CPU 可跑，视频导出会真试编选择硬件编码器（NVENC / AMF / QSV）` |

- `useGpuInfo.ts::gpuSummary` 当前无调用方：删除，避免第三份 GPU 文案真相源。
- `GpuCard` 的 CUDA 运行库下载行仍只在 `vendor === 'nvidia'` 时出现（不变）。

### 6.4 人声分离提示

`TtsTab.tsx::SeparationBackendNote`：

- 删除 `ortGpu.reason.includes('未检测到 NVIDIA')` 这一文案解析。
- 改为读宿主事实：`hostMayHaveCuda = machine.gpu === undefined || !machine.gpu.ready || machine.gpu.vendor === 'nvidia' || machine.gpu.vendor === 'unknown'`。
- `retry = ortGpu === null || (!ortGpu.gpu && hostMayHaveCuda)`：非 NVIDIA 主机不再显示无意义的「重跑安装」；NVIDIA 主机缺 GPU 后端时仍显示。
- 后端 `tts_runtime.ort_state` 的 reason 原样展示，不再被当作控制流。
- 本格与 §6.2 的设备选项**互不干涉**：设备选项按厂商隐藏 CUDA 时，人声分离仍按 `ort_state` 的实际后端走（宿主是 NVIDIA 但 ORT 是 CPU 轮 → 分离走 CPU 并显示原因 + 「重跑安装」；宿主非 NVIDIA → 显示「仅支持 NVIDIA CUDA，当前走 CPU」，不显示重跑）。
- 每次清洗的成功回执要把「本次实际：GPU / CPU（原因）」留在返回值里并入库（§3.5 降级链修正的配套），不能只进 toast 与通知流。

### 6.5 设置页

`desktop/src/features/settings/sections.ts` 的 `export.encoder` 选项与帮助文案按 §4.4 更新。

---

## 7. 测试

### 7.1 后端

| 文件 | 覆盖 |
|---|---|
| `service/tests/infra/test_gpu_multi_vendor.py`（新增） | CIM 单对象/数组/缺字段/非法 JSON；虚拟设备过滤；NVIDIA/AMD/Intel/other 分类；主适配器优先级；smi 覆盖 CIM 的 NVIDIA 字段；CIM-only NVIDIA（无 smi）→ CUDA 三项为空；CIM 失败 + smi 成功；两者皆无 → none；非 win32 不调用 CIM |
| `service/tests/infra/test_device_profile_multi_vendor.py`（新增） | amd/intel/other/none/unknown 的标签、推荐、五项 cap 提示；NVIDIA 驱动不可读 vs 驱动过旧的两个分支；显存 0 → tier none；`tier_of` 非 N 卡恒 none；`indextts2_gpu.ok` 的 sm_70 下限与 `ready` 随 torch 变体变化；`funasr_gpu` 不设静态下限（ready 由探测决定）；每个 cap 都有 `reason` 字段 |
| `service/tests/infra/test_device_resolve.py`（新增） | 组件 → cap 映射完整；`cuda` 在 cap 未 ready 时抛 `ComputeUnavailableError` 且不构造引擎；`cpu` 恒 CPU；`auto` 按 ready 选路并带 reason，`downgraded` 只在 ok≠ready 时为真；待定快照返回 `device="auto"` 而不是 cpu；回执 `actual` 不由 resolve 伪造 |
| `service/tests/engines/test_device_resolve_wiring.py`（新增） | `_build_transcriber`（三种本地引擎）与 `tts.factory.create`（indextts2/cosyvoice）传下去的是解析后的设备；显式 `cuda` 不可用时在构造前失败 |
| `service/tests/engines/exporter/test_hw_probe.py` | win32 候选序含 AMF；AMF 参数与正式段编码同形状；NVENC 失败后 AMF 命中；全部失败缓存；`"h264_amf" in encoder._HW_ENCODERS` 与 `_fallback_eligible(...)`（AMF 段为真，同段换 `libx264` 为假） |
| `service/tests/test_verify_gpu_coverage.py` | `judge_actual` 接受 AMF；`_select_hw_encoder` 按候选序回落并在全失败时给逐项原因；`_HW_ENCODERS` 含 AMF |
| `service/tests/infra/test_gpu_and_fallback.py` | `test_detect_reports_cpu_when_smi_missing` 必须同时桩掉 CIM 源（否则 Windows 本机会真的枚举到 N 卡）；`_PENDING_FIELDS` / `detect` 的既有形状断言同步更新；不放宽任何生产断言 |
| `service/tests/api/test_tts_clean_reference.py` | 设备解耦：`tts.device` 设为 `cuda` / `cpu` 时，分离请求都是 `auto`；成功时建 `voice_clean` 任务行且 `jobs.compute` 非空、component 为 `tts.separation`；`mode=fast` 写 `tts.reference_clean.filter` 且 reason 说明用户选择；失败任务行置 failed 且 error 带原因；不静默换模式 |
| `service/tests/engines/tts/test_auto_voice_clean.py` | 降级链：CUDA 分离抛错 → CPU 分离成功 → `cleaned_with=separation` 且回执 `actual=cpu`；CPU 也失败才 `cleaned_with=filter` 且 `jobs.compute` 写 `tts.reference_clean.filter` 并带 `clean_reason`；自动提取不再继承 `tts.device` |
| `service/tests/api/test_export_voice_preflight.py` | `_ensure_clone_voice` 的清洗报告并入该导出的 compute 数组（与 `video.encode` 同账）；走滤镜时报告 component 为 `tts.reference_clean.filter` 且 reason 含失败原因；不再把 `tts.device` 传给分离 |

### 7.2 前端

| 文件 | 覆盖 |
|---|---|
| `desktop/src/features/engines/__tests__/deviceOptions.test.ts`（新增） | 引擎 → cap 映射；`cap.ready=false` 隐藏 CUDA 并展示 reason（N 卡低算力与 AMD 同样处理）；`ok=false`（永久下限）与 `ok=true, ready=false`（未装运行时）都隐藏 CUDA、reason 来源正确；caps/机器未就绪时保留 CUDA；已存 cuda 时为 disabled 选项且标签带 reason |
| `desktop/src/features/engines/__tests__/MachinePanelEnv.test.tsx` | NVIDIA 既有断言不变；把「无 GPU」夹具改成 `ready=true, vendor='none'` 并断言新文案；新增 AMD/Intel 的 CUDA 行、显卡格与尾句断言；`indextts2_gpu` 改读 `cap.ready` 后既有 ttsReady 组合断言同步 |
| `desktop/src/features/jobs/__tests__/jobMeta.test.ts` | `voice_clean` 标签为「参考清洗」、路由到 `/engines`、主体为产物文件名（不显示裸 id） |
| `desktop/src/features/engines/__tests__/GpuCard.test.tsx`（新增） | NVIDIA 文案/下载行不变；AMD 与 none 的 status/meta；下载行只在 NVIDIA 出现 |
| `desktop/src/components/layout/__tests__/StatusBar.test.tsx`（新增） | nvidia/amd/none/未就绪 四种 GPU 文案 |
| `desktop/src/features/settings/__tests__/sections.test.ts` | `export.encoder` 选项含 `h264_amf`/`h264_qsv`，帮助文案含 AMF |

不新增「只为覆盖率」的测试；每个用例都要能在对应生产代码改错时失败。

---

## 8. 真机验收

### 8.1 开发机（回归基准，必须全跑，不作任何厂商判据）

这台机器的算力档（sm_52）、双卡枚举顺序、GameViewer 虚拟显示适配器都不是设计前提；在本机跑通只证明「没把 NVIDIA 路径改坏」，不证明多厂商可用，也不据本机结果调算力下限。

```bash
cd service && ../.venv/Scripts/python.exe -m pytest
cd service && ../.venv/Scripts/python.exe -m ruff check dramaclip tests
cd desktop && npm run typecheck && npm test
service/.venv/Scripts/python.exe scripts/verify_gpu_coverage.py
service/.venv/Scripts/python.exe scripts/verify_gpu_coverage.py --require video.encode.cuda=pass --require video.ai_label.cuda=pass
```

判定：

- 后端/前端全绿；lint 只允许既有历史 `I001`（若仍在）。
- `video.encode.cuda` / `video.ai_label.cuda` 仍为 `actual=h264_nvenc` 且 `pass`；新增 AMF 候选不改变本机选择。
- 其余 14 项与 P3 记录同口径：`unsupported` 不计通过，`unknown` 判失败。
- `host_gpu` 出现在验收 JSON 中，`vendor="nvidia"`，`adapters` 至少一条 NVIDIA。

### 8.2 外部回执清单（按主流机型类别，未回执不得写「已通过」）

| 主机 | 必查 |
|---|---|
| NVIDIA 主流独显（RTX 20/30/40，当前驱动） | `gpu_info.vendor=nvidia`；CUDA 四项 `pass`；`tts.device` 有 CUDA 且 IndexTTS2 合成 `actual=cuda`；人声分离 `actual=cuda`；`video.encode.cuda=pass` 且 `actual=h264_nvenc` |
| **NVIDIA 存量卡（算力 <7.0：GTX 10 系、Maxwell/Pascal）** | **§3.5/§3.6 的主验收**：torch 只能 CPU（`tts.device` 设 auto 时合成回执 `actual=cpu` 且不报错，设 cuda 时在拉起 worker 前报「算力低于 sm_70」），而人声分离仍 `actual=cuda`；ASR 按 `ctranslate2` 下限实测（sm_61 段可 `actual=cuda`，更低则 CPU 且回执写明）；TTS 页不出现 CUDA 选项（`indextts2_gpu.ok=false` 且展示 reason），ASR 页按引擎分别显示（CUDA 运行库已装时 faster_whisper 可选；sensevoice/paraformer 因 torch 低于 sm_70 不可选）；界面不得因为「TTS 走 CPU」就把分离也显示成 CPU；手动清洗产生 `voice_clean` 任务行且 `jobs.compute` 有回执 |
| AMD 独显（RX 6000/7000，Windows 10/11，当前 Adrenalin） | `gpu_info.vendor=amd` 且 `adapters` 含 AMD；ASR/TTS 无 CUDA 选项、auto 回执 `actual=cpu`；`verify_gpu_coverage.py --require video.encode.cuda=pass` 得 `actual=h264_amf`；成片 ffprobe 为 h264、时长正确、抽帧无花屏；人声分离回执 CPU 且提示「仅支持 NVIDIA CUDA」 |
| Intel 核显（11 代及以上，当前核显驱动） | `video.encode.cuda=pass` 且 `actual=h264_qsv`；ASR/TTS CPU 回执；其余同上 |
| AMD 独显 + Intel 核显笔记本 | 自动选择先 AMF；AMF 失败时回落 QSV；不得落 libx264（除非两者真试编都失败） |
| 无独显 / Microsoft Basic Display | `vendor=none`；导出自动落 libx264 且回执可见；界面不劝装 CUDA 运行库 |

回执内容：`verify_gpu_coverage.py` 的 JSON、`gpu_info` 快照、成片 ffprobe 输出、界面截图（设备选项与 GPU 格）。回执回来前，文档只能写「路径已实现，待真机回执」。

---

## 9. 不在本批（另行立规格）

1. **macOS 平台落地**：CI mac runner、PyInstaller 路径、mac ffmpeg 资产、VideoToolbox 真试编、TTS/ASR 的 CPU 回执、`.app` 打包与签名。本批只保留 `darwin` 现有候选，不改。
2. **DirectML / CoreML**：**不做**（2026-10-20 业主定则：AI 引擎 GPU 加速只支持 NVIDIA CUDA）。
   - `audio-separator` 官方支持 `dml` extra，ONNX Runtime DirectML EP 要求 Windows 10 1903+ / DX12，覆盖 NVIDIA/AMD/Intel，但会关闭内存模式与并行优化；
   - 开发机上确有 Radeon RX 5500 XT，但按机型基准它不作 AMD 判据；业主已裁决 CUDA-only，故不接、不写死版本；
   - 若未来重新评估，前提是：有 AMD 真机 + 人声分离 CER/耗时对照回执 + ORT DML 与本项目 cu12 运行库共存方案通过隔离试验。届时须重新裁决，不得默认翻案。
3. **Linux 打包/加速**：不支持。
4. **非 NVIDIA 的 AI 推理加速**（CUDA-on-AMD 兼容层等）：不尝试。
5. **AMF/QSV 画质调参竞赛**：本批只做与现有硬编对齐的固定参数；画质评估另立。
6. **人声分离的其余修正**（与厂商无关，另开小批）：产物 `<stem>.cleaned.wav` 的模式/次数去重（现会叠成 `.cleaned.cleaned.wav`，滤镜与分离互相覆盖）；`ensure_model` 对已在盘文件补字节数校验、下载补 SHA256（`fetch.download_file` 已支持，只是没传）；同步清洗与运行环境安装作业之间加互斥（`_install_ort` 会卸载正被 worker 占用的 ORT）。
7. **统一 worker 执行层（方案丙的后半）**：人声分离 worker、TTS workers、安装期 ORT 探针现在各写一份「venv 解析 → CUDA DLL 注入 → 超时 → 单行 JSON 协议 → 回执归一」。本批只统一**解析入口与回执账本**（§3.6），不动进程层；下一步再收成一层 `worker_runner`，顺带补上全量审计里的「worker 桥无超时」。分开的理由：它触及并发与安装互斥，需要独立回归。
8. **参考音频清洗的长期档案**：若要跨「清空已完成」保留 provenance，或把参考音频做成实体库，再迁 `voice_cleaning` 表；本批回执随任务行走（§3.5），不建表。

---

## 10. 风险与约束

| 风险 | 处置 |
|---|---|
| AMF 驱动版本差异大，参数可能不被识别 | 真试编用**与正式段编码同形状**的参数；失败即换下一候选，绝不静默产出坏片 |
| PowerShell 被策略禁用/CIM 超时 | 10s 超时 + 吞异常；nvidia-smi 仍可识别 N 卡；非 N 卡退化为 `none`，不阻塞服务启动 |
| CIM 名称本地化/异常字符 | 名称只作展示与分类数据；UTF-8 输出 + `errors="replace"`；分类失败归 `other` |
| 非 N 卡用户被文案误导 | 分支只读 vendor；设备选项、GPU 卡、总览、状态栏四处统一按 §6.3 |
| 三套运行时算力下限不同，一个开关必然错配 | §3.5：`tts.device` 只管 torch，人声分离恒按 `auto` 起步并如实回执；§3.6 把三套栈收口到同一解析入口与能力表；该组合由 §8.2「NVIDIA 存量卡」行的回执判定 |
| 解析依赖的探测尚未就绪（服务刚启动几秒内） | §3.6：待定态返回 `device="auto"` 交给引擎自判，绝不据此判 CPU；不加阻塞等待 |
| 能力表与运行证据各说各话 | §3.6：caps 只决定「预期设备」，回执 `actual` 一律来自 worker/引擎证据；`unknown ≠ ok` 由 `compute.assert_success` 兜底 |
| 旧服务不返回 `adapters` | TS 字段可选；UI 不依赖 adapters，只用 vendor/name |
| 显存/驱动读不到被写成「太旧」 | §3.3 三分支；`driver_unknown` 不冒充 `driver_old` |
| 外部无 AMD/Intel 回执 | 只写「路径已实现，待回执」；验真脚本在那些机器上若 `unsupported`，不得算通过 |

**约束**：不新增依赖；不改打包与 CI；不合并/重写 `docs/05-开发路线图.md`；不提交任何后端源码分发物；提交只按明确路径，禁止广域 `git add`；`unsupported ≠ pass`，`unknown ≠ ok`。

---

## 11. 涉及文件

**后端**
- `service/dramaclip/infra/gpu.py`（CIM + 合并 + 纯函数切分）
- `service/dramaclip/infra/device_profile.py`（厂商标签/推荐/提示/驱动三分支；torch 下限、`ready` 真结论、`reason`、`torch_variant` 入参）
- `service/dramaclip/api/system.py`（health 传 `torch_variant`）
- `service/dramaclip/infra/device_resolve.py`（新增：唯一解析入口）
- `service/dramaclip/engines/analysis/runtime.py`、`service/dramaclip/engines/tts/factory.py`（构造前调 resolve）
- `service/dramaclip/api/engines.py`（自检直连也走 resolve）
- `service/dramaclip/engines/exporter/encoder.py`（AMF 候选与参数、`_HW_ENCODERS`）
- `service/dramaclip/infra/compute.py`（仅模块注释补 `amf`，无行为改动）
- `service/dramaclip/api/tts.py`、`service/dramaclip/api/export.py`、`service/dramaclip/engines/tts/auto_voice.py`、`service/dramaclip/engines/tts/vocal_separation.py`（§3.5：分离设备恒 auto、降级链补 CPU 一档、回执落 `jobs.compute`/`export_jobs.compute`、`voice_clean` 任务行）
- `scripts/verify_gpu_coverage.py`（多厂商选择、AMF 判定、host_gpu 记录）

**前端/协议**
- `protocol/schemas/tts.json`（`tts.clean_reference` / `tts.extract_reference` 结果补 `job_id`，`compute` 描述改为按 mode 分账）
- `protocol/ts/index.ts`（`GpuVendor` / `GpuAdapter` / `adapters`；`DeviceCaps` 类型）
- `desktop/src/features/engines/machineFit.ts`（`MachineSpecs.gpu` / `caps`）
- `desktop/src/features/engines/deviceOptions.ts`（新增，含引擎 → cap 的唯一映射）
- `desktop/src/features/engines/AsrTab.tsx`、`TtsTab.tsx`
- `desktop/src/features/engines/GpuCard.tsx`
- `desktop/src/features/engines/MachinePanel.tsx`
- `desktop/src/features/engines/useGpuInfo.ts`（删除未用 `gpuSummary`）
- `desktop/src/components/layout/StatusBar.tsx`
- `desktop/src/features/jobs/jobMeta.ts`（`voice_clean` 标签与路由）
- `desktop/src/features/settings/sections.ts`

**测试**
- `service/tests/infra/test_gpu_multi_vendor.py`（新增）
- `service/tests/infra/test_device_profile_multi_vendor.py`（新增）
- `service/tests/infra/test_device_resolve.py`（新增）
- `service/tests/engines/test_device_resolve_wiring.py`（新增）
- `service/tests/api/test_tts_clean_reference.py`
- `service/tests/engines/tts/test_auto_voice_clean.py`
- `service/tests/api/test_export_voice_preflight.py`
- `service/tests/engines/exporter/test_hw_probe.py`
- `service/tests/test_verify_gpu_coverage.py`
- `service/tests/infra/test_gpu_and_fallback.py`（仅形状适配）
- `desktop/src/features/engines/__tests__/deviceOptions.test.ts`（新增）
- `desktop/src/features/engines/__tests__/MachinePanelEnv.test.tsx`
- `desktop/src/features/engines/__tests__/GpuCard.test.tsx`（新增）
- `desktop/src/components/layout/__tests__/StatusBar.test.tsx`（新增）
- `desktop/src/features/jobs/__tests__/jobMeta.test.ts`
- `desktop/src/features/settings/__tests__/sections.test.ts`

---

## 12. 验收清单

- [ ] Windows 宿主探测能列出多个适配器，主适配器优先级正确；CIM 失败不阻塞服务。
- [ ] AMD/Intel 主机不再显示「未检测到 NVIDIA 显卡」/「无独立显卡」；NVIDIA 主机文案与行为不变。
- [ ] 自动导出在 AMD 上真试编 AMF、Intel 上真试编 QSV；全失败回 libx264 且回执可见。
- [ ] 设备选项按 caps 而非 vendor（§6.2）：非 NVIDIA 主机无 CUDA；NVIDIA 低算力卡的 TTS/本地 ASR 无 CUDA 并展示 `reason`，faster_whisper 在 sm_61+ 且运行时已装时仍可选；保存过 CUDA 的旧设置以 disabled 项显式呈现。
- [ ] 人声分离非 NVIDIA 提示「仅支持 CUDA」，不再出现无意义的重跑安装按钮。
- [ ] §3.5 解耦生效：`tts.device` 设成 `cuda`/`cpu` 都不改变分离请求（恒 `auto`）；分离失败链是 CUDA → CPU → 滤镜，不再一步跳到滤镜。
- [ ] §3.6 解析入口生效：引擎侧不再各自读 `asr.device`/`tts.device` 决定设备；显式 `cuda` 在拉起模型/worker 前按 caps 报清晰原因；待定快照不落 CPU。
- [ ] 清洗回执入账：手动清洗/自动提取产生 `voice_clean` 任务行且 `jobs.compute` 非空；导出预检的清洗报告出现在该导出的 compute 数组里；滤镜兜底以 `tts.reference_clean.filter` 可辨；不再写 `tts.voice.receipt`。
- [ ] 验真脚本不再写死 NVENC，`video.*` 的 `actual` 能报 AMF/QSV；`unsupported`/`unknown` 纪律不变。
- [ ] 开发机全量测试、lint、前端测试通过（回归基准）；16 项验真与 P3 同口径，NVENC 仍为实际编码器。
- [ ] AMD/Intel/存量 N 卡外部回执未回来前，任何文档不写「已通过」。
