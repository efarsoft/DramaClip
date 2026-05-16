# DramaClip - 短剧自动高光剪辑工具

一款基于 AI 的短剧自动高光剪辑工具，能够智能分析视频内容，自动检测高光片段，并生成精彩的短视频。

## ✨ 功能特性

- 🎬 **智能高光检测**：多维度分析（音频爆点、台词情绪、画面特征、镜头节奏）
- 🤖 **AI 驱动**：集成 LLM 视觉分析、ASR 语音识别、台词情绪分析
- 🎙️ **AI 解说**：支持本地 StyleTTS2 / Edge TTS / Azure Speech / 腾讯 TTS / CosyVoice
- ✂️ **智能剪辑**：场景分割 → 高光筛选 → 片段拼接 → 字幕合成
- 📦 **批量处理**：支持多集剧集批量分析和处理
- 🖥️ **桌面应用**：基于 Electron 的跨平台桌面客户端

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
- **OpenAI API** - LLM 视觉分析
- **librosa** - 音频分析
- **OpenCV** - 视频处理
- **PySceneDetect** - 场景分割
- **jieba** - 中文分词

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

### 开发模式

```bash
npm run dev
```

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

配置文件位于 `config.toml`，主要配置项：

```toml
[app]
# LLM 配置
vision_llm_provider = "openai"
vision_openai_model_name = "Qwen/Qwen2.5-VL-32B-Instruct"
vision_openai_api_key = "your-api-key"
vision_openai_base_url = "https://api.siliconflow.cn/v1"

# TTS 配置
tts_engine = "styletts2"

[highlight]
# 高光检测权重
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
