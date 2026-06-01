# DramaClip - 短剧自动高光剪辑工具

一款基于 AI 的短剧自动高光剪辑工具，能够智能分析视频内容，自动检测高光片段，并生成精彩的短视频。

## ✨ 功能特性

- 🎬 **智能高光检测**：多维度分析（音频爆点、台词情绪、画面特征、镜头节奏），自动提炼剧集高光点。
- 🤖 **AI 驱动**：集成 LLM 视觉分析、ASR 语音识别、台词情绪分析、候选爆款标题/简介智能推介。
- 🚀 **智能字幕与文案提取工坊**：独创页内 Segmented Tab 双模极速切换——🎬 **AI 智能声轨打轴器**（多人对白毫秒级定位，快捷单句复制，支持标准 `.srt` 字幕导出）与 🎙️ **AI 口播文案提取器**（智能过滤语气口癖，重整连续段落，无缝对接“震惊反转、悬疑拉满、情感共鸣、智能洗稿” 4 大风格 AI 一键改写工作台）。一次 ASR 转写，双模即时填充！
- 🛡️ **智能消重与台词保护**：首创基于 SRT 字幕的**静音区避让 (智能 Jitter) 算法**，配合极微变速、等尺寸微缩放、画面色彩抖动及文件指纹抹除，零损伤剧情连续性，在平台眼里全是“原创孤品”！
- 🎙️ **AI 解说**：支持本地 StyleTTS2 / Edge TTS / Azure Speech / 腾讯 TTS / CosyVoice。
- 💾 **项目级状态持久化与断点续剪**：支持全流程状态持久化缓存（已选剧集、方案预设、尺寸比例、已导出成品列表、AI 生成候选标题及简介），彻底摆脱“软件关闭/切换页面必须从头开始”的痛苦，带来工业级“随时中断，随时恢复”的顺畅体验。
- 🔒 **数字路径安全编码防崩溃**：重构底层物理路径逻辑，使用 `project_id` Alphanumeric UUID 代替中文项目文件夹名，从根源上杜绝 Windows ANSI 路径编码错乱引起的 CLI 调用崩溃，保障系统在极端条件下的健壮性。
- ✂️ **智能剪辑**：场景分割 → 高光筛选 → 片段拼接 → 字幕合成。
- 📦 **批量处理**：主流程支持多集剧集批量导入、批量分析与智能二创排版。
- 🖥️ **桌面应用**：基于 Electron 33 的跨平台桌面客户端，全屏发光深空科技感 UI/UX 体验。

## 🛡️ 智能消重与台词静音区避让系统

本工具在行业中首创了**剧情零损伤的影院级去重闭环系统**，专门解决短剧剪辑中同质化素材在短视频平台（如抖音、快手、视频号等）的排重机制（重合度检测）：

1. **静音区避让与台词防吞 (Smart Jitter)**:
   - **绝对禁止盲切**：避免纯数学随机加减导致“吞字”或“闪帧”。
   - **台词保护区**：自动读取同名 `.srt` 字幕，将每行字幕的 `[开始 - 0.2s, 结束 + 0.15s]` 标定为**台词保护禁区**。
   - **智能避让与抖动**：当首尾裁切点落在禁区内时，自动向外避让（Snap）保留台词完整性；若落在安静的空白间隙，则允许在物理间隙边界内进行 `+/- 0.1s ~ 0.3s` 的随机安全抖动（Jitter）。
2. **极微变速抖动 (Micro-Speed Jitter)**:
   - 为每个片段应用极微弱的随机变速（`0.996` - `1.004` 之间），拉开与源视频的时间轴与波形对齐。
   - 自动启用 FFmpeg `atempo` 音频滤镜进行**变速不变调（变调补偿）**处理，重新编码为 `AAC` 格式，音质饱满连续。
3. **等尺寸画面微缩放 (Micro-Scaling)**:
   - 对画面应用 `[1.2%, 1.8%]` 的随机微缩放（`scale_factor`）。
   - 裁切出的局部画面通过 `scale` 滤镜等比例**拉伸回原定标准输出尺寸**（如竖屏 1080x1920），彻底破坏像素哈希指纹的同时防止不同片段产生分辨率偏差或黑边。
4. **像素与亮度色彩微抖动 (Visual eq)**:
   - 叠加 `eq` 滤镜对对比度进行 `[0.99, 1.01]` 的轻微抖动，亮度进行 `[-0.01, 0.01]` 微幅波动，改变每一帧的特征向量与色域哈希。
5. **元数据指纹彻底擦除 (Metadata Cleansing)**:
   - 在片段分割与最终拼接（Concat）的 FFmpeg 命令中全程注入 `-map_metadata -1` 参数，物理上百分之百抹除原视频相机的创建时间、地理位置、编码工具等设备标签。

## 🛠️ 技术栈

### 前端
- **Electron 33.x** - 跨平台桌面应用框架
- **React 19.x** - UI 框架
- **TypeScript 5.7** - 类型安全
- **Vite 6.x** - 构建工具
- **Ant Design 5.x** - UI 组件库
- **Zustand 5.x** - 状态管理

### 后端
- **Python 3.10+** - 后端语言
- **PyInstaller** - 打包为可执行文件
- **JSON-RPC 2.0** - 进程间通信协议

### AI/ML
- **OpenAI API / Dashscope (Qwen)** - LLM 视觉与剧本分析
- **faster-whisper / SenseVoice** - 离线高精度 ASR 语音识别与情感/音频事件检测
- **librosa** - 音频爆点与节奏分析
- **OpenCV** - 视频智能帧内容检测
- **PySceneDetect** - 物理镜头与场景分割
- **jieba** - 中文台词分词与文本挖掘

## 📦 安装

### 前置要求

- Node.js 18+
- Python 3.10+
- FFmpeg（用于视频处理）

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/your-username/DramaClip.git
cd DramaClip

# 2. 安装前端依赖
npm install

# 3. 安装 Python 后端依赖
pip install -r requirements.txt

# 4. 复制配置文件
cp config.example.toml config.toml
# 编辑 config.toml 配置 API 密钥等

# 5. 启动开发模式
npm run dev
```

## 🚀 使用

### 开发模式（推荐）

```bash
# 方式一：仅前端 Vite（需手动启动 Electron）
npm run dev

# 方式二：一键完整开发栈（推荐，自动构建主进程 + 启动 Electron + 支持 Python 源码后端直跑）
npm run dev:full
```

> **注意**：后端支持两种模式：
> - 开发时优先使用 `app/backend_main.py` + 项目 `.venv`（无需每次 PyInstaller）
> - 生产/完整测试时使用 `python scripts/build-backend.py` 打包 `dist-backend/`

启动后修改前端 TSX 热更新，修改 Python 后端代码需重启 Electron（manager 会自动重启后端进程）。

### 生产构建

```bash
# 构建前端
npm run build:vite

# 打包 Python 后端
python scripts/build-backend.py

# 构建 Electron 应用
npm run build
```

### 运行测试

```bash
# 前端测试
npm test

# Python 后端测试
pytest
```

## 📁 项目结构

```
DramaClip/
├── main/                    # Electron 主进程
│   ├── app.ts              # 应用入口
│   ├── preload.ts          # 预加载脚本
│   ├── backend/            # 后端进程管理
│   ├── ipc/                # IPC 通信层
│   ├── window/             # 窗口管理
│   └── services/           # 主进程服务
├── src/                     # React 前端
│   ├── pages/              # 页面组件
│   ├── components/         # UI 组件
│   ├── stores/             # Zustand 状态管理
│   ├── services/           # IPC 客户端
│   └── types/              # TypeScript 类型
├── app/                     # Python 后端
│   ├── backend_main.py     # 后端入口
│   ├── ipc/                # JSON-RPC 服务端
│   ├── services/           # 业务逻辑层
│   │   ├── highlight/      # 高光检测核心
│   │   ├── llm/            # LLM 服务
│   │   ├── analyze/        # 分析服务
│   │   └── narration/      # 解说生成
│   ├── config/             # 配置管理
│   └── utils/              # 工具函数
├── tests/                   # 测试文件
├── scripts/                 # 构建脚本
├── resources/               # 资源文件
└── docs/                    # 文档
```

## ⚙️ 配置

DramaClip 采用了一套高内聚的**双重配置与热更新体系 (Dual-Config & Hot-Reload System)**，兼顾桌面端用户的可视化易用性与开发者的命令行高度可控性：

### 🔄 配置优先级与热更新策略
1. **`settings.json`（GUI 可视化设置，高优先级）**：
   - **路径**：`C:\Users\您的用户名\.dramaclip\settings.json` (Windows 平台)
   - **特点**：当您在桌面端客户端界面的 **「系统设置」** 页面修改并保存配置时，应用会自动将新配置写入该文件。底层的 Python 后端服务在检测到更改后会触发**热重载机制 (Hot-Reload)**，新配置将**瞬间在全局生效**。因此，您不需要将设置手动同步拷贝回本地的 `config.toml` 文件中，即可享用最新配置。
2. **`config.toml`（文件级默认配置，兼容性后备）**：
   - **路径**：项目根目录 `/config.toml`（首次使用时从 `/config.example.toml` 复制）
   - **特点**：主要用作软件首次安装的初始默认参数，或者在命令行模式（CLI）下的直接加载与参数调试。
3. **优先级合并逻辑 (Fallback Priority)**：
   - 统一配置管理器 `UnifiedConfig` 会将两个配置源合并。以高优先级的 `settings.json` 为主；只有当某些字段在 `settings.json` 中不存在时，系统才会降级去读取 `config.toml` 的对应默认值，提供极致的健壮性。

### 📄 config.toml 配置模板示范

```toml
[app]
# LLM 兼容配置 (如 Dashscope / 通义千问等兼容 OpenAI 接口的模型)
vision_llm_provider = "openai"
vision_openai_model_name = "qwen3.6-plus"
vision_openai_api_key = "your-dashscope-api-key"
vision_openai_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# ASR 语音识别配置
[asr]
engine = "faster_whisper"    # ASR引擎: faster_whisper | sensevoice
model = "large-v3"           # whisper 模型尺寸或 SenseVoice 型号
device = "auto"              # 自动检测 cuda/cpu 硬件加速
enable_emotion = true        # 启用情绪识别（SenseVoice 独有）

# 视频剪辑高光打分权重
[highlight]
audio_weight = 0.4
emotion_weight = 0.3
visual_weight = 0.2
rhythm_weight = 0.1
```

## 🧪 测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/app/services/highlight/

# 运行带覆盖率的测试
pytest --cov=app --cov-report=html
```

## 📝 开发指南

### 代码风格

- **Python**: 使用 Black 格式化，isort 排序导入
- **TypeScript**: 使用 ESLint + Prettier

```bash
# Python 代码格式化
black app/
isort app/

# TypeScript 代码检查
npm run lint
npm run format
```

### 提交规范

使用语义化提交信息：

```
feat: 新功能
fix: 修复 bug
docs: 文档更新
style: 代码格式调整
refactor: 重构
test: 测试相关
chore: 构建/工具相关
```

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 🤝 贡献

欢迎贡献！请遵循以下步骤：

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'feat: Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

## 📧 联系方式

如有问题或建议，请通过以下方式联系：

- 提交 Issue
- 发送邮件至：your-email@example.com

## 🙏 致谢

感谢以下开源项目：

- [Electron](https://www.electronjs.org/)
- [React](https://react.dev/)
- [Vite](https://vitejs.dev/)
- [Ant Design](https://ant.design/)
- [Zustand](https://github.com/pmndrs/zustand)
- [librosa](https://librosa.org/)
- [OpenCV](https://opencv.org/)
- [PySceneDetect](https://pyscenedetect.readthedocs.io/)
