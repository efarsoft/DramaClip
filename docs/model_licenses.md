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

## 现役已分发模型

| 模型 | 许可 | 定位 | 依据 |
|---|---|---|---|
| IndexTTS-2.5（现役重 TTS，registry=IndexTeam/IndexTTS-2.5） | bilibili-model-license（自定义协议） | **业主定位（2026-11-13）：DramaClip 为免费开源工具、非商用软件，模型使用落 NC 条款下的非商业使用**——不触发商用授权；红线降级为备注。若将来产品商业化（收费/商用分发），此处需重新评估（或向 indexspeech@bilibili.com 取得授权）。[HF 页](https://huggingface.co/IndexTeam/IndexTTS-2.5)；同族 [LICENSE](https://github.com/index-tts/index-tts/blob/main/LICENSE) |
| demucs / HTDemucs（人声分离权重） | 代码 MIT；权重训于 MUSDB18（研究条款） | 同上定位（非商业使用）；若商业化需深核权重条款。[demucs 仓库](https://github.com/facebookresearch/demucs) |

## 待复核（现役引擎，本轮未逐字核对）

| 模型 | 初判 | 备注 |
|---|---|---|
| CosyVoice / CosyVoice3（FunAudioLLM） | Apache 2.0（行业通识） | 待逐字复核模型卡 |
| SenseVoice-Small | 通识可商用 | 待逐字复核 |
| paraformer-large（iic） | 待复核 | FunASR 系模型许可不一，逐个过 |
| fsmn-vad / campplus（iic） | 待复核 | 同上 |

## 处置记录

- 2026-11-13：首核完成。IndexTTS-2.5 曾标「商用红线待决」，业主当日确认 DramaClip 定位为免费开源非商用工具（NC 条款不触发）——降级为备注，D1 维持 IndexTTS-2.5 主力不变。**触发重估条件：产品商业化（收费/商用分发/代运营服务）。**
- 备注：仓库暂无 LICENSE 文件（源码公开 ≠ 许可开源）；是否加开源许可由业主另行决定。
