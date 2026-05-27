"""
视觉分析服务

基于 OpenCV 分析视频画面特征：
- 亮度分析
- 运动强度检测
- 人脸检测
- 画面稳定性
"""

import json
import cv2
import numpy as np
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class VisualFrame:
    """单帧视觉特征"""
    timestamp: float
    brightness: float      # 亮度 0-1
    contrast: float        # 对比度 0-1
    motion_score: float    # 运动强度 0-1
    face_count: int        # 人脸数量
    face_score: float      # 人脸得分 0-1
    sharpness: float       # 清晰度 0-1


@dataclass
class VisualAnalysis:
    """视觉分析结果"""
    video_id: str
    duration: float
    avg_brightness: float
    avg_contrast: float
    avg_motion: float
    avg_sharpness: float
    total_faces: int
    face_ratio: float           # 有人脸的帧比例
    frame_scores: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "video_id": self.video_id,
            "duration": self.duration,
            "avg_brightness": self.avg_brightness,
            "avg_contrast": self.avg_contrast,
            "avg_motion": self.avg_motion,
            "avg_sharpness": self.avg_sharpness,
            "total_faces": self.total_faces,
            "face_ratio": self.face_ratio,
            "frame_scores": self.frame_scores,
        }


class VisualService:
    """
    视觉分析服务
    
    使用 OpenCV 分析视频画面特征
    """
    
    # 人脸检测器（Haar Cascade）
    _face_cascade: Optional[cv2.CascadeClassifier] = None
    
    def __init__(self):
        self._cancel_flag = False
        self._load_face_detector()
    
    def _load_face_detector(self):
        """加载人脸检测器"""
        try:
            # 使用 OpenCV 自带的 Haar Cascade
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'  # type: ignore
            self._face_cascade = cv2.CascadeClassifier(cascade_path)
            logger.info("人脸检测器已加载")
        except Exception as e:
            logger.warning(f"人脸检测器加载失败: {e}")
            self._face_cascade = None
    
    def cancel(self):
        """取消分析"""
        self._cancel_flag = True
    
    def analyze(
        self,
        video_path: str,
        video_id: str,
        sample_interval: float = 1.0,  # 每秒采样一帧
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> VisualAnalysis:
        """
        分析视频视觉特征
        
        Args:
            video_path: 视频文件路径
            video_id: 视频 ID
            sample_interval: 采样间隔（秒）
            progress_callback: 进度回调
            
        Returns:
            VisualAnalysis 视觉分析结果
        """
        self._cancel_flag = False
        
        if not Path(video_path).exists():
            logger.error(f"视频文件不存在: {video_path}")
            return self._create_empty_result(video_id)
        
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.error(f"无法打开视频: {video_path}")
                return self._create_empty_result(video_id)
            
            # 获取视频信息
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if fps > 0 else 0.0
            
            # 计算采样帧间隔
            sample_frame_interval = int(fps * sample_interval)
            if sample_frame_interval < 1:
                sample_frame_interval = 1
            
            logger.info(f"视觉分析: fps={fps:.1f}, frames={frame_count}, duration={duration:.1f}s, sample_interval={sample_interval}s")
            
            # 分析帧
            frame_scores: List[Dict] = []
            prev_gray: Optional[np.ndarray] = None
            frame_idx = 0
            
            while True:
                if self._cancel_flag:
                    logger.info("视觉分析已取消")
                    break
                
                # 采样分析
                if frame_idx % sample_frame_interval == 0:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    
                    timestamp = frame_idx / fps
                    
                    # 分析单帧
                    frame_result = self._analyze_frame(frame, prev_gray, timestamp)
                    frame_scores.append(frame_result)
                    
                    # 更新前一帧（用于运动检测）
                    prev_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    
                    # 进度回调
                    if progress_callback and len(frame_scores) % 5 == 0:
                        progress = min(95, int((frame_idx / frame_count) * 100))
                        progress_callback(progress, f"视觉分析: {int(timestamp)}/{int(duration)}秒...")
                else:
                    ret = cap.grab()
                    if not ret:
                        break
                
                frame_idx += 1
            
            cap.release()
            
            # 汇总结果
            return self._aggregate_results(video_id, duration, frame_scores)
            
        except Exception as e:
            logger.error(f"视觉分析失败: {e}")
            return self._create_empty_result(video_id)
    
    def _analyze_frame(
        self,
        frame: np.ndarray,
        prev_gray: Optional[np.ndarray],
        timestamp: float
    ) -> Dict:
        """
        分析单帧
        
        Returns:
            {
                "timestamp": float,
                "brightness": float,
                "contrast": float,
                "motion_score": float,
                "face_count": int,
                "face_score": float,
                "sharpness": float,
            }
        """
        # 转灰度
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 亮度 (均值归一化到 0-1)
        brightness = np.mean(gray) / 255.0
        
        # 对比度 (标准差归一化)
        contrast = np.std(gray) / 128.0
        contrast = min(1.0, contrast)
        
        # 清晰度 (Laplacian 方差)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        sharpness = np.var(laplacian)
        sharpness = min(1.0, sharpness / 5000.0)  # 归一化
        
        # 运动检测（帧差法）
        motion_score = 0.0
        if prev_gray is not None:
            # 计算帧差
            diff = cv2.absdiff(gray, prev_gray)
            motion_score = np.mean(diff) / 255.0
            motion_score = min(1.0, motion_score * 3)  # 放大
        
        # 人脸检测
        face_count = 0
        face_score = 0.0
        if self._face_cascade is not None:
            # 缩小图片加速检测
            small_gray = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
            faces = self._face_cascade.detectMultiScale(
                small_gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30)
            )
            face_count = len(faces)
            # 人脸得分：有人脸 = 1.0，无人脸 = 0.0
            face_score = 1.0 if face_count > 0 else 0.0
        
        return {
            "timestamp": timestamp,
            "brightness": round(brightness, 3),
            "contrast": round(contrast, 3),
            "motion_score": round(motion_score, 3),
            "face_count": face_count,
            "face_score": round(face_score, 3),
            "sharpness": round(sharpness, 3),
        }
    
    def _aggregate_results(
        self,
        video_id: str,
        duration: float,
        frame_scores: List[Dict]
    ) -> VisualAnalysis:
        """汇总帧分析结果"""
        if not frame_scores:
            return self._create_empty_result(video_id)
        
        # 计算平均值
        avg_brightness = float(np.mean([f["brightness"] for f in frame_scores]))
        avg_contrast = float(np.mean([f["contrast"] for f in frame_scores]))
        avg_motion = float(np.mean([f["motion_score"] for f in frame_scores]))
        avg_sharpness = float(np.mean([f["sharpness"] for f in frame_scores]))
        
        # 人脸统计
        total_faces = sum(f["face_count"] for f in frame_scores)
        face_frames = sum(1 for f in frame_scores if f["face_count"] > 0)
        face_ratio = face_frames / len(frame_scores) if frame_scores else 0.0
        
        return VisualAnalysis(
            video_id=video_id,
            duration=duration,
            avg_brightness=round(avg_brightness, 3),
            avg_contrast=round(avg_contrast, 3),
            avg_motion=round(avg_motion, 3),
            avg_sharpness=round(avg_sharpness, 3),
            total_faces=total_faces,
            face_ratio=round(face_ratio, 3),
            frame_scores=frame_scores,
        )
    
    def _create_empty_result(self, video_id: str) -> VisualAnalysis:
        """创建空结果"""
        return VisualAnalysis(
            video_id=video_id,
            duration=0.0,
            avg_brightness=0.5,
            avg_contrast=0.5,
            avg_motion=0.0,
            avg_sharpness=0.5,
            total_faces=0,
            face_ratio=0.0,
            frame_scores=[],
        )
    
    def get_frame_score_at_time(
        self,
        analysis: VisualAnalysis,
        timestamp: float,
        tolerance: float = 1.0
    ) -> Optional[Dict]:
        """
        获取指定时间点的视觉得分
        
        Args:
            analysis: 视觉分析结果
            timestamp: 时间戳（秒）
            tolerance: 容差（秒）
            
        Returns:
            该时间点的视觉特征字典
        """
        for frame in analysis.frame_scores:
            if abs(frame["timestamp"] - timestamp) <= tolerance:
                return frame
        return None
    
    def calculate_visual_score(
        self,
        brightness: float,
        contrast: float,
        motion: float,
        face_score: float,
        sharpness: float,
    ) -> float:
        """
        计算综合视觉得分
        
        权重：
        - 亮度适中（0.4-0.6）得分高
        - 对比度适中（0.3-0.7）得分高
        - 运动强度适中得分高
        - 有人脸得分高
        - 清晰度高得分高
        """
        # 亮度得分：越接近 0.5 越好
        brightness_score = 1.0 - abs(brightness - 0.5) * 2
        
        # 对比度得分
        contrast_score = min(1.0, contrast * 1.5)
        
        # 运动得分：适中最好
        motion_score = 1.0 - abs(motion - 0.4) * 1.5
        motion_score = max(0.0, motion_score)
        
        # 人脸得分
        face_score_weight = face_score
        
        # 清晰度得分
        sharpness_score = sharpness
        
        # 加权平均
        total_score = (
            brightness_score * 0.15 +
            contrast_score * 0.15 +
            motion_score * 0.25 +
            face_score_weight * 0.30 +
            sharpness_score * 0.15
        )
        
        return round(min(1.0, max(0.0, total_score)), 3)
    
    def save_result(self, result: VisualAnalysis, output_path: Path) -> None:
        """保存分析结果"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"视觉分析结果已保存: {output_path}")
    
    def load_result(self, result_path: Path) -> Optional[VisualAnalysis]:
        """加载分析结果"""
        if not result_path.exists():
            return None
        
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
            return VisualAnalysis(
                video_id=data.get("video_id", ""),
                duration=data.get("duration", 0.0),
                avg_brightness=data.get("avg_brightness", 0.5),
                avg_contrast=data.get("avg_contrast", 0.5),
                avg_motion=data.get("avg_motion", 0.0),
                avg_sharpness=data.get("avg_sharpness", 0.5),
                total_faces=data.get("total_faces", 0),
                face_ratio=data.get("face_ratio", 0.0),
                frame_scores=data.get("frame_scores", []),
            )
        except Exception as e:
            logger.error(f"加载视觉分析结果失败: {e}")
            return None


# 全局单例
_visual_service: Optional[VisualService] = None


def get_visual_service() -> VisualService:
    """获取全局视觉分析服务实例"""
    global _visual_service
    if _visual_service is None:
        _visual_service = VisualService()
    return _visual_service
