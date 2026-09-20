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

### ⚠️ 储备策略反转：IndexTTS2 许可否决
- **IndexTTS2 采用 B 站自定义模型协议：非商用，商用需单独授权**（此前记录的 Apache 2.0 是 IndexTTS 1.x 的）。
- 对 CPS 商业场景=一票否决。已下载的 5.5GB 降级为「仅个人测试」，registry 需标注许可状态。
- 技术上仍是独一份（精确时长控制+音色情感解耦），若未来拿到授权或出 Apache 版再启用。

### 新增储备第一优先：Fun-CosyVoice3-0.5B（阿里，Apache 2.0）
- 9 语言 + **18 种以上中文方言**零样本克隆、**情感控制**（韵律/音质可控）——正中解说风格系统
- 0.5B 参数：显存压力小，M4000 torch 生态可试；Apache 2.0 商用无忧
- 行动：registry 登记真实仓库名（此前 iic/FunAudioLLM 404 待复核）→ 引擎接入排队 P-2 首位
- 附带：同批开源 Fun-ASR-Nano（轻量 ASR），纳入 ASR 观察名单

### VibeVoice-1.5B（已下 5GB，MIT）
- 多角色（4 人）对话合成 → 只服务「双人对谈」模式的升级；推理较重需 GPU，维持储备观察。

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
2. **Fun-CosyVoice3-0.5B 登记 + 引擎接入**（P-2 首位）：情感+方言+可商用，接替 IndexTTS2 的储备位
3. **Qwen3-ASR-0.6B spike**（1 天）：许可证核实 → 中文短剧样片 CER 对比 whisper-small → 时间戳质量评估（融合兼容性）
4. FireRedASR2S / IndexTTS-2.5 挂观察名单，季度复查

## 附：来源
- [IndexTTS GitHub（含 2.5 与许可说明）](https://github.com/index-tts/index-tts) / [IndexTTS2 推理性能分析](https://gitcode.csdn.net)
- [CosyVoice3 与 ASR-Nano 开源（知乎）](https://zhuanlan.zhihu.com) / [CosyVoice2 方言情感实测（CSDN）](https://blog.csdn.net)
- [FireRedASR 论文 arXiv 2501.14350](https://arxiv.org/abs/2501.14350) / [FireRedASR 模型卡](https://huggingface.co/FireRedTeam/FireRedASR-AED-L)
- [Qwen3-ASR GitHub](https://github.com/QwenLM/Qwen3-ASR)
- [CPU TTS 对比（KittenTTS issue）](https://github.com/KittenML/KittenTTS/issues/40) / [Picovoice 端侧 TTS 基准](https://picovoice.ai)
