# selftest — 引擎能力层自检的随包样例

`sample_zh.wav`：`engines.selftest`（ASR 分支）真转写用的固定样例，16 kHz 单声道
PCM，约 14 秒 / 450 KB。

## 来历（诚实备案）

- 2026-09-22 在开发机上由 Windows SAPI（Microsoft Huihui Desktop，zh-CN）朗读
  本项目自撰文案合成：「欢迎使用短剧切片工具。这是一段用于引擎自检的样例音频，
  如果你能完整识别出这句话，说明本机的语音转写引擎工作正常。」
- 经随包 `resources/ffmpeg/ffmpeg.exe` 转成 16 kHz 单声道 pcm_s16le。
- 用本仓库 faster-whisper small（CPU/int8）实测：识别出 56 字、耗时 8.4 s——
  「文件在且能被真实引擎认出字」是量出来的，不是假设。

## 纪律

- 只进安装包、不进 `data/`；任何修复动作都不许碰它。
- 换样例必须重跑上面的实测并在本文件更新数字——样例认不出字，自检就成了假绿灯。
