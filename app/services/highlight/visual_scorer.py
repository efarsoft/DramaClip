"""
DramaClip - 画面特征分析器

基于 OpenCV 进行画面分析：
- 人脸检测与位置
- 特写镜头识别
- 人物动作/冲突检测
- 画面情绪标签
"""

import os
import numpy as np
from typing import Tuple, List, Optional, Dict
from loguru import logger


# ===== 常量定义（避免魔法数字）=====
BLURRY_THRESHOLD = 100          # Laplacian模糊阈值，低于此值认为画面模糊
CLOSEUP_RATIO_THRESHOLD = 0.15  # 特写判断：人脸占画面比例超过此值为特写


class VisualScorer:
    """
    画面特征评分器
    
    对镜头片段的视频帧进行画面分析，给出 0~1 的视觉精彩度得分。
    
    分析维度：
    1. 人脸因子 (30%) — 是否有人脸、人脸数量、大小
    2. 特写程度 (25%) — 是否为近景/特写（人物表情更清晰=更有感染力）
    3. 动作/冲突 (25%) — 检测肢体动作、运动模糊等
    4. 构图质量 (10%) — 画面稳定性、清晰度
    5. 镜头类型 (10%) — 特殊角度、转场效果
    """
    
    # Downscale width for face detection (speed vs accuracy trade-off)
    FACE_DETECT_WIDTH = 640

    def __init__(self, 
                 sample_fps: float = 0.5,
                 face_confidence: float = 0.5):
        """
        Args:
            sample_fps: Sampling rate in frames per second (default 0.5 = 1 frame per 2s)
            face_confidence: Face detection confidence threshold
        """
        self.sample_fps = sample_fps
        self.face_confidence = face_confidence
        self._cv_available = None
        self._face_cascade = None
    
    def _check_opencv(self) -> bool:
        """检查OpenCV是否可用"""
        if self._cv_available is not None:
            return self._cv_available
        
        try:
            import cv2
            self._cv_available = True
            
            # 加载 Haar 级联分类器（轻量级，无需深度学习模型）
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            if os.path.exists(cascade_path):
                self._face_cascade = cv2.CascadeClassifier(cascade_path)
            else:
                logger.warning(f"人脸检测模型未找到: {cascade_path}")
                self._face_cascade = None
                
            return True
        except ImportError:
            self._cv_available = False
            return False
    
    def score(self, video_path: str, 
              duration: Optional[float] = None) -> Tuple[float, dict]:
        """
        对视频文件进行画面评分
        
        Args:
            video_path: 视频文件路径
            duration: 视频时长(秒)，已知时传入可加速
            
        Returns:
            tuple: (得分0~1, 详细分析结果dict)
        """
        if not self._check_opencv():
            logger.warning("OpenCV不可用，使用简化版画面评分")
            return self._fallback_score(video_path)
        
        if not os.path.exists(video_path):
            logger.warning(f"视频文件不存在: {video_path}")
            return 0.0, {"error": "file_not_found"}
        
        try:
            import cv2
            
            cap = cv2.VideoCapture(video_path)
            try:
                if not cap.isOpened():
                    return 0.0, {"error": "video_open_failed"}
            
                # 获取视频信息
                video_duration = duration or (cap.get(cv2.CAP_PROP_FRAME_COUNT) / 
                                              max(1, cap.get(cv2.CAP_PROP_FPS)))
                video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                
                # Calculate sampling interval and seek frames directly
                interval = max(1, int(video_fps / self.sample_fps))
                
                # Collect sampled frames using seek (avoid decoding every frame)
                frames_data = []
                frame_idx = 0
                
                while True:
                    target_frame = frame_idx * interval
                    if target_frame >= total_frames:
                        break
                    
                    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                    ret, frame = cap.read()
                    if not ret:
                        break
                    
                    frame_info = self._analyze_frame(frame)
                    frames_data.append(frame_info)
                    
                    frame_idx += 1
                
                if not frames_data:
                    return 0.0, {"error": "no_frames"}
                
                # 聚合所有帧的评分结果
                result = self._aggregate_frames(frames_data, video_duration)
                
                return result["total_score"], result
            
            finally:
                cap.release()
            
        except Exception as e:
            logger.warning(f"画面分析失败(使用fallback): {e}")
            return 0.0, {"error": str(e)}
    
    def _analyze_frame(self, frame: np.ndarray) -> dict:
        """Analyze a single frame image"""
        import cv2
        
        info = {}
        orig_h, orig_w = frame.shape[:2]
        
        # ===== 1. 人脸检测 =====#
        faces = []
        face_center = None
        is_closeup = False
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Downscale for face detection (Haar cascade works fine at lower res)
        orig_h, orig_w = frame.shape[:2]
        scale = self.FACE_DETECT_WIDTH / max(1, orig_w)
        if scale < 1.0:
            small_gray = cv2.resize(gray, (self.FACE_DETECT_WIDTH, int(orig_h * scale)))
        else:
            small_gray = gray
        
        if self._face_cascade is not None:
            detected_faces = self._face_cascade.detectMultiScale(
                small_gray,
                scaleFactor=1.3,
                minNeighbors=5,
                minSize=(20, 20)  # Smaller minSize since we already downscaled
            )
            
            for (x, y, w, h) in detected_faces:
                # Map coordinates back to original resolution
                if scale < 1.0:
                    x, y, w, h = int(x / scale), int(y / scale), int(w / scale), int(h / scale)
                faces.append({
                    "x": int(x), "y": int(y),
                    "w": int(w), "h": int(h),
                    "center_x": (x + w/2) / orig_w,
                    "center_y": (y + h/2) / orig_h,
                    "size_ratio": (w * h) / (orig_w * orig_h),
                })
            
            if faces:
                # Pick the largest face center
                largest_face = max(faces, key=lambda f: f["size_ratio"])
                face_center = (largest_face["center_x"], largest_face["center_y"])
                
                # Closeup: face occupies > threshold of frame area
                is_closeup = largest_face["size_ratio"] > CLOSEUP_RATIO_THRESHOLD
        
        info["faces"] = faces
        info["face_count"] = len(faces)
        info["has_face"] = len(faces) > 0
        info["face_center"] = face_center
        info["is_closeup"] = is_closeup
        
        # ===== 2. 运动检测（帧差分）=====#
        info["brightness"] = float(np.mean(gray))
        info["contrast"] = float(np.std(gray))
        
        # 边缘检测（用于评估画面复杂度）
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.sum(edges > 0) / edges.size
        info["edge_density"] = float(edge_density)
        
        # ===== 3. 模糊检测（Laplacian方差）=====#
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        info["sharpness"] = float(laplacian_var)
        info["is_blurry"] = laplacian_var < BLURRY_THRESHOLD  # 模糊阈值
        
        return info
    
    def _aggregate_frames(self, frames_data: List[dict], duration: float) -> dict:
        """聚合多帧的分析结果"""
        n = len(frames_data)
        
        # 人脸相关统计
        face_ratios = [len(f.get("faces", [])) for f in frames_data]
        has_face_ratio = sum(1 for r in face_ratios if r > 0) / max(1, n)
        avg_face_count = sum(face_ratios) / max(1, n)
        
        closeup_ratios = [f.get("is_closeup", False) for f in frames_data]
        closeup_ratio = sum(closeup_ratios) / max(1, n)
        
        # 画面质量
        sharpness_values = [f.get("sharpness", 0) for f in frames_data]
        avg_sharpness = sum(sharpness_values) / max(1, n)
        blurry_ratio = sum(1 for s in sharpness_values if s < 100) / max(1, n)
        
        edge_densities = [f.get("edge_density", 0) for f in frames_data]
        avg_edge_density = sum(edge_densities) / max(1, n)
        
        # 人脸居中程度
        face_centers = [f.get("face_center") for f in frames_data if f.get("face_center")]
        center_score = 0.0
        if face_centers:
            # 计算人脸中心距离画面中心的平均偏差
            deviations = [(abs(cx - 0.5) + abs(cy - 0.5)) / 2 
                         for cx, cy in face_centers]
            center_score = 1.0 - min(1.0, sum(deviations) / len(face_centers))
        
        # ===== 各维度评分 =====#
        
        # 1. 人脸因子 (30%)
        face_score = (
            0.6 * has_face_ratio +      # 有人脸的帧占比
            0.3 * min(1.0, avg_face_count / 3) +  # 平均人脸数
            0.1 * center_score           # 居中程度
        )
        
        # 2. 特写程度 (25%)
        closeup_score = closeup_ratio  # 特写帧占比直接作为得分
        
        # 3. 画面动态/构图 (25%)
        # 边缘密度高 + 清晰度高 = 好的画面
        dynamic_score = (
            0.5 * min(1.0, avg_edge_density * 3) +
            0.3 * min(1.0, avg_sharpness / 500) +
            0.2 * (1 - blurry_ratio)
        )
        
        # 4. 综合质量 (20%)
        quality_score = (
            0.6 * (1 - blurry_ratio) +
            0.4 * min(1.0, avg_edge_density * 2)
        )
        
        # 总分
        total_score = (
            0.30 * face_score +
            0.25 * closeup_score +
            0.25 * dynamic_score +
            0.20 * quality_score
        )
        
        total_score = max(0.0, min(1.0, total_score))
        
        return {
            "total_score": round(total_score, 4),
            "face_score": round(face_score, 4),
            "closeup_score": round(closeup_score, 4),
            "dynamic_score": round(dynamic_score, 4),
            "quality_score": round(quality_score, 4),
            "has_face_ratio": round(has_face_ratio, 4),
            "avg_face_count": round(avg_face_count, 2),
            "closeup_ratio": round(closeup_ratio, 4),
            "avg_sharpness": round(avg_sharpness, 2),
            "blurry_ratio": round(blurry_ratio, 4),
            "frames_analyzed": n,
            "duration": round(duration, 2),
            "face_center": face_centers[0] if face_centers else None,
        }
    
    def _fallback_score(self, video_path: str) -> Tuple[float, dict]:
        """简化版评分（OpenCV不可用时）"""
        try:
            from moviepy import VideoFileClip
            
            clip = VideoFileClip(video_path)
            duration = clip.duration
            w, h = clip.size
            clip.close()
            
            # 基于分辨率和时长的基础评分
            resolution_factor = (w * h) / (1920 * 1080)
            duration_factor = min(1.0, duration / 5.0)
            
            score = 0.3 * min(1.0, resolution_factor) + 0.2 * duration_factor + 0.1
            
            details = {
                "total_score": round(score, 4),
                "method": "fallback_moviepy",
                "resolution": f"{w}x{h}",
                "duration": round(duration, 2),
            }
            
            return score, details
            
        except Exception as e:
            return 0.0, {"error": str(e), "method": "none"}
