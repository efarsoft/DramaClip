# DramaClip Resources

此目录包含应用程序运行所需的资源文件。

## 目录结构

```
resources/
├── ffmpeg.exe          # FFmpeg 可执行文件（需要下载）
├── ffprobe.exe         # FFprobe 可执行文件（需要下载）
├── fonts/              # 字体文件
│   └── SimHei.ttf     # 微软雅黑字体
└── models/             # AI 模型
    └── whisper-tiny/   # Whisper 语音识别模型
```

## 资源说明

### FFmpeg
- 版本：7.x
- 下载地址：https://ffmpeg.org/download.html
- Windows 推荐下载 `ffmpeg-release-essentials.zip`

### 模型
- Whisper tiny 模型将在首次运行时自动下载
- 存储位置：`%APPDATA%/dramaclip/models/`

## 注意事项

- `ffmpeg.exe` 和 `ffprobe.exe` 需要手动下载并放置在此目录
- 首次运行时会自动检测 FFmpeg 是否可用
