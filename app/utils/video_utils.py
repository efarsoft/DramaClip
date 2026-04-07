"""
DramaClip - 视频封面生成工具
"""

import os
from typing import Optional
from loguru import logger


def generate_video_cover(segments, output_dir: str, task_id: str,
                          video_getter=None) -> Optional[str]:
    """
    从视频片段中生成封面图
    
    Args:
        segments: 视频片段列表（需有 video_path 和 total_score 属性）
        output_dir: 输出目录
        task_id: 任务ID（用于文件名）
        video_getter: 可选的 cv2.VideoCapture getter，默认用 cv2
        
    Returns:
        封面图片路径，失败返回 None
    """
    if not segments:
        return None
    
    # 找得分最高的片段
    best_seg = max(segments, key=lambda s: getattr(s, 'total_score', 0) or 0)
    
    try:
        import cv2
        
        video_path = getattr(best_seg, 'video_path', None) or ""
        if not video_path:
            return None
            
        if video_getter is None:
            cap = cv2.VideoCapture(video_path)
        else:
            cap = video_getter(video_path)
        
        try:
            if cap.isOpened():
                start_time = getattr(best_seg, 'start_time', 0)
                fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                frame_pos = int(start_time * fps) + int(fps * 2)
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(1, frame_pos))
                ret, frame = cap.read()
                
                if ret:
                    cover_path = os.path.join(output_dir, f"cover_{task_id}.jpg")
                    cv2.imwrite(cover_path, frame)
                    return cover_path
        finally:
            cap.release()
                
    except Exception as e:
        logger.warning(f"封面生成失败: {e}")
    
    return None
