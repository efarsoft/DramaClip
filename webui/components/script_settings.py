import os
import glob
import json
import time
import traceback
import streamlit as st
from loguru import logger

from app.config import config
from app.models.schema import VideoClipParams
from app.services.subtitle_text import decode_subtitle_bytes
from app.utils import utils, check_script
# generate_script_docu 已移除（DramaClip 不需要画面解说模式）
# 原函数保留为空实现以兼容调用
def generate_script_docu(params):
    """画面解说脚本生成（已弃用，保留接口兼容）"""
    st.warning("画面解说模式暂不可用，请选择其他模式")
    logger.warning("generate_script_docu called but module removed")
from webui.tools.generate_script_short import generate_script_short
from webui.tools.generate_short_summary import generate_script_short_sunmmary


def render_script_panel(tr):
    """渲染脚本配置面板"""
    with st.container(border=True):
        st.write(tr("Video Script Configuration"))
        params = VideoClipParams()

        # 渲染脚本文件选择
        render_script_file(tr, params)

        # 渲染视频文件选择
        render_video_file(tr, params)

        # 获取当前选择的脚本类型
        script_path = st.session_state.get('video_clip_json_path', '')

        # 根据脚本类型显示不同的布局
        if script_path == "auto":
            # 画面解说
            render_video_details(tr)
        elif script_path == "short":
            # 短剧混剪
            render_short_generate_options(tr)
        elif script_path == "summary":
            # 短剧解说
            short_drama_summary(tr)
        else:
            # 默认为空
            pass

        # 渲染脚本操作按钮
        render_script_buttons(tr, params)


def render_script_file(tr, params):
    """渲染脚本文件选择"""
    # 定义功能模式
    MODE_FILE = "file_selection"
    MODE_AUTO = "auto"
    MODE_SHORT = "short"
    MODE_SUMMARY = "summary"

    # 处理保存脚本后的模式切换（必须在 widget 实例化之前）
    if st.session_state.get('_switch_to_file_mode'):
        st.session_state['script_mode_selection'] = tr("Select/Upload Script")
        del st.session_state['_switch_to_file_mode']

    # 模式选项映射
    mode_options = {
        tr("Select/Upload Script"): MODE_FILE,
        tr("Auto Generate"): MODE_AUTO,
        tr("Short Generate"): MODE_SHORT,
        tr("Short Drama Summary"): MODE_SUMMARY,
    }
    
    # 获取当前状态
    current_path = st.session_state.get('video_clip_json_path', '')
    
    # 确定当前选中的模式索引
    default_index = 0
    mode_keys = list(mode_options.keys())
    
    if current_path == "auto":
        default_index = mode_keys.index(tr("Auto Generate"))
    elif current_path == "short":
        default_index = mode_keys.index(tr("Short Generate"))
    elif current_path == "summary":
        default_index = mode_keys.index(tr("Short Drama Summary"))
    else:
        default_index = mode_keys.index(tr("Select/Upload Script"))

    # 1. 渲染功能选择下拉框
    # 使用 segmented_control 替代 selectbox，提供更好的视觉体验
    default_mode_label = mode_keys[default_index]
    
    # 定义回调函数来处理状态更新
    def update_script_mode():
        # 获取当前选中的标签
        selected_label = st.session_state.script_mode_selection
        if selected_label:
            # 更新实际的 path 状态
            new_mode = mode_options[selected_label]
            st.session_state.video_clip_json_path = new_mode
            params.video_clip_json_path = new_mode
        else:
            # 如果用户取消选择（segmented_control 允许取消），恢复到默认或上一个状态
            # 这里我们强制保持当前状态，或者重置为默认
            st.session_state.script_mode_selection = default_mode_label

    # 渲染组件
    selected_mode_label = st.segmented_control(
        tr("Video Type"),
        options=mode_keys,
        default=default_mode_label,
        key="script_mode_selection",
        on_change=update_script_mode
    )
    
    # 处理未选择的情况（虽然有default，但在某些交互下可能为空）
    if not selected_mode_label:
        selected_mode_label = default_mode_label
        
    selected_mode = mode_options[selected_mode_label]

    # 2. 根据选择的模式处理逻辑
    if selected_mode == MODE_FILE:
        # --- 文件选择模式 ---
        script_list = [
            (tr("None"), ""),
            (tr("Upload Script"), "upload_script")
        ]

        # 获取已有脚本文件
        suffix = "*.json"
        script_dir = utils.script_dir()
        files = glob.glob(os.path.join(script_dir, suffix))
        file_list = []

        for file in files:
            file_list.append({
                "name": os.path.basename(file),
                "file": file,
                "ctime": os.path.getctime(file)
            })

        file_list.sort(key=lambda x: x["ctime"], reverse=True)
        for file in file_list:
            display_name = file['file'].replace(config.root_dir, "")
            script_list.append((display_name, file['file']))

        # 找到保存的脚本文件在列表中的索引
        # 如果当前path是特殊值(auto/short/summary)，则重置为空
        saved_script_path = current_path if current_path not in [MODE_AUTO, MODE_SHORT, MODE_SUMMARY] else ""
        
        selected_index = 0
        for i, (_, path) in enumerate(script_list):
            if path == saved_script_path:
                selected_index = i
                break

        # 如果找到了保存的脚本，同步更新 selectbox 的 key 状态
        if saved_script_path and selected_index > 0:
            st.session_state['script_file_selection'] = selected_index

        selected_script_index = st.selectbox(
            tr("Script Files"),
            index=selected_index,
            options=range(len(script_list)),
            format_func=lambda x: script_list[x][0],
            key="script_file_selection"
        )

        script_path = script_list[selected_script_index][1]
        # 只有当用户实际选择了脚本时才更新路径，避免覆盖已保存的路径
        if script_path:
            st.session_state['video_clip_json_path'] = script_path
            params.video_clip_json_path = script_path
        elif saved_script_path:
            # 如果用户选择了 "None" 但之前有保存的脚本，保持原有路径
            st.session_state['video_clip_json_path'] = saved_script_path
            params.video_clip_json_path = saved_script_path

        # 处理脚本上传
        if script_path == "upload_script":
            uploaded_file = st.file_uploader(
                tr("Upload Script File"),
                type=["json"],
                accept_multiple_files=False,
            )

            if uploaded_file is not None:
                try:
                    # 读取上传的JSON内容并验证格式
                    script_content = uploaded_file.read().decode('utf-8')
                    json_data = json.loads(script_content)

                    # 保存到脚本目录
                    safe_filename = os.path.basename(uploaded_file.name)
                    script_file_path = os.path.join(script_dir, safe_filename)
                    file_name, file_extension = os.path.splitext(safe_filename)

                    # 如果文件已存在,添加时间戳
                    if os.path.exists(script_file_path):
                        timestamp = time.strftime("%Y%m%d%H%M%S")
                        file_name_with_timestamp = f"{file_name}_{timestamp}"
                        script_file_path = os.path.join(script_dir, file_name_with_timestamp + file_extension)

                    # 写入文件
                    with open(script_file_path, "w", encoding='utf-8') as f:
                        json.dump(json_data, f, ensure_ascii=False, indent=2)

                    # 更新状态
                    st.success(tr("Script Uploaded Successfully"))
                    st.session_state['video_clip_json_path'] = script_file_path
                    params.video_clip_json_path = script_file_path
                    time.sleep(1)
                    st.rerun()

                except json.JSONDecodeError:
                    st.error(tr("Invalid JSON format"))
                except Exception as e:
                    st.error(f"{tr('Upload failed')}: {str(e)}")
    else:
        # --- 功能生成模式 ---
        st.session_state['video_clip_json_path'] = selected_mode
        params.video_clip_json_path = selected_mode


def _natural_sort_key(s):
    """自然排序 key：把字符串中的数字提取出来作为排序依据"""
    import re
    parts = re.split(r'(\d+)', s)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def _collect_video_files_from_dir(folder_path: str) -> list:
    """从文件夹中递归收集所有支持格式的视频文件"""
    supported_exts = ('.mp4', '.mov', '.avi', '.flv', '.mkv', '.wmv', '.webm')
    found = []
    try:
        for root, _, files in os.walk(folder_path):
            for f in sorted(files, key=lambda x: _natural_sort_key(x)):
                if f.lower().endswith(supported_exts):
                    found.append(os.path.join(root, f))
    except Exception as e:
        logger.warning(f"遍历文件夹失败: {folder_path}, {e}")
    return found


def _save_uploaded_files(uploaded_files, video_dir: str) -> list:
    """批量保存上传的文件，返回保存后的路径列表"""
    saved_paths = []
    for uploaded_file in uploaded_files:
        safe_filename = os.path.basename(uploaded_file.name)
        video_file_path = os.path.join(video_dir, safe_filename)
        file_name, file_extension = os.path.splitext(safe_filename)

        if os.path.exists(video_file_path):
            timestamp = time.strftime("%Y%m%d%H%M%S")
            file_name_with_timestamp = f"{file_name}_{timestamp}"
            video_file_path = os.path.join(video_dir, file_name_with_timestamp + file_extension)

        with open(video_file_path, "wb") as f:
            f.write(uploaded_file.read())
        saved_paths.append(video_file_path)
    return saved_paths


def _get_duration_seconds(video_path: str) -> float:
    """通过 ffprobe 获取视频时长（秒），失败返回 0"""
    try:
        import subprocess
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return float(result.stdout.strip()) if result.stdout.strip() else 0.0
    except Exception:
        return 0.0


def render_video_file(tr, params):
    """
    渲染视频文件选择 - DramaClip 多集短剧版本
    支持三种输入方式：
    1. 多文件上传（批量上传 N 集短剧）
    2. 文件夹上传（选择整部短剧文件夹，自动按文件名排序）
    3. 历史文件选择（从已上传文件中选择）
    """
    st.divider()
    st.subheader("📁 " + tr("Video Files") + "（多集支持）")

    video_dir = utils.video_dir()
    supported_exts = ["mp4", "mov", "avi", "flv", "mkv"]

    # ---- 初始化 session_state ----
    if 'episode_paths' not in st.session_state:
        st.session_state['episode_paths'] = []   # [{'path': str, 'name': str, 'duration': float}, ...]
    if 'episode_input_mode' not in st.session_state:
        st.session_state['episode_input_mode'] = "files"   # "files" | "folder"

    # ---- 顶部模式切换 tabs ----
    tabs = st.tabs(["📤 多文件上传", "📂 文件夹上传", "📁 历史文件"])

    # =============================================
    # Tab 0: 多文件上传
    # =============================================
    with tabs[0]:
        uploaded_files = st.file_uploader(
            "拖拽或点击上传短剧文件（可多选）",
            type=supported_exts,
            accept_multiple_files=True,
            key="multi_file_uploader"
        )

        if uploaded_files:
            new_paths = _save_uploaded_files(uploaded_files, video_dir)
            existing = {ep['path'] for ep in st.session_state['episode_paths']}
            for p in new_paths:
                if p not in existing:
                    dur = _get_duration_seconds(p)
                    st.session_state['episode_paths'].append({
                        'path': p,
                        'name': os.path.basename(p),
                        'duration': dur
                    })
            if new_paths:
                st.success(f"✅ 已添加 {len(new_paths)} 个文件！")

        st.caption("已上传说明：支持 MP4 / MOV / AVI / FLV / MKV，单文件 ≤ 200MB，建议单集时长 1~5 分钟")

    # =============================================
    # Tab 1: 文件夹上传
    # =============================================
    with tabs[1]:
        folder_path = st.text_input(
            "短剧文件夹路径",
            placeholder="例如：D:\\MyDramas\\霸道总裁爱上我",
            help="填入短剧所在文件夹路径，系统将自动扫描并按文件名排序添加所有视频文件",
            key="folder_path_input"
        )

        col_add, col_scan = st.columns(2)
        with col_add:
            add_folder_clicked = st.button("📂 扫描并添加", use_container_width=True)
        with col_scan:
            if st.button("🔍 仅扫描预览（不添加）", use_container_width=True):
                if folder_path and os.path.isdir(folder_path):
                    found = _collect_video_files_from_dir(folder_path)
                    if found:
                        st.info(f"在「{os.path.basename(folder_path)}」中找到 {len(found)} 个视频：")
                        for fp in found:
                            st.write(f"  • {os.path.basename(fp)}")
                    else:
                        st.warning("未找到任何支持格式的视频文件")
                else:
                    st.error("文件夹路径无效，请检查路径是否正确")

        if add_folder_clicked:
            if not folder_path:
                st.error("请先输入文件夹路径")
            elif not os.path.isdir(folder_path):
                st.error("文件夹不存在，请检查路径是否正确")
            else:
                found = _collect_video_files_from_dir(folder_path)
                if not found:
                    st.warning("未找到任何支持格式的视频文件")
                else:
                    # 按文件名自然排序（支持 E01.mp4, E02.mp4 ...）
                    found_sorted = sorted(found, key=lambda x: _natural_sort_key(os.path.basename(x)))
                    existing = {ep['path'] for ep in st.session_state['episode_paths']}
                    added = 0
                    for p in found_sorted:
                        if p not in existing:
                            dur = _get_duration_seconds(p)
                            st.session_state['episode_paths'].append({
                                'path': p,
                                'name': os.path.basename(p),
                                'duration': dur
                            })
                            added += 1
                    st.success(f"✅ 已从文件夹添加 {added} 个视频文件！")

    # =============================================
    # Tab 2: 历史文件
    # =============================================
    with tabs[2]:
        # 收集历史文件
        history_list = []
        for suffix in ["*.mp4", "*.mov", "*.avi", "*.flv", "*.mkv"]:
            for f in glob.glob(os.path.join(video_dir, suffix)):
                history_list.append(f)
        history_list.sort(key=lambda x: os.path.getmtime(x), reverse=True)

        if history_list:
            # 分页展示，每页20个
            page_size = 20
            total_pages = max(1, (len(history_list) + page_size - 1) // page_size)
            page = st.number_input(
                f"历史文件（共 {len(history_list)} 个）", min_value=1,
                max_value=total_pages, value=1, step=1,
                key="history_page"
            )
            start_i = (page - 1) * page_size
            page_items = history_list[start_i:start_i + page_size]

            selected_to_add = st.multiselect(
                "选择文件（可多选）",
                options=page_items,
                default=[],
                format_func=lambda x: os.path.basename(x),
                key="history_multiselect"
            )
            if st.button("➕ 添加选中文件", use_container_width=True):
                if selected_to_add:
                    existing = {ep['path'] for ep in st.session_state['episode_paths']}
                    added = 0
                    for p in selected_to_add:
                        if p not in existing:
                            dur = _get_duration_seconds(p)
                            st.session_state['episode_paths'].append({
                                'path': p,
                                'name': os.path.basename(p),
                                'duration': dur
                            })
                            added += 1
                    st.success(f"✅ 已添加 {added} 个文件！")
        else:
            st.info("暂无历史文件，请通过「多文件上传」或「文件夹上传」添加短剧")

    # =============================================
    # 已添加剧集列表（所有 tab 共用）
    # =============================================
    st.divider()
    episodes = st.session_state['episode_paths']

    if episodes:
        # 按文件名自然排序
        episodes_sorted = sorted(episodes, key=lambda x: _natural_sort_key(x['name']))

        total_dur = sum(ep.get('duration', 0) for ep in episodes_sorted)
        total_min = int(total_dur // 60)
        total_sec = int(total_dur % 60)
        st.success(
            f"✅ 已添加 {len(episodes_sorted)} 集短剧，"
            f"总时长约 {total_min}分{total_sec}秒"
        )

        # 逐集展示，可单独删除
        for i, ep in enumerate(episodes_sorted):
            ep_name = ep['name']
            ep_dur = ep.get('duration', 0)
            dur_str = f"{int(ep_dur // 60):02d}:{int(ep_dur % 60):02d}" if ep_dur > 0 else "未知时长"

            col_info, col_del = st.columns([6, 1])
            with col_info:
                st.write(
                    f"**E{i+1:02d}** `{ep_name}` "
                    f"<span style='color:gray'>⏱ {dur_str}</span>",
                    unsafe_allow_html=True
                )
            with col_del:
                if st.button("🗑", key=f"del_ep_{i}", help="移除此集"):
                    # 用路径匹配删除（避免遍历中 pop(i) 索引偏移问题）
                    target_path = ep['path']
                    st.session_state['episode_paths'] = [
                        e for e in st.session_state['episode_paths']
                        if e['path'] != target_path
                    ]
                    st.rerun()

        # 全量清理
        if st.button("🗑 清空全部", type="secondary"):
            st.session_state['episode_paths'] = []
            st.rerun()

        # 同步到 session_state（供后端使用）
        paths_list = [ep['path'] for ep in episodes_sorted]
        st.session_state['video_origin_path'] = paths_list[0] if paths_list else ""
        st.session_state['video_origin_paths'] = paths_list
        params.video_origin_path = paths_list[0] if paths_list else ""
        params.video_origin_paths = paths_list

    else:
        st.info("👆 请通过上方任一方式添加短剧集（支持 1~N 集）")
        st.session_state['video_origin_path'] = ""
        st.session_state['video_origin_paths'] = []
        params.video_origin_path = ""
        params.video_origin_paths = []


def render_short_generate_options(tr):
    """
    渲染Short Generate模式下的特殊选项
    在Short Generate模式下，替换原有的输入框为自定义片段选项
    """
    short_drama_summary(tr)
    # 显示自定义片段数量选择器
    custom_clips = st.number_input(
        tr("自定义片段"),
        min_value=1,
        max_value=20,
        value=st.session_state.get('custom_clips', 5),
        help=tr("设置需要生成的短视频片段数量"),
        key="custom_clips_input"
    )
    st.session_state['custom_clips'] = custom_clips


def render_video_details(tr):
    """画面解说 渲染视频主题和提示词"""
    video_theme = st.text_input(tr("Video Theme"))
    custom_prompt = st.text_area(
        tr("Generation Prompt"),
        value=st.session_state.get('video_plot', ''),
        help=tr("Custom prompt for LLM, leave empty to use default prompt"),
        height=180
    )
    # 非短视频模式下显示原有的三个输入框
    input_cols = st.columns(3)

    with input_cols[0]:
        st.number_input(
            tr("Frame Interval (seconds)"),
            min_value=0,
            value=st.session_state.get('frame_interval_input', config.frames.get('frame_interval_input', 3)),
            help=tr("Frame Interval (seconds) (More keyframes consume more tokens)"),
            key="frame_interval_input"
        )

    with input_cols[1]:
        st.number_input(
            tr("Batch Size"),
            min_value=0,
            value=st.session_state.get('vision_batch_size', config.frames.get('vision_batch_size', 10)),
            help=tr("Batch Size (More keyframes consume more tokens)"),
            key="vision_batch_size"
        )

    with input_cols[2]:
        target_dur = st.selectbox(
            tr("Target Duration (s)"),
            options=[15, 30, 45, 60, 90, 120, 180, 240, 300],
            index=1,  # 默认 30s
            help=tr("目标输出时长：15s~5min（多集模式下高光将均匀分配到各集）"),
            key="target_duration"
        )
        # selectbox 已通过 key 自动写入 session_state，无需重复赋值

    st.session_state['video_theme'] = video_theme
    st.session_state['custom_prompt'] = custom_prompt
    return video_theme, custom_prompt


def short_drama_summary(tr):
    """短剧解说 渲染视频主题和提示词"""
    # 检查是否已经处理过字幕文件
    if 'subtitle_file_processed' not in st.session_state:
        st.session_state['subtitle_file_processed'] = False
    
    subtitle_file = st.file_uploader(
        tr("上传字幕文件"),
        type=["srt"],
        accept_multiple_files=False,
        key="subtitle_file_uploader"  # 添加唯一key
    )
    
    # 显示当前已上传的字幕文件路径
    if 'subtitle_path' in st.session_state and st.session_state['subtitle_path']:
        st.info(f"已上传字幕: {os.path.basename(st.session_state['subtitle_path'])}")
        if st.button(tr("清除已上传字幕")):
            st.session_state['subtitle_path'] = None
            st.session_state['subtitle_content'] = None
            st.session_state['subtitle_file_processed'] = False
            st.rerun()
    
    # 只有当有文件上传且尚未处理时才执行处理逻辑
    if subtitle_file is not None and not st.session_state['subtitle_file_processed']:
        try:
            # 清理文件名，防止路径污染和路径遍历攻击
            safe_filename = os.path.basename(subtitle_file.name)

            decoded = decode_subtitle_bytes(subtitle_file.getvalue())
            script_content = decoded.text
            detected_encoding = decoded.encoding

            if not script_content:
                st.error(tr("无法读取字幕文件，请检查文件编码（支持 UTF-8、UTF-16、GBK、GB2312）"))
                st.stop()

            # 验证字幕内容（简单检查）
            if len(script_content.strip()) < 10:
                st.warning(tr("字幕文件内容似乎为空，请检查文件"))

            # 保存到字幕目录
            script_file_path = os.path.join(utils.subtitle_dir(), safe_filename)
            file_name, file_extension = os.path.splitext(safe_filename)

            # 如果文件已存在,添加时间戳
            if os.path.exists(script_file_path):
                timestamp = time.strftime("%Y%m%d%H%M%S")
                file_name_with_timestamp = f"{file_name}_{timestamp}"
                script_file_path = os.path.join(utils.subtitle_dir(), file_name_with_timestamp + file_extension)

            # 直接写入SRT内容（统一使用 UTF-8）
            with open(script_file_path, "w", encoding='utf-8') as f:
                f.write(script_content)

            # 更新状态
            st.success(
                f"{tr('字幕上传成功')} "
                f"(编码: {detected_encoding.upper()}, "
                f"大小: {len(script_content)} 字符)"
            )
            st.session_state['subtitle_path'] = script_file_path
            st.session_state['subtitle_content'] = script_content
            st.session_state['subtitle_file_processed'] = True  # 标记已处理

            # 避免使用rerun，使用更新状态的方式
            # st.rerun()

        except Exception as e:
            st.error(f"{tr('Upload failed')}: {str(e)}")

    # 名称输入框
    video_theme = st.text_input(tr("短剧名称"))
    st.session_state['video_theme'] = video_theme
    # 数字输入框
    temperature = st.slider("temperature", 0.0, 2.0, 0.7)
    st.session_state['temperature'] = temperature
    return video_theme


def render_script_buttons(tr, params):
    """渲染脚本操作按钮"""
    # 获取当前选择的脚本类型
    script_path = st.session_state.get('video_clip_json_path', '')

    # 生成/加载按钮
    if script_path == "auto":
        button_name = tr("Generate Video Script")
    elif script_path == "short":
        button_name = tr("Generate Short Video Script")
    elif script_path == "summary":
        button_name = tr("生成短剧解说脚本")
    elif script_path.endswith("json"):
        button_name = tr("Load Video Script")
    else:
        button_name = tr("Please Select Script File")

    if st.button(button_name, key="script_action", disabled=not script_path):
        if script_path == "auto":
            # 执行纪录片视频脚本生成（视频无字幕无配音）
            generate_script_docu(params)
        elif script_path == "short":
            # 执行 短剧混剪 脚本生成
            custom_clips = st.session_state.get('custom_clips')
            generate_script_short(tr, params, custom_clips)
        elif script_path == "summary":
            # 执行 短剧解说 脚本生成
            subtitle_path = st.session_state.get('subtitle_path')
            video_theme = st.session_state.get('video_theme')
            temperature = st.session_state.get('temperature')
            generate_script_short_sunmmary(params, subtitle_path, video_theme, temperature)
        else:
            load_script(tr, script_path)

    # 视频脚本编辑区
    video_clip_json_details = st.text_area(
        tr("Video Script"),
        value=json.dumps(st.session_state.get('video_clip_json', []), indent=2, ensure_ascii=False),
        height=500
    )

    # 操作按钮行 - 合并格式检查和保存功能
    if st.button(tr("Save Script"), key="save_script", use_container_width=True):
        save_script_with_validation(tr, video_clip_json_details)


def load_script(tr, script_path):
    """加载脚本文件"""
    try:
        with open(script_path, 'r', encoding='utf-8') as f:
            script = f.read()
            script = utils.clean_model_output(script)
            st.session_state['video_clip_json'] = json.loads(script)
            st.success(tr("Script loaded successfully"))
            st.rerun()
    except Exception as e:
        logger.error(f"加载脚本文件时发生错误\n{traceback.format_exc()}")
        st.error(f"{tr('Failed to load script')}: {str(e)}")


def save_script_with_validation(tr, video_clip_json_details):
    """保存视频脚本（包含格式验证）"""
    if not video_clip_json_details:
        st.error(tr("请输入视频脚本"))
        st.stop()

    # 第一步：格式验证
    with st.spinner("正在验证脚本格式..."):
        try:
            result = check_script.check_format(video_clip_json_details)
            if not result.get('success'):
                # 格式验证失败，显示详细错误信息
                error_message = result.get('message', '未知错误')
                error_details = result.get('details', '')

                st.error(f"**脚本格式验证失败**")
                st.error(f"**错误信息：** {error_message}")
                if error_details:
                    st.error(f"**详细说明：** {error_details}")

                # 显示正确格式示例
                st.info("**正确的脚本格式示例：**")
                example_script = [
                    {
                        "_id": 1,
                        "timestamp": "00:00:00,600-00:00:07,559",
                        "picture": "工地上，蔡晓艳奋力救人，场面混乱",
                        "narration": "灾后重建，工地上险象环生！泼辣女工蔡晓艳挺身而出，救人第一！",
                        "OST": 0
                    },
                    {
                        "_id": 2,
                        "timestamp": "00:00:08,240-00:00:12,359",
                        "picture": "领导视察，蔡晓艳不屑一顾",
                        "narration": "播放原片4",
                        "OST": 1
                    }
                ]
                st.code(json.dumps(example_script, ensure_ascii=False, indent=2), language='json')
                st.stop()

        except Exception as e:
            st.error(f"格式验证过程中发生错误: {str(e)}")
            st.stop()

    # 第二步：保存脚本
    with st.spinner(tr("Save Script")):
        script_dir = utils.script_dir()
        timestamp = time.strftime("%Y-%m%d-%H%M%S")
        save_path = os.path.join(script_dir, f"{timestamp}.json")

        try:
            data = json.loads(video_clip_json_details)
            with open(save_path, 'w', encoding='utf-8') as file:
                json.dump(data, file, ensure_ascii=False, indent=4)
                st.session_state['video_clip_json'] = data
                st.session_state['video_clip_json_path'] = save_path
                
                # 标记需要切换到文件选择模式（在下次渲染前处理）
                st.session_state['_switch_to_file_mode'] = True

                # 更新配置
                config.app["video_clip_json_path"] = save_path

                # 显示成功消息
                st.success("✅ 脚本格式验证通过，保存成功！")

                # 强制重新加载页面更新选择框
                time.sleep(0.5)  # 给一点时间让用户看到成功消息
                st.rerun()

        except Exception as err:
            st.error(f"{tr('Failed to save script')}: {str(err)}")
            st.stop()


# crop_video函数已移除 - 现在使用统一裁剪策略，不再需要预裁剪步骤


def get_script_params():
    """获取脚本参数"""
    return {
        'video_language': st.session_state.get('video_language', ''),
        'video_clip_json_path': st.session_state.get('video_clip_json_path', ''),
        'video_origin_path': st.session_state.get('video_origin_path', ''),
        'video_origin_paths': st.session_state.get('video_origin_paths', []),
        'video_name': st.session_state.get('video_name', ''),
        'video_plot': st.session_state.get('video_plot', ''),
        'target_duration': st.session_state.get('target_duration', 30),
        'vision_llm_provider': st.session_state.get('vision_llm_provider', 'gemini'),
    }
