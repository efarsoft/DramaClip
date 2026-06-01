"""
DramaClip 服务层

子模块组织（按领域划分）：
    analyze/      → 视频分析（ASR、情绪、视觉、节奏、说话人分离）
    clip/         → 剪辑流水线（直剪/交叉解说/全片解说 + 风格 + 视频裁剪）
    highlight/    → 高光识别与打分
    narration/    → AI 解说生成与混音
    llm/          → 大语言模型服务（多提供商）
    tts/          → TTS 语音合成（含引擎管理）
    project/      → 项目与视频管理（SQLite）
    prompts/      → 提示词模板与脚本生成
    sorter/       → 片段排序策略
    SDE/          → 短剧解说 (Short Drama Explanation)
    SDP/          → 短剧制作 (Short Drama Production)

独立服务：
    state.py              → 任务状态持久化（SQLite + 内存缓存）
    task_manager.py       → 通用任务生命周期管理（并发/取消/持久化）
    model_manager.py      → 模型下载/管理（HuggingFace + ModelScope）
    title_generator.py    → 标题与简介生成
    template_manager.py   → 剪辑模板管理
    mode_recommender.py   → 剪辑模式智能推荐
    onboarding.py         → 新手引导
    upload_validation.py  → 上传文件验证
    cleanup_service.py    → 临时文件清理

向后兼容 shim（已迁移，保留旧 import 路径）：
    voice.py              → 实际代码在 tts/voice.py
    clip_video.py         → 实际代码在 clip/clip_video.py
    subtitle_text.py      → 实际代码在 clip/subtitle_text.py
    clip_style.py         → 实际代码在 clip/style.py
"""
