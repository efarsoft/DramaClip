"""
DramaClip - Mode Selector Component
Provides direct-cut / AI narration mode switching UI
"""

import streamlit as st


def render_mode_selector(tr):
    """
    Render mode selection panel with enhanced visual styling
    
    Args:
        tr: Translation function
    """
    # Mode selection card
    st.subheader("🎯 剪辑模式选择")
    
    selected = st.radio(
        "选择剪辑模式",
        options=[
            ("📹 原片直剪模式", "direct_cut"),
            ("🤖 AI解说模式", "ai_narration"),
        ],
        format_func=lambda x: x[0],
        index=0 if st.session_state.get('clip_mode', 'direct_cut') == 'direct_cut' else 1,
        horizontal=True,
        label_visibility="collapsed"
    )
    
    st.session_state['clip_mode'] = selected[1]
    
    # Mode description
    mode = st.session_state.get('clip_mode', 'direct_cut')
    if mode == 'direct_cut':
        st.info("""
        **📹 原片直剪模式**
        - ✅ 保留原片原声、背景音、BGM
        - ✅ 快速提取高光片段
        - ⚡ 处理速度快
        - 🎯 适用：名场面混剪、快速出片
        """)
    else:
        st.info("""
        **🤖 AI解说模式**  
        - ✅ AI解析剧情 + 生成解说文案
        - ✅ TTS合成自然语音
        - 📝 解说清晰、剧情连贯
        - 🎯 适用：剧情解说、吐槽点评
        """)
    
    # Output duration selector
    st.divider()
    duration_options = {
        15: "15秒 · 超短精华",
        30: "30秒 · 默认推荐 ⭐",
        45: "45秒 · 中等长度",
        60: "60秒 · 完整高光",
    }
    
    current_duration = st.session_state.get('output_duration', 30)
    
    selected_duration = st.select_slider(
        "⏱ 输出时长",
        options=list(duration_options.keys()),
        format_func=lambda x: duration_options[x],
        value=current_duration,
    )
    st.session_state['output_duration'] = selected_duration
