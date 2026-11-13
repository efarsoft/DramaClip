# 模型商用许可登记（audio.cpp 迁移前置）

- 目的：audio.cpp 迁移的第一步前置——逐模型商用许可核对，NC/受限许可不挂架（红线）。
- 核对口径：以上游官方发布页（HuggingFace/ModelScope/GitHub）的许可标注为准；GGUF 转换件继承上游模型许可。
- 核对日期：2026-11-13（首核）。状态：✅ 已核可挂架 / ⚠️ 受限待决 / ❓ 待复核。
- 维护纪律：新增挂架模型必须先在本表登记许可结论；上游改许可 = 重新核对。

## 批1 入册清单（audio.cpp 首批，全部可挂架 ✅）

| 模型 | 许可 | 商用 | 依据 |
|---|---|---|---|
| Qwen3-ASR（0.6B/1.7B） | Apache 2.0 | ✅ | 2026-01-28 官方开源发布（含 0.6B 档），[官方博客](https://qwen.ai/blog?id=qwen3asr) 声明三模型权重均以 Apache 2.0 开源；[GitHub](https://github.com/qwenlm/qwen3-asr) |
| Qwen3-ForcedAligner（0.6B） | Apache 2.0 | ✅ | 同上发布（词级时间戳对齐器，ASR 两段式的第二段） |
| Fun-ASR-Nano-2512 | Apache 2.0 | ✅ | [HF 模型卡](https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512) 元数据 license 标签；备选对照模型 |
| Kokoro-82M（GGUF） | Apache 2.0 | ✅ | [HF 模型卡](https://huggingface.co/hexgrad/Kokoro-82M) license: apache-2.0；官方声明欢迎商用部署 |

## 现役已分发模型（存量核对，含一条红线 ⚠️）

| 模型 | 许可 | 商用 | 结论与依据 |
|---|---|---|---|
| **IndexTTS-2.5**（现役重 TTS，registry=IndexTeam/IndexTTS-2.5） | **bilibili-model-license**（自定义协议，非开源许可） | ⚠️ **受限** | [HF 页](https://huggingface.co/IndexTeam/IndexTTS-2.5) license 标签 = bilibili-model-license；同族 [IndexTTS2 LICENSE](https://github.com/index-tts/index-tts/blob/main/LICENSE)：免费下载/自部署/非商业，**商用需向 indexspeech@bilibili.com 单独授权**，且禁用衍生模型竞品训练。**存量风险**：0.2.4 资产库已在架、用户已下载使用——非 audio.cpp 新增，需业主决策（见下） |
| demucs / HTDemucs（人声分离权重） | 代码 MIT；权重 ⚠️ | ⚠️ 待深核 | [demucs 仓库](https://github.com/facebookresearch/demucs) LICENSE=MIT；但预训练权重训于 MUSDB18（Zenodo 发布，研究条款），商用灰色（[行业讨论](https://www.audioshake.ai/post/can-demucs-be-used-commercially-musdb18-model-weights-licensing)）。存量已分发，同上待决 |

## 待复核（现役引擎，本轮未逐字核对）

| 模型 | 初判 | 备注 |
|---|---|---|
| CosyVoice / CosyVoice3（FunAudioLLM） | Apache 2.0（行业通识，[FunASR 仓库](https://github.com/modelscope/funasr)注明 toolkit MIT/模型各自许可） | **待逐字复核模型卡**；克隆能力在栈，是 D1 红线场景的现成替代 |
| SenseVoice-Small | 通识可商用 | 待逐字复核 |
| paraformer-large（iic） | 待复核 | FunASR 系模型许可不一，逐个过 |
| fsmn-vad / campplus（iic） | 待复核 | 同上 |

## 红线处置记录

- 2026-11-13：首核发现 IndexTTS-2.5（现役重 TTS）为受限许可——上报业主。影响面：①audio.cpp D1「IndexTTS2 主力」建议需重新权衡（替代=CosyVoice 系克隆，Apache 2.0 已在栈）；②存量 0.2.4 资产库在架状态需业主决策（申请商用授权 / 下架 / 标注知情使用）。**未处置前，audio.cpp 侧 IndexTTS-2.5 不重复挂架。**
