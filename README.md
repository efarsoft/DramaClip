# DramaClip 短剧自动高光剪辑系统

> 一款专注于短剧自动高光剪辑的智能系统，采用**单系统双模式**设计，支持 1~N 集短剧一键生成竖屏高光成片。

---

## 核心特性

| 特性 | 说明 |
|------|------|
| **双模式剪辑** | 原片直剪模式（保留原声）+ AI 解说模式（生成旁白），一套系统自由切换 |
| **任意集数支持** | 1 集、3 集、5 集、6 集... 任意数量短剧均可处理 |
| **竖屏成片输出** | 自动裁剪为 9:16 竖屏，1080P，适配抖音/快手/视频号等短视频平台 |
| **高光智能识别** | 多维度打分（音频爆点 + 台词情绪 + 画面特征 + 镜头节奏），自动筛选精彩片段 |
| **智能排序** | 按剧集顺序 + 时间先后 + 情绪递进排序，确保成片剧情流畅、不跳戏 |
| **Web 界面** | 拖拽上传、进度可视化、历史记录，开箱即用 |

---

## 两种剪辑模式

### 模式一：原片直剪模式（保留原音）

- **核心目标**：保留原片质感，快速出片
- **音频处理**：保留原片全部音频（人声、BGM），自动音量均衡
- **字幕**：自动叠加 ASR 转写字幕，支持样式调整
- **处理速度**：单集 ≤ 30s，6 集 ≤ 2 分钟
- **适用场景**：名场面混剪、卡点视频

### 模式二：AI 解说模式（替换原音）

- **核心目标**：通过 AI 传递剧情核心
- **剧情解析**：AI 解析全剧台词与画面，提取冲突、反转、高潮节点
- **文案生成**：自动生成解说文案，支持常规解说/吐槽风/简洁风多种风格
- **TTS 合成**：自然语音旁白，支持音色、语速、情绪调节
- **双字幕**：解说字幕（居中）+ 原片台词字幕（底部），支持手动调整
- **处理速度**：单集 ≤ 1 分钟，6 集 ≤ 3 分钟
- **适用场景**：剧情解说、吐槽、几分钟看完一部剧

---

## 系统架构

```
DramaClip/
├── app/                      # 后端核心应用（Python）
│   ├── models/               # 数据模型（Pydantic schemas）
│   ├── services/            # 业务服务层
│   │   ├── task.py          # 任务管理服务
│   │   ├── video.py         # 视频处理服务（FFmpeg）
│   │   ├── audio.py         # 音频分析服务（Librosa）
│   │   ├── asr.py           # ASR 语音转写（Whisper）
│   │   ├── ai.py            # AI 文案生成（大模型）
│   │   └── tts.py           # TTS 语音合成
│   ├── api/                 # FastAPI 路由层
│   └── core/                # 核心配置与工具
├── webui/                   # Web 界面后端（Gradio）
├── SourceProjects/          # 源代码资源目录
│   ├── autoclip/            # 前端项目（React + TypeScript）
│   └── NarratoAI/           # AI 解说模块源码（参考来源）
├── docs/                    # 项目文档与资源
├── config.example.toml      # 配置文件模板
├── requirements.txt         # Python 依赖
├── webui.py                 # Web 界面启动入口
└── docker-compose.yml       # Docker 部署配置
```

### 模块说明

| 模块 | 说明 |
|------|------|
| `app/models` | 数据模型定义（Task、Video、Clip、Collection 等） |
| `app/services/task` | 任务状态管理、流程编排 |
| `app/services/video` | FFmpeg 视频转码、镜头分割（PySceneDetect）、竖屏裁剪 |
| `app/services/audio` | 音频分析（爆点检测、音量均衡） |
| `app/services/asr` | Whisper 语音转写，生成 SRT 字幕 |
| `app/services/ai` | 大模型剧情解析、文案生成 |
| `app/services/tts` | TTS 语音合成 |
| `webui/` | Gradio Web 界面，快速部署 |

---

## 技术栈

| 类别 | 技术 |
|------|------|
| **语言** | Python 3.8+ / TypeScript |
| **视频处理** | FFmpeg、OpenCV、PySceneDetect |
| **音频分析** | Librosa |
| **语音识别** | Whisper |
| **AI 文案** | OpenAI / 国产大模型 API |
| **TTS** | CosyVoice / 第三方 TTS API |
| **后端框架** | FastAPI、SQLAlchemy |
| **Web 界面** | Gradio / React + TypeScript |
| **部署** | Docker Compose |

---

## 环境要求

### 硬件

| 项目 | 最低要求 | 推荐配置 |
|------|----------|----------|
| CPU | Intel i5 及以上 | Intel i7 / AMD R5 及以上 |
| 内存 | 8 GB | 16 GB（AI 解说模式推荐） |
| 显卡 | — | NVIDIA GTX 1050 及以上（GPU 加速） |
| 存储 | 10 GB 可用空间 | 50 GB+ |

### 软件

- 操作系统：Windows 10+ / Linux（Ubuntu 18.04+）
- Python：3.8+
- FFmpeg：已预装或自动安装
- 浏览器：Chrome 90+ / Edge 90+

---

## 快速开始

### 1. 安装依赖

```bash
# 克隆项目
git clone https://github.com/your-repo/dramaclip.git
cd dramaclip

# 安装 Python 依赖
pip install -r requirements.txt
```

### 2. 配置

复制配置文件并填入你的 API Key：

```bash
cp config.example.toml config.toml
# 编辑 config.toml，填入 API 相关配置
```

### 3. 启动

```bash
# Web 界面（Gradio，快速体验）
python webui.py

# 或通过 Docker 部署
docker-compose up -d
```

启动后打开浏览器访问 `http://localhost:7860` 即可使用。

---

## 使用流程

```
准备素材 → 上传短剧 → 选择模式 → 设置参数 → 开始处理 → 预览下载
```

1. **准备素材**：单集 1~5 分钟，单文件 ≤ 200MB，支持 MP4/MOV/AVI
2. **上传短剧**：拖拽上传 1~N 集，系统自动显示剧集序号、时长信息
3. **选择模式**：
   - 原片直剪模式 → 保留原声，快速出片
   - AI 解说模式 → 生成旁白，适配解说场景
4. **设置参数**：输出时长（15s/30s/45s/60s），高光阈值，字幕样式等
5. **开始处理**：进度可视化（预处理 → 高光筛选 → 剪辑合成）
6. **预览下载**：查看成片、手动调整片段顺序、下载成片及字幕/文案

---

## 输入输出约束

| 类型 | 约束 |
|------|------|
| 输入格式 | MP4、MOV、AVI 等常见格式 |
| 输入时长 | 单集 1~5 分钟 |
| 输入大小 | 单文件 ≤ 200MB |
| 输入画质 | 分辨率 ≥ 720P |
| 输出格式 | MP4，竖屏 9:16，1080P |
| 输出时长 | 15s / 30s / 45s / 60s |

---

## 处理速度参考

| 模式 | 1 集 | 3 集 | 6 集 |
|------|------|------|------|
| 原片直剪模式 | ≤ 30s | ≤ 1min | ≤ 2min |
| AI 解说模式 | ≤ 1min | ≤ 2min | ≤ 3min |

> GPU 加速可显著提升处理速度。

---

## 系统维护

- **缓存清理**：定期清理处理中间文件，节省存储空间
- **版本更新**：关注 Release 更新，获取性能优化和新功能
- **日志查看**：后端日志位于 `app/logs/`，便于排查问题

---

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| 上传失败"文件过大" | 单文件需 ≤ 200MB，可压缩后重新上传 |
| 处理超时 | 检查网络，关闭其他占 CPU/GPU 的程序，减少单次剧集数量 |
| AI 解说语音有机械感 | 调整语音情绪/语速/音色，重新生成 |
| 音频音量不均衡 | 系统自动均衡，或在参数设置中手动调整音频增益 |
| 字幕时间轴有偏差 | ≤ 0.5s 属正常，可手动调整字幕 |

---

## 参考项目

本项目在开发过程中参考了以下两个开源项目的设计与实现：

### 1. [AutoClip](https://github.com/AutoClip-AI/autoclip)（`SourceProjects/autoclip/`）

AutoClip 是一款商业级 SaaS 平台，专注于 AI 驱动的视频剪辑。本项目参考了其：

- **WebUI 交互设计**：React + TypeScript 前端架构，拖拽上传、实时预览、进度可视化等交互模式
- **工作流设计**：上传 → 分析 → 剪辑 → 导出四阶段流程
- **项目目录结构**：前后端分离的组织方式

> AutoClip 拥有完整的付费功能实现，本项目仅学习其设计思路，独立实现所有代码。

### 2. [NarratoAI](https://github.com/NarratoAI/NarratoAI)（`SourceProjects/NarratoAI/`）

NarratoAI 是一款开源的 AI 视频解说生成工具，支持文案生成、TTS 配音与视频合成。本项目参考了其：

- **AI 解说流程**：剧情分析 → 文案生成 → 旁白配音 → 音画对齐
- **Prompt 工程**：短剧解说的提示词结构与文案风格分类
- **字幕叠加方案**：解说字幕 + 原片字幕双轨字幕系统

> NarratoAI 的核心 AI 模块（Prompt 模板、脚本生成逻辑）为本项目的 AI 解说模式提供了重要参考。

---

## License

本项目仅供学习与研究使用。

---

> DramaClip — 让短剧高光剪辑更简单。
