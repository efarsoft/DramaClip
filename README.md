# DramaClip v2

**本地优先的短剧自动高光剪辑工具，面向短剧推广达人（短剧 CPS 从业者）。**
核心能力：导入短剧视频 → AI 智能分析 → 自动生成多种风格的推广短视频。

> v1（Electron 版原型）完整封存于 `legacy/v1-electron` 分支与 `backup/` 目录（只读参考，不参与构建）。
> v2 全部代码为全新重写，架构与规范见 `docs/`。

## 结构

```
desktop/    Electron + React 桌面应用（main/ 主进程薄壳 + src/ 渲染层）
service/    Python 本地服务（分析/解说/字幕/消重/TTS/存储，包名 dramaclip）
protocol/   三端契约唯一真相源（JSON Schema + TS 类型）
resources/  随应用分发的只读资源（ffmpeg/字体/内置字幕预设）
scripts/    开发编排脚本
docs/       架构决策记录、质量规约、技术方案、经验参数表
backup/     v1 快照（gitignored）
```

## 常用命令

```bash
npm install                            # 前端依赖（根目录）
npm run dev                            # 一键启动开发栈（Vite + Electron + Python 服务）
python -m venv .venv                   # Python 环境（首次）
.venv/Scripts/pip install -e "service[dev]"   # 服务依赖（Windows）
.venv/Scripts/python -m pytest service/tests  # Python 测试
```

## 打包发布（W14）

```bash
npm run dist:service                   # PyInstaller sidecar → resources/dramaclip-service/（onedir，含 ML 依赖）
node scripts/verify_sidecar.mjs        # sidecar 冒烟：握手/资源注入/预设/预筛/优雅退出
npm run dist                           # sidecar + vite build + electron-builder（NSIS + zip → desktop/release/）
```

sidecar 产物约 1 GB（torch/ctranslate2/faster-whisper 等全量随包），gitignored，
由 electron-builder `extraResources` 随安装包分发至 `resources/app-resources/`；
主进程经 `process.resourcesPath` 定位并以 `DRAMACLIP_RESOURCES_DIR` 注入服务。

## 恢复 ffmpeg

```bash
git checkout legacy/v1-electron -- resources/ffmpeg/ffmpeg.exe resources/ffmpeg/ffprobe.exe
```
