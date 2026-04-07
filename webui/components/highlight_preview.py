"""
DramaClip - 高光片段预览组件
展示打分后的高光片段，支持手动调整顺序
"""

import streamlit as st
import json


def render_highlight_panel(tr):
    """
    渲染高光片段预览面板
    
    Args:
        tr: 翻译函数
    """
    with st.container(border=True):
        st.subheader("✨ 高光片段预览")
        
        segments = st.session_state.get('highlight_segments', [])
        
        if not segments:
            st.info("📋 上传短剧并处理后，高光片段将显示在这里\n\n处理流程：上传视频 → 选择模式 → 自动识别高光 → 预览调整 → 生成成片")
            return
        
        st.write(f"共 **{len(segments)}** 个高光片段 | 总时长: **{sum(s.get('duration', 0) for s in segments):.1f}** 秒")
        
        # 显示片段列表
        for i, seg in enumerate(segments):
            ep = seg.get('episode', '?')
            score = seg.get('score', 0)
            start = seg.get('start_time', 0)
            dur = seg.get('duration', 0)
            
            col_score, col_info, col_action = st.columns([1, 4, 1])
            
            with col_score:
                # 分数可视化
                score_color = "green" if score >= 0.7 else "orange" if score >= 0.4 else "gray"
                st.metric(f"#{i+1}", f"{score:.2f}", delta=None)
            
            with col_info:
                st.write(f"**E{ep}** | {start:.1f}s - {start+dur:.1f}s | {dur:.1f}s")
                st.caption(seg.get('reason', '高光片段'))
            
            with col_action:
                if st.button("🗑️", key=f"del_seg_{i}", help="移除此片段"):
                    # 使用列表推导安全删除（避免遍历中pop导致索引错乱）
                    segments = [s for j, s in enumerate(segments) if j != i]
                    st.session_state['highlight_segments'] = segments
                    st.rerun()
        
        # 操作按钮
        col_auto, col_manual = st.columns(2)
        with col_auto:
            if st.button("🔄 重新筛选", use_container_width=True):
                st.rerun()
        with col_manual:
            if st.button("✅ 确认片段", use_container_width=True, type="primary"):
                st.success(f"已确认 {len(segments)} 个高光片段，可开始生成成片")
