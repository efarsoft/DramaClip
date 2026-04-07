"""
DramaClip - Highlight Preview Component
Displays scored highlight segments with visual feedback
"""

import streamlit as st
import json


def render_highlight_panel(tr):
    """
    Render highlight segment preview panel with enhanced score visualization
    
    Args:
        tr: Translation function
    """
    st.subheader("✨ 高光片段预览")
    
    segments = st.session_state.get('highlight_segments', [])
    
    if not segments:
        st.info("📋 上传短剧并处理后，高光片段将显示在这里\n\n处理流程：上传视频 → 选择模式 → 自动识别高光 → 预览调整 → 生成成片")
        return
    
    total_duration = sum(s.get('duration', 0) for s in segments)
    avg_score = sum(s.get('score', 0) for s in segments) / len(segments) if segments else 0
    
    # Summary stats
    col1, col2 = st.columns(2)
    with col1:
        st.metric("片段数量", f"{len(segments)} 个")
    with col2:
        st.metric("总时长", f"{total_duration:.1f}s")
    
    st.divider()
    
    # Segment list with score color coding
    for i, seg in enumerate(segments):
        ep = seg.get('episode', '?')
        score = seg.get('score', 0)
        start = seg.get('start_time', 0)
        dur = seg.get('duration', 0)
        reason = seg.get('reason', '高光片段')
        
        # Score-based color indicator
        if score >= 0.7:
            score_emoji = "🔥"
            score_label = "精品"
        elif score >= 0.5:
            score_emoji = "⭐"
            score_label = "优质"
        elif score >= 0.3:
            score_emoji = "📊"
            score_label = "普通"
        else:
            score_emoji = "📋"
            score_label = "一般"
        
        col_idx, col_info, col_action = st.columns([1, 5, 1])
        
        with col_idx:
            st.metric(f"#{i+1}", f"{score:.2f}", delta=score_label)
        
        with col_info:
            st.write(f"**E{ep}** | {start:.1f}s - {start+dur:.1f}s | {dur:.1f}s")
            if reason and reason != '高光片段':
                st.caption(f"{score_emoji} {reason}")
        
        with col_action:
            if st.button("🗑️", key=f"del_seg_{i}", help="移除此片段"):
                segments = [s for j, s in enumerate(segments) if j != i]
                st.session_state['highlight_segments'] = segments
                st.rerun()
    
    # Action buttons
    st.divider()
    col_auto, col_manual = st.columns(2)
    with col_auto:
        if st.button("🔄 重新筛选", use_container_width=True):
            st.rerun()
    with col_manual:
        if st.button("✅ 确认片段", use_container_width=True, type="primary"):
            st.success(f"已确认 {len(segments)} 个高光片段，可开始生成成片")
