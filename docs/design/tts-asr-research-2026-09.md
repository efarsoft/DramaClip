# TTS / ASR 模型调研（2026-09-19）—— 适用性评估

> 筛选锚：①中文短剧场景 ②本地优先、**许可可商用**（CPS 业务）③本机硬件弱 GPU
> （M4000 Pascal / torch 可用 / 无 cuDNN 加成）④与现有管线衔接（OCR×ASR 融合要时间戳；
> 解说配音要情感与时间轴）。

---

## 一、TTS 结论

### 现役组合维持（轻量本地档已是最优）
| 引擎 | 定位 | 事实依据 |
|---|---|---|
| **Kokoro 82M** | 轻量本地主力 | 效率冠军：GPU RTF≈0.03，CPU 舒适超实时；100 中文音色已全量接入 |
| **sherpa melo** | CPU 实时备胎 | CPU 实时中文、部署最简 |
| **Edge（云端）** | 免费在线 | 14 中文音色已全量；注意高频限流 |

对比过的新轻量候选均**不换**：KittenTTS（中文支持弱）、Piper（中文音质机械）、MeloTTS（与已接入的 melo 同源）。现有 Kokoro+melo 就是 CPU 中文档的头部组合。

### IndexTTS2：许可标注为 informational，接入候选保留
- **IndexTTS2 采用 B 站自定义模型协议：非商用，商用需单独授权**（此前记录的 Apache 2.0 是 IndexTTS 1.x 的）。
- **业主裁决（2026-09-19）：本项目用途按常规视频剪辑对待，许可作为说明信息标注，不构成接入障碍。**
- 技术上独一份（精确时长控制+音色情感解耦），接入优先级回升：与 Fun-CosyVoice3 并列为储备接入的前两位——
  IndexTTS2 胜在时长控制（解说时间轴对齐的根治方案），CosyVoice3 胜在协议完全无虞+方言广度。

### 新增储备第一优先：Fun-CosyVoice3-0.5B（阿里，Apache 2.0）✅ 已核实（2026-09-20）
- **真实仓库：`FunAudioLLM/Fun-CosyVoice3-0.5B-2512`**（ModelScope 下载 30.8 万 / HF 30 天 18.7 万；
  此前查的 iic/* 与 FunAudioLLM/CosyVoice3-0.5B 均为 404，本次经 README 链接定位）
- **HF API license tag = apache-2.0，商用无忧**
- 9 语言 + 18+ 中文方言零样本克隆（3 秒参考音频）、内容一致性/说话人相似度/韵律自然度全面超 2.0
- 模型构成（ModelScope 文件清单实测，总量 9.08GB，必装子集约 **5.6GB**）：
  llm.pt 1.9G（另有 RL 强化版 llm.rl.pt 1.9G 可不装）+ flow.pt 1.27G + speech_tokenizer_v3 0.9G
  + CosyVoice-BlankEN 分词器 0.94G + hift 79M + campplus 27M + 配置
- **推理方式：git clone FunAudioLLM/CosyVoice 官方仓库 + 模型目录加载**（无 pip 包，
  requirements 较重：sox/ttsfrd 等，Windows 需验证 sox 依赖；文本规范化有 wetext 纯 py 兜底）
- 附带：同批开源 Fun-ASR-Nano（轻量 ASR），纳入 ASR 观察名单

### VibeVoice-1.5B（已下 5GB，MIT）
- 多角色（4 人）对话合成 → 只服务「双人对谈」模式的升级；推理较重需 GPU，维持储备观察。

### 扩充核实（2026-09-20 第二轮：头部模型逐一过 API）

| 模型 | 仓库实测 | 许可（HF API） | 体积 | 亮点 | 裁决 |
|---|---|---|---|---|---|
| **VoxCPM2**（OpenBMB） | ✓ 34.4万下载（MS）/ HF 38万/月、1630 赞 | **apache-2.0** | 4.62GB | 2B 参数、tokenizer-free 扩散自回归、**48kHz 录音室级音质**、30 语言、零样本克隆、上下文感知 | **🥇 新增高音质首选**：热度与许可双优，48kHz 输出是全榜独一档 |
| IndexTTS-2.5 | ✓ 2.5万下载（MS） | other（B 站协议，informational） | 5.11GB | 时长控制+情感解耦+RTF 2.28×提速 | 已有 2 于盘，2.5 升级收益中庸，先不重复下载 |
| CosyVoice2-0.5B | ✓ 192.6万下载（MS） | apache-2.0 | 5.23GB | 上一代旗舰 | 被 CosyVoice3 全面替代，跳过 |
| VoxCPM-0.5B | ✓ | — | 1.5GB | 轻量版 | CPU 可能可行，作 VoxCPM2 跑分不佳的备胎 |
| fish-speech-1.5 | ✓ | CC-BY-NC（不可商用） | ~4GB | — | 排除（业主 informational 裁决也救不了：质量不构成独占价值） |
| F5-TTS / Spark-TTS / MOSS-TTSD / Kimi-TTS | ✗ 不在 ModelScope | — | — | — | HF 侧再核（国内下载需镜像，暂缓） |

**结论修订：TTS 接入序列 = CosyVoice3（已核实启动）→ VoxCPM2（高音质档）**，两者许可均 apache-2.0、热度可信、仓库直连国内 CDN。

---

## 二、ASR 结论

### 主力维持：faster-whisper（int8 CPU）
word 级时间戳 + 热词 prompt + int8 CPU 已与融合管线深度耦合；中文精度虽非最高，但 OCR 融合（60% 段落 OCR 校对）补齐了精度短板。

### 候选评估
| 模型 | 亮点 | 对本项目硬伤 | 裁决 |
|---|---|---|---|
| **FireRedASR-AED-L**（小红书，1.1B/3.37GB） | 中文 CER 3.18%（LLM 版 2.89%）开源最强；方言好 | **无原生时间戳**（融合管线硬依赖）；LLM 版 21GB 不可行；CPU 慢 | 观望，等 FireRedASR2S（一体化时间戳）成熟 |
| **Qwen3-ASR-0.6B/1.7B**（2026-01 开源） | 22 方言；配套 Qwen3-ForcedAligner 字级对齐；0.6B 轻 | 字级时间戳有已知 bug（issue #55）；许可证需逐一核（Qwen 系通常 Apache） | **Spike 值得做**：0.6B 体积小、方言覆盖对短剧语料有真实价值 |
| **Paraformer-large**（已在 registry） | SeACo **原生热词**+长音频时间戳+部署成熟 | 精度逊 FireRed | 保留现状；热词增强通道 |
| **SenseVoice**（已接入） | 快 + 独有情感标签 | 无热词 | 保留（情感标签供字幕情绪匹配） |

---

## 三、行动清单（按性价比）

1. **registry 许可标注**（0.5h）：IndexTTS2 标「非商用·B 站协议」、VibeVoice 标 MIT、CosyVoice 系标 Apache——引擎中心诚实性原则
2. **引擎接入排队**（P-2）：Fun-CosyVoice3-0.5B 与 IndexTTS2 并列首位（前者协议稳妥、后者时长控制独门）
3. **Qwen3-ASR-0.6B spike**（1 天）：许可证核实 → 中文短剧样片 CER 对比 whisper-small → 时间戳质量评估（融合兼容性）
4. FireRedASR2S / IndexTTS-2.5 挂观察名单，季度复查

## 附：来源
- [IndexTTS GitHub（含 2.5 与许可说明）](https://github.com/index-tts/index-tts) / [IndexTTS2 推理性能分析](https://gitcode.csdn.net)
- [CosyVoice3 与 ASR-Nano 开源（知乎）](https://zhuanlan.zhihu.com) / [CosyVoice2 方言情感实测（CSDN）](https://blog.csdn.net)
- [FireRedASR 论文 arXiv 2501.14350](https://arxiv.org/abs/2501.14350) / [FireRedASR 模型卡](https://huggingface.co/FireRedTeam/FireRedASR-AED-L)
- [Qwen3-ASR GitHub](https://github.com/QwenLM/Qwen3-ASR)
- [CPU TTS 对比（KittenTTS issue）](https://github.com/KittenML/KittenTTS/issues/40) / [Picovoice 端侧 TTS 基准](https://picovoice.ai)
