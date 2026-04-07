import streamlit as st
import os
import sys
import threading
from loguru import logger
from app.config import config
from webui.components import basic_settings, video_settings, audio_settings, subtitle_settings, script_settings, \
    system_settings, mode_selector, highlight_preview
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
        "Report a bug": "https://github.com/user/DramaClip/issues",
        'About': f"# :blue[DramaClip] 🎬 \n #### Version: v{config.project_version} \n "
                 f"短剧自动高光剪辑系统\n "
                 f"单系统双模式：原片直剪 | AI解说"
    },
)

# ============================================================
# DramaClip UI Theme - Custom CSS
# ============================================================
custom_css = """
<style>
/* ---- Global Layout ---- */
.block-container {
    padding-top: 2rem;
    padding-bottom: 1rem;
    padding-left: 1.5rem;
    padding-right: 1.5rem;
    max-width: 1400px;
}

/* ---- Title ---- */
h1 {
    font-weight: 800 !important;
    letter-spacing: -0.02em;
}

/* ---- Cards / Containers with border ---- */
.streamlit-expanderHeader,
div[data-testid="stContainer"] {
    border-radius: 12px !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
}

/* ---- Tabs ---- */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background: transparent;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 8px 16px;
    background-color: rgba(255, 255, 255, 0.05);
    color: rgba(255, 255, 255, 0.6);
    font-size: 14px;
    transition: all 0.2s ease;
}
.stTabs [data-baseweb="tab"]:hover {
    background-color: rgba(255, 255, 255, 0.1);
    color: rgba(255, 255, 255, 0.85);
}
.stTabs [aria-selected="true"] {
    background-color: #FF4D6D !important;
    color: white !important;
    font-weight: 600;
}

/* ---- Buttons ---- */
.stButton > button {
    border-radius: 10px;
    font-weight: 600;
    transition: all 0.2s ease;
    border: none;
}
.stButton > button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(255, 77, 109, 0.3);
}
.stButton > button:active {
    transform: translateY(0);
}
/* Primary button glow */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #FF4D6D, #FF758F);
    border: none;
}

/* ---- Selectbox / Input ---- */
div[data-testid="stSelectbox"] > div > div,
.stSelectbox label {
    font-size: 14px;
}

/* ---- Slider ---- */
.stSlider > div > div > div > div {
    background: linear-gradient(90deg, #FF4D6D, #FF758F);
}

/* ---- Radio buttons (mode selector) ---- */
div[data-testid="stRadio"] label {
    font-size: 15px;
    font-weight: 500;
}

/* ---- Segmented Control ---- */
div[data-testid="stSegmentedControl"] {
    background-color: rgba(255, 255, 255, 0.05);
    border-radius: 10px;
    padding: 4px;
}
div[data-testid="stSegmentedControl"] button {
    border-radius: 8px;
    font-weight: 500;
    transition: all 0.2s ease;
}

/* ---- Progress bar ---- */
.stProgress > div > div > div {
    background: linear-gradient(90deg, #FF4D6D, #FF758F, #FFB3C1);
    border-radius: 10px;
}

/* ---- Metric (highlight scores) ---- */
[data-testid="stMetricValue"] {
    font-size: 28px !important;
    font-weight: 700 !important;
}
[data-testid="stMetricLabel"] {
    font-size: 13px !important;
    opacity: 0.7;
}

/* ---- Info / Success / Warning / Error boxes ---- */
.stAlert {
    border-radius: 10px;
    border-left: 4px solid;
}

/* ---- Sidebar (hidden by default, reserve for future) ---- */
section[data-testid="stSidebar"] {
    display: none;
}

/* ---- Scrollbar (Webkit) ---- */
::-webkit-scrollbar {
    width: 6px;
}
::-webkit-scrollbar-track {
    background: transparent;
}
::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.15);
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: rgba(255, 255, 255, 0.25);
}

/* ---- File uploader ---- */
[data-testid="stFileUploader"] section {
    border: 2px dashed rgba(255, 77, 109, 0.3);
    border-radius: 12px;
    padding: 1.5rem;
    background: rgba(255, 77, 109, 0.03);
    transition: all 0.2s ease;
}
[data-testid="stFileUploader"] section:hover {
    border-color: rgba(255, 77, 109, 0.6);
    background: rgba(255, 77, 109, 0.06);
}

/* ---- Divider ---- */
hr {
    border: none;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.1), transparent);
    margin: 0.5rem 0;
}

/* ---- Hide Streamlit default hamburger / footer ---- */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)


def init_log():
    """初始化日志配置"""
    from loguru import logger
    logger.remove()
    _lvl = "INFO"

    def format_record(record):
        file_path = record["file"].path
        relative_path = os.path.relpath(file_path, config.root_dir)
        record["file"].path = f"./{relative_path}"
        record['message'] = record['message'].replace(config.root_dir, ".")

        _format = '<green>{time:%Y-%m-%d %H:%M:%S}</> | ' \
                  '<level>{level}</level> | ' \
                  '"{file.path}:{line}":<blue> {function}</blue> ' \
                  '- <level>{message}</level>' + "\n"
        return _format

    def log_filter(record):
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

    def setup_advanced_filters():
        try:
            for handler_id in logger._core.handlers:
                logger.remove(handler_id)

            def advanced_filter(record):
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
            logger.add(
                sys.stdout,
                level=_lvl,
                format=format_record,
                colorize=True
            )
            logger.error(f"设置高级日志过滤器失败: {e}")

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
    # DramaClip 新增状态
    if 'clip_mode' not in st.session_state:
        st.session_state['clip_mode'] = 'direct_cut'  # 默认原片直剪模式
    if 'uploaded_episodes' not in st.session_state:
        st.session_state['uploaded_episodes'] = []
    if 'highlight_segments' not in st.session_state:
        st.session_state['highlight_segments'] = []


# i18n 翻译缓存（避免每次调用都重新读文件）
_tr_cache: dict = {}
_tr_cache_lock = threading.Lock()

def tr(key):
    """翻译函数（带LRU缓存，避免重复读取文件）"""
    global _tr_cache
    lang = st.session_state.get('ui_language', 'zh_CN')
    cache_key = f"{lang}:{key}"
    
    # 加锁读取缓存，防止迭代时修改字典
    if cache_key in _tr_cache:
        return _tr_cache[cache_key]
    
    i18n_dir = os.path.join(os.path.dirname(__file__), "webui", "i18n")
    locales = utils.load_locales(i18n_dir)
    loc = locales.get(lang, {})
    result = loc.get("Translation", {}).get(key, key)
    
    # 加锁写入缓存
    with _tr_cache_lock:
        _tr_cache[cache_key] = result
        # 防止缓存无限增长（原子操作）
        if len(_tr_cache) > 500:
            _tr_cache = {k: v for k, v in list(_tr_cache.items())[-300:]}
    return result


def render_generate_button():
    """渲染生成按钮和处理逻辑"""
    if st.button(tr("Generate Video"), use_container_width=True, type="primary"):
        from app.services import task as tm
        from app.services import state as sm
        from app.models import const
        import threading
        import time
        import uuid

        config.save_config()

        clip_mode = st.session_state.get('clip_mode', 'direct_cut')

        # AI解说模式：脚本文件可选（无脚本走自动NarrationPipeline）
        if clip_mode == 'ai_narration':
            has_script = st.session_state.get('video_clip_json_path')
            if not has_script:
                # Auto narration mode: need video files
                if not video_paths and not single_path:
                    st.error(tr("AI解说模式（自动）需要上传视频文件"))
                    return

        # 两种模式都需要视频（支持单集和多集）
        video_paths = st.session_state.get('video_origin_paths', [])
        single_path = st.session_state.get('video_origin_path', '')

        # 直剪模式只需要有视频即可
        if clip_mode == 'direct_cut':
            if not video_paths and not single_path:
                st.error(tr("视频文件不能为空"))
                return
        else:
            # AI解说模式保持原有校验
            if not single_path:
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
            **subtitle_params,
            # DramaClip: 传递剪辑模式
            'clip_mode': st.session_state.get('clip_mode', 'direct_cut'),
            # DramaClip: 传递多集视频路径列表
            'video_origin_paths': st.session_state.get('video_origin_paths', []),
        }

        params = VideoClipParams(**all_params)
        task_id = str(uuid.uuid4())

        progress_bar = st.progress(0)
        status_text = st.empty()

        def run_task():
            try:
                tm.start_subclip_unified(
                    task_id=task_id,
                    params=params
                )
            except Exception as e:
                logger.error(f"任务执行失败: {e}")
                sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, message=str(e))

        thread = threading.Thread(target=run_task)
        thread.start()

        elapsed = 0.0
        max_wait = 7200  # 最长等待2小时（短剧剪辑通常不会超过这个时间）
        while True:
            task = sm.state.get_task(task_id)
            if task:
                progress = task.get("progress", 0)
                state = task.get("state")

                progress_bar.progress(progress / 100)
                status_text.text(f"Processing... {progress}%")

                if state == const.TASK_STATE_COMPLETE:
                    status_text.text(tr("视频生成完成"))
                    progress_bar.progress(1.0)

                    # Feed highlight segments to preview panel
                    seg_list = task.get("highlight_segments", [])
                    if seg_list:
                        st.session_state['highlight_segments'] = seg_list

                    video_files = task.get("videos", [])
                    try:
                        if video_files:
                            player_cols = st.columns(len(video_files) * 2 + 1)
                            for i, url in enumerate(video_files):
                                player_cols[i * 2 + 1].video(url)
                    except Exception as e:
                        logger.error(f"播放视频失败: {e}")

                    st.success(tr("视频生成完成"))
                    break

                elif state == const.TASK_STATE_FAILED:
                    st.error(f"任务失败: {task.get('message', 'Unknown error')}")
                    break

            time.sleep(0.5)
            elapsed += 0.5
            if elapsed > max_wait:
                st.warning("⚠️ 任务执行超时，请检查日志获取详情")
                break


def main():
    """主函数"""
    init_log()
    init_global_state()

    # 注册 LLM 提供商
    if 'llm_providers_registered' not in st.session_state:
        try:
            from app.services.llm.providers import register_all_providers
            register_all_providers()
            st.session_state['llm_providers_registered'] = True
            logger.info("LLM 提供商注册成功")
        except Exception as e:
            logger.error(f"LLM 初始化失败: {str(e)}")
            st.error(f"⚠️ LLM 初始化失败: {str(e)}\n\n请检查配置文件和依赖是否正确安装。")

    # FFmpeg硬件加速检测
    if 'hwaccel_logged' not in st.session_state:
        st.session_state['hwaccel_logged'] = False
    
    hwaccel_info = ffmpeg_utils.detect_hardware_acceleration()
    if not st.session_state['hwaccel_logged']:
        if hwaccel_info["available"]:
            logger.info(f"FFmpeg硬件加速: 可用 | 类型: {hwaccel_info['type']} | 编码器: {hwaccel_info['encoder']}")
        else:
            logger.warning(f"FFmpeg硬件加速不可用: {hwaccel_info['message']}, 使用CPU软件编码")
        st.session_state['hwaccel_logged'] = True

    # 初始化资源
    try:
        utils.init_resources()
    except Exception as e:
        logger.warning(f"资源初始化警告: {e}")

    # ===== DramaClip 主界面 =====
    st.title(f":blue[DramaClip] 🎬")
    st.caption(tr("短剧自动高光剪辑系统 — 单系统双模式"))

    # 模式选择面板（DramaClip 核心新增）
    mode_selector.render_mode_selector(tr)

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

    # 高光预览面板（DramaClip 核心新增）
    highlight_preview.render_highlight_panel(tr)

    # 系统设置
    with panel[2]:
        system_settings.render_system_panel(tr)

    # 生成按钮
    render_generate_button()


if __name__ == "__main__":
    main()
