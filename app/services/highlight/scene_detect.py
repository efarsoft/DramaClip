"""
DramaClip - PySceneDetect 镜头分割器

使用 PySceneDetect 将短剧视频切割为独立的镜头片段（scene），
作为高光打分的基本单元。

输出：每个镜头的 [剧集号, 起始时间, 结束时间, 时长]
"""

import os
import json
import subprocess
from typing import List, Optional, Dict, Tuple
from loguru import logger
from dataclasses import dataclass, asdict


@dataclass
class SceneInfo:
    """镜头/场景信息"""
    episode_index: int       # 剧集序号(从1开始)
    scene_index: int         # 该集中的场景序号(从1开始)
    start_time: float        # 起始时间(秒)
    end_time: float          # 结束时间(秒)
    duration: float          # 时长(秒)
    video_path: str          # 原始视频路径
    
    def to_segment_id(self) -> str:
        """生成唯一ID"""
        return f"ep{self.episode_index}_scn{self.scene_index}_{self.start_time:.1f}s"


class SceneDetector:
    """
    镜头分割检测器
    
    基于 PySceneDetect 的 Content Detector 算法，
    自动识别视频中的场景切换点，将视频切分为多个镜头。
    
    使用方式：
        detector = SceneDetector(threshold=30)
        scenes = detector.detect("video.mp4", episode_index=1)
        # scenes -> [SceneInfo, SceneInfo, ...]
    """
    
    # PySceneDetect 可用性缓存
    _available = None
    
    def __init__(self,
                 threshold: int = 30,
                 min_scene_len: float = 2.0,
                 max_scene_len: float = 8.0,
                 detection_method: str = "content"):
        """
        Args:
            threshold: 场景检测阈值 (0-100), 越低越敏感
            min_scene_len: 最小场景长度(秒)
            max_scene_len: 最大场景长度(秒) — 超过此值会尝试二次切割
            detection_method: 检测方法 ("content"/"threshold"/"adaptive")
        """
        self.threshold = threshold
        self.min_scene_len = min_scene_len
        self.max_scene_len = max_scene_len
        self.detection_method = detection_method
    
    @classmethod
    def is_available(cls) -> bool:
        """检查 PySceneDetect 是否可用"""
        if cls._available is not None:
            return cls._available
        
        try:
            import scenedetect as pyscenedetect
            cls._available = True
            logger.info("PySceneDetect (scenedetect) 可用")
            return True
        except ImportError:
            cls._available = False
            logger.warning("PySceneDetect 未安装，将使用 FFmpeg 备选方案")
            return False
    
    def detect(self, 
               video_path: str, 
               episode_index: int = 1,
               progress_callback=None) -> List[SceneInfo]:
        """
        检测视频中的所有场景/镜头
        
        Args:
            video_path: 视频文件路径
            episode_index: 剧集序号
            progress_callback: 进度回调 function(progress_01, message)
            
        Returns:
            List[SceneInfo]: 所有检测到的场景列表
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        
        if progress_callback:
            progress_callback(0.05, f"正在分析视频 E{episode_index}...")
        
        # 优先使用 PySceneDetect
        if self.is_available():
            try:
                return self._detect_with_pyscenedetect(
                    video_path, episode_index, progress_callback
                )
            except Exception as e:
                logger.warning(f"PySceneDetect 检测失败: {e}, 回退到 FFmpeg 方案")
        
        # 回退方案：基于 FFmpeg 的简单场景检测
        return self._detect_with_ffmpeg(video_path, episode_index, progress_callback)
    
    def _detect_with_pyscenedetect(self,
                                    video_path: str,
                                    episode_index: int,
                                    progress_callback=None) -> List[SceneInfo]:
        """使用 PySceneDetect 进行专业级场景检测"""
        from scenedetect import VideoManager, SceneManager
        from scenedetect.detectors import ContentDetector
        
        if progress_callback:
            progress_callback(0.10, f"E{episode_index} - 使用 PySceneDetect 分析...")
        
        # 创建 VideoManager
        video_manager = VideoManager([video_path])
        
        try:
            # 设置帧跳过参数（提高速度）
            video_manager.set_downscale_factor(2)  # 降低分辨率以加速
            video_manager.start()
            
            # 创建场景管理器和检测器
            scene_manager = SceneManager()
            scene_manager.add_detector(
                ContentDetector(
                    threshold=self.threshold,
                    min_scene_len=int(self.min_scene_len * 30)  # 帧数
                )
            )
            
            # 执行检测
            if progress_callback:
                progress_callback(0.20, f"E{episode_index} - 正在扫描画面...")
            
            scene_manager.detect_scenes(frame_source=video_manager)
            
            # 获取结果
            scene_list = scene_manager.get_scene_list()
        finally:
            try:
                video_manager.release()
            except Exception:
                pass
        
        if not scene_list:
            logger.warning(f"E{episode_index}: 未检测到任何场景切换点")
            # 返回整个视频作为一个场景
            duration = self._get_video_duration(video_path)
            return [SceneInfo(
                episode_index=episode_index,
                scene_index=1,
                start_time=0.0,
                end_time=duration,
                duration=duration,
                video_path=video_path,
            )]
        
        # 转换为 SceneInfo 列表
        scenes = []
        
        # PySceneDetect 返回 FrameTimecode 对象，需正确提取秒数
        for i, (start_tc, end_tc) in enumerate(scene_list):
            # FrameTimecode 对象有 get_seconds() 方法，或可直接用 float() 转换
            try:
                start_time = float(start_tc.get_seconds()) if hasattr(start_tc, 'get_seconds') else float(start_tc)
                end_time = float(end_tc.get_seconds()) if hasattr(end_tc, 'get_seconds') else float(end_tc)
            except (TypeError, AttributeError):
                # 兼容旧版：如果返回的是帧号数字
                video_fps = self._get_video_fps(video_path)
                start_time = float(start_tc) / video_fps
                end_time = float(end_tc) / video_fps
            
            duration = end_time - start_time
            
            # 过滤过短的场景
            if duration < self.min_scene_len:
                continue
            
            # 尝试拆分过长的场景
            if duration > self.max_scene_len:
                sub_scenes = self._split_long_scene(
                    video_path, start_time, end_time,
                    episode_index, i + len(scenes) + 1
                )
                scenes.extend(sub_scenes)
            else:
                scene = SceneInfo(
                    episode_index=episode_index,
                    scene_index=i + 1 + len(scenes),
                    start_time=start_time,
                    end_time=end_time,
                    duration=duration,
                    video_path=video_path,
                )
                scenes.append(scene)
        
        if progress_callback:
            progress_callback(1.0, f"E{episode_index} - 完成! 检测到 {len(scenes)} 个镜头")
        
        logger.debug(f"E{episode_index}: PySceneDetect 检测到 {len(scenes)} 个镜头片段")
        return scenes
    
    def _detect_with_ffmpeg(self,
                             video_path: str,
                             episode_index: int,
                             progress_callback=None) -> List[SceneInfo]:
        """
        回退方案：使用 FFmpeg 进行基础场景检测
        
        通过检测场景变化（帧差分超过阈值的时刻）来近似模拟场景切换。
        """
        try:
            import cv2
        except ImportError:
            logger.error("OpenCV (cv2) 未安装，无法使用 FFmpeg 回退方案进行场景检测")
            raise RuntimeError("需要安装 opencv-python: pip install opencv-python")
        
        if progress_callback:
            progress_callback(0.10, f"E{episode_index} - 使用 FFmpeg/CV2 方案...")
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"无法打开视频: {video_path}")
        
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 60.0
            
            # 每 N 帧采样一次进行场景变化检测
            sample_interval = max(1, int(fps))  # 每秒采1帧
            
            prev_frame = None
            change_points = [0.0]  # 第一个场景从0开始
            
            current_pos = 0
            frame_idx = 0
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                if frame_idx % sample_interval == 0:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    gray = cv2.GaussianBlur(gray, (11, 11), 0)
                    
                    if prev_frame is not None:
                        # 计算帧差
                        diff = cv2.absdiff(prev_frame, gray)
                        mean_diff = diff.mean()
                        
                        # 如果差异超过阈值，标记为场景切换
                        if mean_diff > self.threshold * 2.5:
                            change_time = frame_idx / fps
                            # 避免太密集的切换点
                            if not change_points or (change_time - change_points[-1]) >= self.min_scene_len:
                                change_points.append(change_time)
                    
                    prev_frame = gray
                    
                    # 进度更新
                    if progress_callback and frame_idx % (sample_interval * 5) == 0:
                        prog = min(0.9, 0.2 + 0.7 * (frame_idx / total_frames))
                        progress_callback(prog, f"E{episode_index} - 扫描中... {frame_idx}/{total_frames}")
                
                frame_idx += 1
        
        finally:
            cap.release()
        
        # 确保最后一个时间点是视频结尾
        if not change_points or abs(change_points[-1] - duration) > 1.0:
            change_points.append(duration)
        
        # 构建 SceneInfo 列表
        scenes = []
        for i in range(len(change_points) - 1):
            start_time = change_points[i]
            end_time = change_points[i + 1]
            dur = end_time - start_time
            
            if dur < self.min_scene_len:
                continue
            
            if dur > self.max_scene_len:
                sub_scenes = self._split_long_scene(
                    video_path, start_time, end_time,
                    episode_index, i + len(scenes) + 1
                )
                scenes.extend(sub_scenes)
            else:
                scenes.append(SceneInfo(
                    episode_index=episode_index,
                    scene_index=i + 1 + len(scenes),
                    start_time=start_time,
                    end_time=end_time,
                    duration=dur,
                    video_path=video_path,
                ))
        
        if progress_callback:
            progress_callback(1.0, f"E{episode_index} - 完成! 检测到 {len(scenes)} 个镜头")
        
        logger.info(f"E{episode_index}: FFmpeg回退方案检测到 {len(scenes)} 个镜头片段")
        return scenes
    
    def _split_long_scene(self,
                           video_path: str,
                           start_time: float,
                           end_time: float,
                           episode_index: int,
                           base_scene_index: int) -> List[SceneInfo]:
        """将过长场景按固定间隔切分"""
        duration = end_time - start_time
        split_interval = self.max_scene_len  # 按 max_scene_len 为单位切分
        
        sub_scenes = []
        current_start = start_time
        scene_num = base_scene_index
        
        while current_start < end_time:
            current_end = min(current_start + split_interval, end_time)
            
            if current_end - current_start >= self.min_scene_len:
                sub_scenes.append(SceneInfo(
                    episode_index=episode_index,
                    scene_index=scene_num,
                    start_time=current_start,
                    end_time=current_end,
                    duration=current_end - current_start,
                    video_path=video_path,
                ))
                scene_num += 1
            
            current_start = current_end
        
        return sub_scenes
    
    def _get_video_duration(self, video_path: str) -> float:
        """获取视频时长"""
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            cap.release()
            return frames / fps if fps > 0 else 60.0
        except Exception:
            return 60.0


def detect_all_episodes(video_paths: List[str],
                        config: dict = None,
                        progress_callback=None) -> List[SceneInfo]:
    """
    批量检测多集短剧的所有镜头片段
    
    Args:
        video_paths: 视频文件路径列表（按剧集顺序）
        config: 配置字典 {threshold, min_scene_len, max_scene_len}
        progress_callback: 进度回调 function(progress_01, message)
        
    Returns:
        List[SceneInfo]: 所有序集的所有镜头片段
    """
    cfg = config or {}
    detector = SceneDetector(
        threshold=cfg.get("threshold", 30),
        min_scene_len=cfg.get("min_scene_len", 2.0),
        max_scene_len=cfg.get("max_scene_len", 8.0),
    )
    
    all_scenes: List[SceneInfo] = []
    total_episodes = len(video_paths)
    
    for idx, path in enumerate(video_paths):
        ep_idx = idx + 1
        
        def make_ep_progress(ep_i, total):
            def cb(prog, msg):
                if progress_callback:
                    overall = ((ep_i - 1) + prog) / total
                    progress_callback(overall, f"[E{ep_i}/{total}] {msg}")
            return cb
        
        try:
            scenes = detector.detect(path, episode_index=ep_idx, 
                                     progress_callback=make_ep_progress(ep_idx, total_episodes))
            all_scenes.extend(scenes)
        except Exception as e:
            logger.error(f"E{ep_idx} 镜头检测失败: {e}")
            # 整个视频作为一个场景兜底
            all_scenes.append(SceneInfo(
                episode_index=ep_idx,
                scene_index=1,
                start_time=0.0,
                end_time=detector._get_video_duration(path),
                duration=detector._get_video_duration(path),
                video_path=path,
            ))
    
    logger.info(f"全部检测完成: {total_episodes} 集, 共 {len(all_scenes)} 个镜头片段")
    return all_scenes
