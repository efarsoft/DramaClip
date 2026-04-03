import streamlit as st
import os
import sys
from loguru import logger
from app.config import config
from webui.components import basic_settings, video_settings, audio_settings, subtitle_settings, script_settings, \
    system_settings
# from webui.utils import cache, file_utils
from app.utils import utils
from app.utils import ffmpeg_utils
from app.models.schema import VideoClipParams, VideoAspect


# 初始化配置 - 必须是第一个 Streamlit 命令
st.set_page_config(
    page_title="DramaClip 短剧高光剪辑",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="auto",
    menu_items={
        "Report a bug": "https://github.com/linyqh/NarratoAI/issues",
        'About': f"# 🎬 DramaClip :blue[短剧自动高光剪辑系统] \n "
                 f"#### Version: v{config.project_version} \n "
                 f"单系统双模式：原片直剪（保留原声）| AI解说（生成旁白）"
    },
)

# 设置页面样式
hide_streamlit_style = """
<style>#root > div:nth-child(1) > div > div > div > div > section > div {padding-top: 2rem; padding-bottom: 10px; padding-left: 20px; padding-right: 20px;}</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)


def init_log():
    """初始化日志配置"""
    from loguru import logger
    logger.remove()
    _lvl = "INFO"  # 改为 INFO 级别，过滤掉 DEBUG 日志

    def format_record(record):
        # 简化日志格式化处理，不尝试按特定字符串过滤torch相关内容
        file_path = record["file"].path
        relative_path = os.path.relpath(file_path, config.root_dir)
        record["file"].path = f"./{relative_path}"
        record['message'] = record['message'].replace(config.root_dir, ".")

        _format = '<green>{time:%Y-%m-%d %H:%M:%S}</> | ' + \
                  '<level>{level}</> | ' + \
                  '"{file.path}:{line}":<blue> {function}</> ' + \
                  '- <level>{message}</>' + "\n"
        return _format

    # 添加日志过滤器
    def log_filter(record):
        """过滤不必要的日志消息"""
        # 过滤掉启动时的噪音日志（即使在 DEBUG 模式下也可以选择过滤）
        ignore_patterns = [
            "Examining the path of torch.classes raised",
            "torch.cuda.is_available()",
            "CUDA initialization"
        ]
        return not any(pattern in record["message"] for pattern in ignore_patterns)

    logger.add(
        sys.stdout,
        level=_lvl,
        format=format_record,
        colorize=True,
        filter=log_filter
    )

    # 应用启动后，可以再添加更复杂的过滤器
    def setup_advanced_filters():
        """在应用完全启动后设置高级过滤器"""
        try:
            for handler_id in logger._core.handlers:
                logger.remove(handler_id)

            # 重新添加带有高级过滤的处理器
            def advanced_filter(record):
                """更复杂的过滤器，在应用启动后安全使用"""
                ignore_messages = [
                    "Examining the path of torch.classes raised",
                    "torch.cuda.is_available()",
                    "CUDA initialization"
                ]
                return not any(msg in record["message"] for msg in ignore_messages)

            logger.add(
                sys.stdout,
                level=_lvl,
                format=format_record,
                colorize=True,
                filter=advanced_filter
            )
        except Exception as e:
            # 如果过滤器设置失败，确保日志仍然可用
            logger.add(
                sys.stdout,
                level=_lvl,
                format=format_record,
                colorize=True
            )
            logger.error(f"设置高级日志过滤器失败: {e}")

    # 将高级过滤器设置放到启动主逻辑后
    import threading
    threading.Timer(5.0, setup_advanced_filters).start()


def init_global_state():
    """初始化全局状态"""
    if 'video_clip_json' not in st.session_state:
        st.session_state['video_clip_json'] = []
    if 'video_plot' not in st.session_state:
        st.session_state['video_plot'] = ''
    if 'ui_language' not in st.session_state:
        st.session_state['ui_language'] = config.ui.get("language", utils.get_system_locale())
    # 多集短剧支持
    if 'episode_paths' not in st.session_state:
        st.session_state['episode_paths'] = []     # [{'path', 'name', 'duration'}, ...]
    if 'video_origin_paths' not in st.session_state:
        st.session_state['video_origin_paths'] = []
    # 移除subclip_videos初始化 - 现在使用统一裁剪策略


def tr(key):
    """翻译函数"""
    i18n_dir = os.path.join(os.path.dirname(__file__), "webui", "i18n")
    locales = utils.load_locales(i18n_dir)
    loc = locales.get(st.session_state['ui_language'], {})
    return loc.get("Translation", {}).get(key, key)


def render_generate_button():
    """渲染生成按钮和处理逻辑 - 支持单视频和多集短剧"""
    if st.button(tr("Generate Video"), use_container_width=True, type="primary"):
        from app.services import task as tm
        from app.services import state as sm
        from app.services.multi_episode_processor import start_multi_episode
        from app.models import const
        import threading
        import time
        import uuid

        config.save_config()

        # 获取 episode 列表
        episode_paths: list = st.session_state.get('video_origin_paths', [])

        if not episode_paths:
            st.error(tr("请先添加短剧集（支持单集或多集）"))
            return

        # 多集模式：自动走多集流程
        if len(episode_paths) >= 2:
            _run_multi_episode(episode_paths, sm, const)
            return

        # 单集模式：向后兼容原有逻辑
        _run_single_episode(sm, const, tm, script_settings, video_settings, audio_settings, subtitle_settings)


def _run_single_episode(sm, const, tm, script_settings, video_settings, audio_settings, subtitle_settings):
    """单集处理流程（向后兼容）"""
    if not st.session_state.get('video_clip_json_path'):
        st.error(tr("脚本文件不能为空"))
        return
    if not st.session_state.get('video_origin_path'):
        st.error(tr("视频文件不能为空"))
        return

    script_params = script_settings.get_script_params()
    video_params = video_settings.get_video_params()
    audio_params = audio_settings.get_audio_params()
    subtitle_params = subtitle_settings.get_subtitle_params()

    all_params = {
        **script_params,
        **video_params,
        **audio_params,
        **subtitle_params
    }
    params = VideoClipParams(**all_params)

    task_id = str(uuid.uuid4())
    progress_bar = st.progress(0)
    status_text = st.empty()

    def run_task():
        try:
            tm.start_subclip_unified(task_id=task_id, params=params)
        except Exception as e:
            logger.error(f"单集任务执行失败: {e}")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, message=str(e))

    thread = threading.Thread(target=run_task)
    thread.start()

    _poll_task_status(task_id, sm, const, progress_bar, status_text)


def _run_multi_episode(episode_paths: list, sm, const):
    """多集短剧处理流程"""
    import uuid as uuid_mod

    episode_count = len(episode_paths)
    episode_names = [os.path.basename(p) for p in episode_paths]
    logger.info(f"[UI] 启动多集处理: {episode_count} 集 — {episode_names}")

    # 获取所有参数
    script_params = script_settings.get_script_params()
    video_params = video_settings.get_video_params()
    audio_params = audio_settings.get_audio_params()
    subtitle_params = subtitle_settings.get_subtitle_params()

    all_params = {
        **script_params,
        **video_params,
        **audio_params,
        **subtitle_params
    }
    params = VideoClipParams(**all_params)

    task_id = str(uuid_mod.uuid4())
    progress_bar = st.progress(0)
    status_text = st.empty()

    # 进度回调（由后端 task.py 的 sm.state 驱动）
    def progress_callback(progress: float, message: str):
        """Streamlit-safe 进度更新（通过 session_state 传递）"""
        st.session_state[f'_task_progress_{task_id}'] = (progress, message)

    def run_task():
        try:
            from app.services.multi_episode_processor import start_multi_episode
            start_multi_episode(
                task_id=task_id,
                params=params,
                episode_paths=episode_paths,
                progress_callback=progress_callback,
            )
        except Exception as e:
            logger.error(f"[多集] 任务执行失败: {e}")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, message=str(e))

    # 启动后台线程
    thread = threading.Thread(target=run_task)
    thread.start()

    # 轮询任务状态（合并后端 state + 前端回调进度）
    prev_pct = 0
    while True:
        task = sm.state.get_task(task_id)
        if task:
            state = task.get("state")

            # 尝试从回调进度更新（更细粒度）
            cb_data = st.session_state.get(f'_task_progress_{task_id}')
            if cb_data:
                cb_pct, cb_msg = cb_data
                progress_bar.progress(cb_pct / 100)
                status_text.text(cb_msg)
                prev_pct = cb_pct
            else:
                # fallback 到后端粗粒度进度
                backend_pct = task.get("progress", prev_pct)
                if backend_pct != prev_pct:
                    progress_bar.progress(backend_pct / 100)
                    status_text.text(f"处理中... {backend_pct:.0f}%")
                    prev_pct = backend_pct

            if state == const.TASK_STATE_COMPLETE:
                status_text.text("✅ 多集高光剪辑完成！")
                progress_bar.progress(1.0)

                video_files = task.get("videos", [])
                if video_files:
                    st.success(f"🎬 处理完成！共 {episode_count} 集短剧高光，已生成成片")
                    for vf in video_files:
                        st.video(vf)
                else:
                    st.success("处理完成！")
                break

            elif state == const.TASK_STATE_FAILED:
                err = task.get('message', 'Unknown error')
                st.error(f"❌ 处理失败: {err}")
                break

        time.sleep(0.5)


def _poll_task_status(task_id, sm, const, progress_bar, status_text):
    """轮询单集任务状态"""
    import time
    while True:
        task = sm.state.get_task(task_id)
        if task:
            progress = task.get("progress", 0)
            state = task.get("state")

            progress_bar.progress(progress / 100)
            status_text.text(f"处理中... {progress:.0f}%")

            if state == const.TASK_STATE_COMPLETE:
                status_text.text(tr("视频生成完成"))
                progress_bar.progress(1.0)
                video_files = task.get("videos", [])
                if video_files:
                    player_cols = st.columns(len(video_files) * 2 + 1)
                    for i, url in enumerate(video_files):
                        player_cols[i * 2 + 1].video(url)
                st.success(tr("视频生成完成"))
                break

            elif state == const.TASK_STATE_FAILED:
                st.error(f"任务失败: {task.get('message', 'Unknown error')}")
                break

        time.sleep(0.5)



def main():
    """主函数"""
    init_log()
    init_global_state()

    # ===== 显式注册 LLM 提供商（最佳实践）=====
    # 在应用启动时立即注册，确保所有 LLM 功能可用
    if 'llm_providers_registered' not in st.session_state:
        try:
            from app.services.llm.providers import register_all_providers
            register_all_providers()
            st.session_state['llm_providers_registered'] = True
            logger.info("✅ LLM 提供商注册成功")
        except Exception as e:
            logger.error(f"❌ LLM 提供商注册失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            st.error(f"⚠️ LLM 初始化失败: {str(e)}\n\n请检查配置文件和依赖是否正确安装。")
            # 不抛出异常，允许应用继续运行（但 LLM 功能不可用）

    # 检测FFmpeg硬件加速，但只打印一次日志（使用 session_state 持久化）
    if 'hwaccel_logged' not in st.session_state:
        st.session_state['hwaccel_logged'] = False
    
    hwaccel_info = ffmpeg_utils.detect_hardware_acceleration()
    if not st.session_state['hwaccel_logged']:
        if hwaccel_info["available"]:
            logger.info(f"FFmpeg硬件加速检测结果: 可用 | 类型: {hwaccel_info['type']} | 编码器: {hwaccel_info['encoder']} | 独立显卡: {hwaccel_info['is_dedicated_gpu']}")
        else:
            logger.warning(f"FFmpeg硬件加速不可用: {hwaccel_info['message']}, 将使用CPU软件编码")
        st.session_state['hwaccel_logged'] = True

    # 仅初始化基本资源，避免过早地加载依赖PyTorch的资源
    # 检查是否能分解utils.init_resources()为基本资源和高级资源(如依赖PyTorch的资源)
    try:
        utils.init_resources()
    except Exception as e:
        logger.warning(f"资源初始化时出现警告: {e}")

    st.title(f"🎬 DramaClip :blue[短剧高光剪辑系统]")
    st.write(tr("Get Help"))

    # 首先渲染不依赖PyTorch的UI部分
    # 渲染基础设置面板
    basic_settings.render_basic_settings(tr)

    # 渲染主面板
    panel = st.columns(3)
    with panel[0]:
        script_settings.render_script_panel(tr)
    with panel[1]:
        audio_settings.render_audio_panel(tr)
    with panel[2]:
        video_settings.render_video_panel(tr)
        subtitle_settings.render_subtitle_panel(tr)

    # 放到最后渲染可能使用PyTorch的部分
    # 渲染系统设置面板
    with panel[2]:
        system_settings.render_system_panel(tr)

    # 放到最后渲染生成按钮和处理逻辑
    render_generate_button()


if __name__ == "__main__":
    main()
