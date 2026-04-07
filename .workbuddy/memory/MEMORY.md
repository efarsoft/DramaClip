# DramaClip 项目长期记忆

## 项目概述
DramaClip 是一个短剧自动高光剪辑系统，基于 NarratoAI 改造开发。
核心特性：单系统双模式（原片直剪模式 + AI解说模式）。

## 技术决策
- **基础项目**：NarratoAI v0.7.7（Python + Streamlit）
- **新增依赖**：pyscenetect, librosa, opencv-python, jieba
- **核心新增模块**：highlight（高光打分）、sorter（智能排序）、direct_cut（原片直剪）、narration增强

## 关键架构决策
- 打分公式：score = 0.4×音频爆点 + 0.3×台词情绪 + 0.2×画面特征 + 0.1×镜头节奏
- 输出规格：MP4, 1080P, 9:16竖屏, 15~60秒
- 共用模块：输入、预处理、高光识别筛选、智能排序、辅助功能
- 差异化模块：剪辑与输出（按模式分流）

## 用户偏好
- 用户倾向于快速出成果，优先保证核心功能

## 项目状态 (2026-04-07 更新)
- **当前阶段**: ✅ E2E 链路全通，代码审查修复完成，ffmpeg_utils.py 重新整理
- **代码质量评分**: 7.2 → 修复21个问题后预估 8.5+
- **测试素材**: `E:\短剧\超级任务之大反派\`（64集MP4）
- **硬件环境**: AMD Ryzen + Radeon RX 5500 XT + D3D11VA 硬件加速
- **E2E 测试结果**:
  - 单集: ✅ 176.9MB成品, 6片段, ~15.6min
  - 多集3集: ✅ 355.2MB成品, 10片段, 42.4s, ~42.2min
  - 人脸居中裁剪: ✅ 修复crop filter参数顺序后100%成功
  - 2026-04-07 E2E retest: 🔄 运行中（VisualScorer 22/25 segments完成）
- **多集处理**: ✅ 已修复调度层断裂 + 视频处理函数补齐
  - task.py _run_direct_cut_pipeline() 调用 DirectCutPipeline.run(video_paths=List[str])
  - webui.py 直剪模式不需要脚本 JSON，校验支持 video_origin_paths 列表
  - ffmpeg_utils.py 新增 6 个核心函数（extract_audio/clip_video/crop_to_portrait_face_centered/crop_to_portrait_centered/concat_videos/mix_audio_video）
  - pipeline.py 修复 AudioNormalizer 参数 + subtitle_merger 接口
- **代码审查修复 (2026-04-06 晚)**: 全部21个P0/P1/P2问题已修复
  - P0×4: 资源泄漏(VideoCapture×2 + VideoManager) + .gitignore确认
  - P1×9: 异常处理/返回值检查/线程安全/边界条件/递归限制等
  - P2×8: 类型标注/死代码标记/魔法数字常量化/日志级别/命名修正/重复代码抽取/缓存安全
- **ffmpeg_utils.py 重整 (2026-04-07)**:
  - 因中文docstring导致的SyntaxError，git checkout恢复原始文件
  - 最小修改方案：只加 threading.Lock + Any类型标注 + detect_hardware_acceleration加锁+防递归
  - 重新编写6个核心视频处理函数（extract_audio/clip_video/crop_to_portrait_face_centered/crop_to_portrait_centered/concat_videos/mix_audio_video）
  - 所有新增函数用英文docstring，避免中文标点SyntaxError
- **已知待优化项**:
  - VisualScorer 性能已优化（seek跳帧+0.5fps+640px降分辨率+scaleFactor 1.3），预计提速3-5倍
  - 高光预览面板已修复（pipeline→task_state→session_state 完整链路）
  - AI解说模式已支持多集（新增 _run_ai_narration_pipeline 调用 NarrationPipeline）
  - 核心模块单元测试 37个 pytest 全部通过（tests/test_core_units.py）
  - 缺少端到端集成测试（需要视频素材，目前仅有手动E2E脚本）
  - 情感TTS已集成：CosyVoice V3（DashScope API）+ Qwen3-TTS instruct-flash，config.cosyvoice 段

## 验收修复记录（重要！后续开发注意）
- scene_detect.py 的 FrameTimecode 对象必须用 `.get_seconds()` 转换，不能直接 `/ float`
- 列表删除操作禁止遍历中 pop(i)，必须用列表推导式过滤
- audio_scorer.py 有过死代码残留，审查时注意检查
- script_settings.py 的 generate_script_docu 已替换为空实现（兼容接口）
- ffmpeg_utils.py 新增函数必须用英文docstring！中文全角标点（，。：）会导致Python SyntaxError
- rhythm_scorer.py: MIN_MARGIN_SECONDS 是类变量，方法中必须用 self.MIN_MARGIN_SECONDS
- rhythm_scorer.py: score() 签名是 (duration, start_time, episode_duration, ...)，没有 end_time 参数
- PowerShell 的 `>` 重定向有缓冲问题，长时间运行的测试用 Python subprocess + 文件实时写入
- tqdm 进度条用 \r 覆盖行，readlines() 看不到更新，需检查文件大小或进程内存变化
