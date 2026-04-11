"""
FFmpeg 工具模块 - 提供 FFmpeg 相关的工具函数，特别是硬件加速检测
优化多平台兼容性，支持渐进式降级和智能错误处理
"""
import os
import platform
import subprocess
import threading
import tempfile
from typing import Dict, List, Optional, Tuple, Union, Any
from loguru import logger

# 全局变量，存储检测到的硬件加速信息
_FFMPEG_HW_ACCEL_INFO = {
    "available": False,
    "type": None,
    "encoder": None,
    "hwaccel_args": [],
    "message": "",
    "is_dedicated_gpu": False,
    "fallback_available": False,  # 是否有备用方案
    "fallback_encoder": None,     # 备用编码器
    "platform": None,             # 平台信息
    "gpu_vendor": None,           # GPU厂商
    "tested_methods": []          # 已测试的方法
}
# 线程锁，保护 _FFMPEG_HW_ACCEL_INFO 的并发访问
_FFMPEG_LOCK = threading.Lock()

# 硬件加速优先级配置（按平台和GPU类型）
HWACCEL_PRIORITY = {
    "windows": {
        "nvidia": ["cuda", "nvenc", "d3d11va", "dxva2"],
        "amd": ["d3d11va", "dxva2", "amf"],  # 不再完全禁用AMD
        "intel": ["qsv", "d3d11va", "dxva2"],
        "unknown": ["d3d11va", "dxva2"]
    },
    "darwin": {
        "apple": ["videotoolbox"],
        "nvidia": ["cuda", "videotoolbox"],
        "amd": ["videotoolbox"],
        "intel": ["videotoolbox"],
        "unknown": ["videotoolbox"]
    },
    "linux": {
        "nvidia": ["cuda", "nvenc", "vaapi"],
        "amd": ["vaapi", "amf"],
        "intel": ["qsv", "vaapi"],
        "unknown": ["vaapi"]
    }
}

# 编码器映射
ENCODER_MAPPING = {
    "cuda": "h264_nvenc",
    "nvenc": "h264_nvenc",
    "videotoolbox": "h264_videotoolbox",
    "qsv": "h264_qsv",
    "vaapi": "h264_vaapi",
    "amf": "h264_amf",
    "d3d11va": "libx264",  # D3D11VA只用于解码
    "dxva2": "libx264",    # DXVA2只用于解码
    "software": "libx264"
}


def get_null_input() -> str:
    """
    获取平台特定的空输入文件路径

    Returns:
        str: 平台特定的空输入路径
    """
    system = platform.system().lower()
    if system == "windows":
        return "NUL"
    else:
        return "/dev/null"


def create_test_video() -> str:
    """
    创建一个临时的测试视频文件，用于硬件加速测试

    Returns:
        str: 临时测试视频文件路径
    """
    try:
        # 创建临时文件
        temp_file = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
        temp_path = temp_file.name
        temp_file.close()

        # 生成一个简单的测试视频（1秒，黑色画面）
        cmd = [
            'ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=black:size=320x240:duration=1',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-t', '1', temp_path
        ]

        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return temp_path
    except Exception as e:
        logger.debug(f"创建测试视频失败: {str(e)}")
        return get_null_input()


def cleanup_test_video(path: str) -> None:
    """
    清理测试视频文件

    Args:
        path: 测试视频文件路径
    """
    try:
        if path != get_null_input() and os.path.exists(path):
            os.unlink(path)
    except Exception as e:
        logger.debug(f"清理测试视频失败: {str(e)}")


def check_ffmpeg_installation() -> bool:
    """
    检查ffmpeg是否已安装

    Returns:
        bool: 如果安装则返回True，否则返回False
    """
    try:
        # 在Windows系统上使用UTF-8编码
        is_windows = os.name == 'nt'
        if is_windows:
            subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', check=True)
        else:
            subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        logger.error("ffmpeg未安装或不在系统PATH中，请安装ffmpeg")
        return False


def detect_gpu_vendor() -> str:
    """
    检测GPU厂商

    Returns:
        str: GPU厂商 (nvidia, amd, intel, apple, unknown)
    """
    system = platform.system().lower()

    try:
        if system == "windows":
            gpu_info = _get_windows_gpu_info().lower()
            if 'nvidia' in gpu_info or 'geforce' in gpu_info or 'quadro' in gpu_info:
                return "nvidia"
            elif 'amd' in gpu_info or 'radeon' in gpu_info:
                return "amd"
            elif 'intel' in gpu_info:
                return "intel"
        elif system == "darwin":
            # macOS上检查是否为Apple Silicon
            if platform.machine().lower() in ['arm64', 'aarch64']:
                return "apple"
            else:
                # Intel Mac，可能有独立显卡
                gpu_info = _get_macos_gpu_info().lower()
                if 'nvidia' in gpu_info:
                    return "nvidia"
                elif 'amd' in gpu_info or 'radeon' in gpu_info:
                    return "amd"
                else:
                    return "intel"
        elif system == "linux":
            gpu_info = _get_linux_gpu_info().lower()
            if 'nvidia' in gpu_info:
                return "nvidia"
            elif 'amd' in gpu_info or 'radeon' in gpu_info:
                return "amd"
            elif 'intel' in gpu_info:
                return "intel"
    except Exception as e:
        logger.debug(f"检测GPU厂商失败: {str(e)}")

    return "unknown"


def test_hwaccel_method(method: str, test_input: str) -> bool:
    """
    测试特定的硬件加速方法

    Args:
        method: 硬件加速方法名称
        test_input: 测试输入文件路径

    Returns:
        bool: 是否支持该方法
    """
    try:
        # 构建测试命令
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]

        # 添加硬件加速参数
        if method == "cuda":
            cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])
        elif method == "nvenc":
            cmd.extend(["-hwaccel", "cuda"])
        elif method == "videotoolbox":
            cmd.extend(["-hwaccel", "videotoolbox"])
        elif method == "qsv":
            cmd.extend(["-hwaccel", "qsv"])
        elif method == "vaapi":
            # 尝试找到VAAPI设备
            render_device = _find_vaapi_device()
            if render_device:
                cmd.extend(["-hwaccel", "vaapi", "-vaapi_device", render_device])
            else:
                cmd.extend(["-hwaccel", "vaapi"])
        elif method == "d3d11va":
            cmd.extend(["-hwaccel", "d3d11va"])
        elif method == "dxva2":
            cmd.extend(["-hwaccel", "dxva2"])
        elif method == "amf":
            cmd.extend(["-hwaccel", "auto"])  # AMF通常通过auto检测
        else:
            return False

        # 添加输入和输出
        cmd.extend(["-i", test_input, "-f", "null", "-t", "0.1", "-"])

        # 执行测试
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=10  # 10秒超时
        )

        success = result.returncode == 0
        if success:
            logger.debug(f"硬件加速方法 {method} 测试成功")
        else:
            logger.debug(f"硬件加速方法 {method} 测试失败: {result.stderr[:200]}")

        return success

    except subprocess.TimeoutExpired:
        logger.debug(f"硬件加速方法 {method} 测试超时")
        return False
    except Exception as e:
        logger.debug(f"硬件加速方法 {method} 测试异常: {str(e)}")
        return False


def detect_hardware_acceleration() -> Dict[str, Union[bool, str, List[str], None]]:
    """
    Detect available hardware accelerators with progressive detection and fallback.

    Returns:
        Dict: Hardware acceleration information
    """
    global _FFMPEG_HW_ACCEL_INFO

    # P1-9: Prevent recursive re-entry (e.g., _get_gpu_info -> ... -> detect)
    if not hasattr(detect_hardware_acceleration, "_detecting"):
        detect_hardware_acceleration._detecting = False
    if detect_hardware_acceleration._detecting:
        logger.warning("Recursive detect_hardware_acceleration() call blocked")
        return _FFMPEG_HW_ACCEL_INFO

    # If already detected, return cached result (lock-free fast path)
    if _FFMPEG_HW_ACCEL_INFO["type"] is not None:
        return _FFMPEG_HW_ACCEL_INFO

    # P1-7: Thread-safe detection with lock
    with _FFMPEG_LOCK:
        # Double-check after acquiring lock
        if _FFMPEG_HW_ACCEL_INFO["type"] is not None:
            return _FFMPEG_HW_ACCEL_INFO

        detect_hardware_acceleration._detecting = True
        try:
            return _do_detect_hardware_acceleration()
        finally:
            detect_hardware_acceleration._detecting = False


def _do_detect_hardware_acceleration() -> Dict[str, Union[bool, str, List[str], None]]:
    """Internal: actual hardware acceleration detection logic (called under lock)."""
    global _FFMPEG_HW_ACCEL_INFO

    # Check FFmpeg installation
    if not check_ffmpeg_installation():
        _FFMPEG_HW_ACCEL_INFO["message"] = "FFmpeg not installed or not in PATH"
        return _FFMPEG_HW_ACCEL_INFO

    # 检测平台和GPU信息
    system = platform.system().lower()
    gpu_vendor = detect_gpu_vendor()

    _FFMPEG_HW_ACCEL_INFO["platform"] = system
    _FFMPEG_HW_ACCEL_INFO["gpu_vendor"] = gpu_vendor

    logger.debug(f"检测硬件加速 - 平台: {system}, GPU厂商: {gpu_vendor}")

    # 获取FFmpeg支持的硬件加速器列表
    try:
        hwaccels_cmd = subprocess.run(
            ['ffmpeg', '-hide_banner', '-hwaccels'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
        )
        supported_hwaccels = hwaccels_cmd.stdout.lower() if hwaccels_cmd.returncode == 0 else ""
        logger.debug(f"FFmpeg支持的硬件加速器: {supported_hwaccels}")
    except Exception as e:
        logger.warning(f"获取FFmpeg硬件加速器列表失败: {str(e)}")
        supported_hwaccels = ""

    # 创建测试输入
    test_input = create_test_video()

    try:
        # 根据平台和GPU厂商获取优先级列表
        priority_list = HWACCEL_PRIORITY.get(system, {}).get(gpu_vendor, [])
        if not priority_list:
            priority_list = HWACCEL_PRIORITY.get(system, {}).get("unknown", [])

        logger.debug(f"硬件加速测试优先级: {priority_list}")

        # 按优先级测试硬件加速方法
        for method in priority_list:
            # 检查FFmpeg是否支持该方法
            if method not in supported_hwaccels and method != "nvenc":  # nvenc可能不在hwaccels列表中
                logger.debug(f"跳过不支持的硬件加速方法: {method}")
                continue

            _FFMPEG_HW_ACCEL_INFO["tested_methods"].append(method)

            if test_hwaccel_method(method, test_input):
                # 找到可用的硬件加速方法
                _FFMPEG_HW_ACCEL_INFO["available"] = True
                _FFMPEG_HW_ACCEL_INFO["type"] = method
                _FFMPEG_HW_ACCEL_INFO["encoder"] = ENCODER_MAPPING.get(method, "libx264")

                # 构建硬件加速参数
                if method == "cuda":
                    _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
                elif method == "nvenc":
                    _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = ["-hwaccel", "cuda"]
                elif method == "videotoolbox":
                    _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = ["-hwaccel", "videotoolbox"]
                elif method == "qsv":
                    _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = ["-hwaccel", "qsv"]
                elif method == "vaapi":
                    render_device = _find_vaapi_device()
                    if render_device:
                        _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = ["-hwaccel", "vaapi", "-vaapi_device", render_device]
                    else:
                        _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = ["-hwaccel", "vaapi"]
                elif method in ["d3d11va", "dxva2"]:
                    _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = ["-hwaccel", method]
                elif method == "amf":
                    _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = ["-hwaccel", "auto"]

                # 判断是否为独立GPU
                _FFMPEG_HW_ACCEL_INFO["is_dedicated_gpu"] = gpu_vendor in ["nvidia", "amd"] or (gpu_vendor == "intel" and "arc" in _get_gpu_info().lower())

                _FFMPEG_HW_ACCEL_INFO["message"] = f"使用 {method} 硬件加速 ({gpu_vendor} GPU)"
                logger.debug(f"硬件加速检测成功: {method} ({gpu_vendor})")
                break

        # 如果没有找到硬件加速，设置软件编码作为备用
        if not _FFMPEG_HW_ACCEL_INFO["available"]:
            _FFMPEG_HW_ACCEL_INFO["fallback_available"] = True
            _FFMPEG_HW_ACCEL_INFO["fallback_encoder"] = "libx264"
            _FFMPEG_HW_ACCEL_INFO["message"] = f"未找到可用的硬件加速，将使用软件编码 (平台: {system}, GPU: {gpu_vendor})"
            logger.debug("未检测到硬件加速，将使用软件编码")

    finally:
        # 清理测试文件
        cleanup_test_video(test_input)

    return _FFMPEG_HW_ACCEL_INFO


def _get_gpu_info() -> str:
    """
    获取GPU信息的统一接口

    Returns:
        str: GPU信息字符串
    """
    system = platform.system().lower()

    if system == "windows":
        return _get_windows_gpu_info()
    elif system == "darwin":
        return _get_macos_gpu_info()
    elif system == "linux":
        return _get_linux_gpu_info()
    else:
        return "unknown"


def _get_macos_gpu_info() -> str:
    """
    获取macOS系统的GPU信息

    Returns:
        str: GPU信息字符串
    """
    try:
        # 使用system_profiler获取显卡信息
        result = subprocess.run(
            ['system_profiler', 'SPDisplaysDataType'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
        )
        if result.returncode == 0:
            return result.stdout

        # 备用方法：检查是否为Apple Silicon
        if platform.machine().lower() in ['arm64', 'aarch64']:
            return "Apple Silicon GPU"
        else:
            return "Intel Mac GPU"
    except Exception as e:
        logger.debug(f"获取macOS GPU信息失败: {str(e)}")
        return "unknown"


def _find_vaapi_device() -> Optional[str]:
    """
    查找可用的VAAPI设备

    Returns:
        Optional[str]: VAAPI设备路径，如果没有找到则返回None
    """
    try:
        # 常见的VAAPI设备路径
        possible_devices = [
            "/dev/dri/renderD128",
            "/dev/dri/renderD129",
            "/dev/dri/card0",
            "/dev/dri/card1"
        ]

        for device in possible_devices:
            if os.path.exists(device):
                # 测试设备是否可用
                test_cmd = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-loglevel", "error",
                     "-hwaccel", "vaapi", "-vaapi_device", device,
                     "-f", "lavfi", "-i", "color=black:size=64x64:duration=0.1",
                     "-f", "null", "-"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
                )
                if test_cmd.returncode == 0:
                    logger.debug(f"找到可用的VAAPI设备: {device}")
                    return device

        logger.debug("未找到可用的VAAPI设备")
        return None
    except Exception as e:
        logger.debug(f"查找VAAPI设备失败: {str(e)}")
        return None


def _detect_macos_acceleration(supported_hwaccels: str) -> None:
    """
    检测macOS系统的硬件加速

    Args:
        supported_hwaccels: FFmpeg支持的硬件加速器列表
    """
    global _FFMPEG_HW_ACCEL_INFO

    if 'videotoolbox' in supported_hwaccels:
        # 测试videotoolbox
        try:
            test_cmd = subprocess.run(
                ["ffmpeg", "-hwaccel", "videotoolbox", "-i", "/dev/null", "-f", "null", "-"],
                stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, check=False
            )
            if test_cmd.returncode == 0:
                _FFMPEG_HW_ACCEL_INFO["available"] = True
                _FFMPEG_HW_ACCEL_INFO["type"] = "videotoolbox"
                _FFMPEG_HW_ACCEL_INFO["encoder"] = "h264_videotoolbox"
                _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = ["-hwaccel", "videotoolbox"]
                # macOS的Metal GPU加速通常是集成GPU
                _FFMPEG_HW_ACCEL_INFO["is_dedicated_gpu"] = False
                return
        except Exception as e:
            logger.debug(f"测试videotoolbox失败: {str(e)}")

    _FFMPEG_HW_ACCEL_INFO["message"] = "macOS系统未检测到可用的videotoolbox硬件加速"


def _detect_windows_acceleration(supported_hwaccels: str) -> None:
    """
    检测Windows系统的硬件加速 - 基于实际测试结果优化
    
    重要发现：CUDA硬件解码在视频裁剪场景下会导致滤镜链错误，
    因此优先使用纯NVENC编码器方案，既保证性能又确保兼容性。
    
    Args:
        supported_hwaccels: FFmpeg支持的硬件加速器列表
    """
    global _FFMPEG_HW_ACCEL_INFO
    
    # 在Windows上，首先检查显卡信息
    gpu_info = _get_windows_gpu_info()
    logger.debug(f"Windows GPU信息: {gpu_info}")
    
    # 检查是否为Intel集成显卡
    is_intel_integrated = False
    if 'intel' in gpu_info.lower() and ('hd graphics' in gpu_info.lower() or 'uhd graphics' in gpu_info.lower()):
        logger.info("检测到Intel集成显卡")
        is_intel_integrated = True
    
    # 1. 优先检测NVIDIA硬件加速 - 基于实际测试的最佳方案
    if 'nvidia' in gpu_info.lower() or 'geforce' in gpu_info.lower() or 'quadro' in gpu_info.lower():
        logger.info("检测到NVIDIA显卡，开始测试硬件加速")
        
        # 检查NVENC编码器是否可用
        try:
            encoders_cmd = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                stderr=subprocess.PIPE, stdout=subprocess.PIPE, 
                encoding='utf-8', text=True, check=False
            )
            has_nvenc = "h264_nvenc" in encoders_cmd.stdout.lower()
            logger.debug(f"NVENC编码器检测结果: {'可用' if has_nvenc else '不可用'}")
            
            if has_nvenc:
                # 优先方案：纯NVENC编码器（测试证明最兼容）
                logger.debug("测试纯NVENC编码器（推荐方案，避免滤镜链问题）")
                test_cmd = subprocess.run([
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=duration=0.1:size=640x480:rate=30",
                    "-c:v", "h264_nvenc", "-preset", "medium", "-cq", "23",
                    "-pix_fmt", "yuv420p", "-f", "null", "-"
                ], stderr=subprocess.PIPE, stdout=subprocess.PIPE, 
                   encoding='utf-8', text=True, check=False)
                
                if test_cmd.returncode == 0:
                    _FFMPEG_HW_ACCEL_INFO["available"] = True
                    _FFMPEG_HW_ACCEL_INFO["type"] = "nvenc"  # 使用nvenc类型标识纯编码器
                    _FFMPEG_HW_ACCEL_INFO["encoder"] = "h264_nvenc"
                    _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = []  # 不使用硬件解码参数
                    _FFMPEG_HW_ACCEL_INFO["is_dedicated_gpu"] = True
                    _FFMPEG_HW_ACCEL_INFO["message"] = "纯NVENC编码器（最佳兼容性）"
                    logger.info("✓ 纯NVENC编码器测试成功")
                    return
                
                # 备用方案：如果需要的话，可以测试CUDA硬件解码（但不推荐用于视频裁剪）
                if 'cuda' in supported_hwaccels:
                    logger.debug("测试CUDA硬件解码（仅用于非裁剪场景）")
                    test_cmd = subprocess.run([
                        "ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                        "-f", "lavfi", "-i", "testsrc=duration=0.1:size=640x480:rate=30",
                        "-c:v", "h264_nvenc", "-preset", "medium", "-cq", "23",
                        "-pix_fmt", "yuv420p", "-f", "null", "-"
                    ], stderr=subprocess.PIPE, stdout=subprocess.PIPE, 
                       encoding='utf-8', text=True, check=False)
                    
                    if test_cmd.returncode == 0:
                        _FFMPEG_HW_ACCEL_INFO["available"] = True
                        _FFMPEG_HW_ACCEL_INFO["type"] = "cuda"  # 保留cuda类型用于特殊场景
                        _FFMPEG_HW_ACCEL_INFO["encoder"] = "h264_nvenc"
                        _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
                        _FFMPEG_HW_ACCEL_INFO["is_dedicated_gpu"] = True
                        _FFMPEG_HW_ACCEL_INFO["message"] = "CUDA+NVENC（限特殊场景使用）"
                        _FFMPEG_HW_ACCEL_INFO["fallback_available"] = True
                        _FFMPEG_HW_ACCEL_INFO["fallback_encoder"] = "h264_nvenc"
                        logger.info("✓ CUDA+NVENC硬件加速测试成功（备用方案）")
                        return
                        
        except Exception as e:
            logger.debug(f"NVIDIA硬件加速测试失败: {str(e)}")
    
    # 2. 检测AMD硬件加速
    if 'amd' in gpu_info.lower() or 'radeon' in gpu_info.lower():
        logger.info("检测到AMD显卡，开始测试硬件加速")
        
        # 检查AMF编码器是否可用
        try:
            encoders_cmd = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                stderr=subprocess.PIPE, stdout=subprocess.PIPE, 
                encoding='utf-8', text=True, check=False
            )
            has_amf = "h264_amf" in encoders_cmd.stdout.lower()
            logger.debug(f"AMF编码器检测结果: {'可用' if has_amf else '不可用'}")
            
            if has_amf:
                # 测试AMF编码器
                logger.debug("测试AMF编码器")
                test_cmd = subprocess.run([
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=duration=0.1:size=640x480:rate=30",
                    "-c:v", "h264_amf", "-quality", "balanced", "-qp_i", "23",
                    "-pix_fmt", "yuv420p", "-f", "null", "-"
                ], stderr=subprocess.PIPE, stdout=subprocess.PIPE, 
                   encoding='utf-8', text=True, check=False)
                
                if test_cmd.returncode == 0:
                    _FFMPEG_HW_ACCEL_INFO["available"] = True
                    _FFMPEG_HW_ACCEL_INFO["type"] = "amf"
                    _FFMPEG_HW_ACCEL_INFO["encoder"] = "h264_amf"
                    _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = []
                    _FFMPEG_HW_ACCEL_INFO["is_dedicated_gpu"] = True
                    _FFMPEG_HW_ACCEL_INFO["message"] = "AMD AMF编码器"
                    logger.info("✓ AMD AMF编码器测试成功")
                    return
                    
        except Exception as e:
            logger.debug(f"AMD硬件加速测试失败: {str(e)}")
    
    # 3. 检测Intel硬件加速
    if 'intel' in gpu_info.lower() and 'qsv' in supported_hwaccels:
        logger.info("检测到Intel显卡，开始测试硬件加速")
        
        try:
            encoders_cmd = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                stderr=subprocess.PIPE, stdout=subprocess.PIPE, 
                encoding='utf-8', text=True, check=False
            )
            has_qsv = "h264_qsv" in encoders_cmd.stdout.lower()
            logger.debug(f"QSV编码器检测结果: {'可用' if has_qsv else '不可用'}")
            
            if has_qsv:
                # 测试QSV编码器
                logger.debug("测试QSV编码器")
                test_cmd = subprocess.run([
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=duration=0.1:size=640x480:rate=30",
                    "-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "23",
                    "-pix_fmt", "yuv420p", "-f", "null", "-"
                ], stderr=subprocess.PIPE, stdout=subprocess.PIPE, 
                   encoding='utf-8', text=True, check=False)
                
                if test_cmd.returncode == 0:
                    _FFMPEG_HW_ACCEL_INFO["available"] = True
                    _FFMPEG_HW_ACCEL_INFO["type"] = "qsv"
                    _FFMPEG_HW_ACCEL_INFO["encoder"] = "h264_qsv"
                    _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = []
                    _FFMPEG_HW_ACCEL_INFO["is_dedicated_gpu"] = not is_intel_integrated
                    _FFMPEG_HW_ACCEL_INFO["message"] = "Intel QSV编码器"
                    logger.info("✓ Intel QSV编码器测试成功")
                    return
                    
        except Exception as e:
            logger.debug(f"Intel硬件加速测试失败: {str(e)}")
    
    # 4. 如果没有硬件编码器，使用软件编码
    logger.info("未检测到可用的硬件编码器，使用软件编码")
    _FFMPEG_HW_ACCEL_INFO["available"] = False
    _FFMPEG_HW_ACCEL_INFO["type"] = "software"
    _FFMPEG_HW_ACCEL_INFO["encoder"] = "libx264"
    _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = []
    _FFMPEG_HW_ACCEL_INFO["is_dedicated_gpu"] = False
    _FFMPEG_HW_ACCEL_INFO["message"] = "使用软件编码"


def _detect_linux_acceleration(supported_hwaccels: str) -> None:
    """
    检测Linux系统的硬件加速

    Args:
        supported_hwaccels: FFmpeg支持的硬件加速器列表
    """
    global _FFMPEG_HW_ACCEL_INFO

    # 获取Linux显卡信息
    gpu_info = _get_linux_gpu_info()
    is_nvidia = 'nvidia' in gpu_info.lower()
    is_intel = 'intel' in gpu_info.lower()
    is_amd = 'amd' in gpu_info.lower() or 'radeon' in gpu_info.lower()

    # 检测NVIDIA CUDA支持
    if 'cuda' in supported_hwaccels and is_nvidia:
        try:
            test_cmd = subprocess.run(
                ["ffmpeg", "-hwaccel", "cuda", "-i", "/dev/null", "-f", "null", "-"],
                stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, check=False
            )
            if test_cmd.returncode == 0:
                _FFMPEG_HW_ACCEL_INFO["available"] = True
                _FFMPEG_HW_ACCEL_INFO["type"] = "cuda"
                _FFMPEG_HW_ACCEL_INFO["encoder"] = "h264_nvenc"
                _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = ["-hwaccel", "cuda"]
                _FFMPEG_HW_ACCEL_INFO["is_dedicated_gpu"] = True
                return
        except Exception as e:
            logger.debug(f"测试CUDA失败: {str(e)}")

    # 检测VAAPI支持
    if 'vaapi' in supported_hwaccels:
        # 检查是否存在渲染设备
        render_devices = ['/dev/dri/renderD128', '/dev/dri/renderD129']
        render_device = None
        for device in render_devices:
            if os.path.exists(device):
                render_device = device
                break

        if render_device:
            try:
                test_cmd = subprocess.run(
                    ["ffmpeg", "-hwaccel", "vaapi", "-vaapi_device", render_device,
                     "-i", "/dev/null", "-f", "null", "-"],
                    stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, check=False
                )
                if test_cmd.returncode == 0:
                    _FFMPEG_HW_ACCEL_INFO["available"] = True
                    _FFMPEG_HW_ACCEL_INFO["type"] = "vaapi"
                    _FFMPEG_HW_ACCEL_INFO["encoder"] = "h264_vaapi"
                    _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = ["-hwaccel", "vaapi", "-vaapi_device", render_device]
                    # 根据显卡类型判断是否为独立显卡
                    _FFMPEG_HW_ACCEL_INFO["is_dedicated_gpu"] = is_nvidia or (is_amd and not is_intel)
                    return
            except Exception as e:
                logger.debug(f"测试VAAPI失败: {str(e)}")

    # 检测Intel QSV支持
    if 'qsv' in supported_hwaccels and is_intel:
        try:
            test_cmd = subprocess.run(
                ["ffmpeg", "-hwaccel", "qsv", "-i", "/dev/null", "-f", "null", "-"],
                stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, check=False
            )
            if test_cmd.returncode == 0:
                _FFMPEG_HW_ACCEL_INFO["available"] = True
                _FFMPEG_HW_ACCEL_INFO["type"] = "qsv"
                _FFMPEG_HW_ACCEL_INFO["encoder"] = "h264_qsv"
                _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = ["-hwaccel", "qsv"]
                _FFMPEG_HW_ACCEL_INFO["is_dedicated_gpu"] = False  # Intel QSV通常是集成GPU
                return
        except Exception as e:
            logger.debug(f"测试QSV失败: {str(e)}")

    _FFMPEG_HW_ACCEL_INFO["message"] = f"Linux系统未检测到可用的硬件加速，显卡信息: {gpu_info}"


def _get_windows_gpu_info() -> str:
    """
    获取Windows系统的显卡信息

    Returns:
        str: 显卡信息字符串
    """
    try:
        # 使用PowerShell获取更可靠的显卡信息，并使用UTF-8编码
        gpu_info = subprocess.run(
            ['powershell', '-Command', "Get-WmiObject Win32_VideoController | Select-Object Name | Format-List"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', text=True, check=False
        )

        # 如果PowerShell失败，尝试使用wmic
        if not gpu_info.stdout.strip():
            gpu_info = subprocess.run(
                ['wmic', 'path', 'win32_VideoController', 'get', 'name'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', text=True, check=False
            )

        # 记录详细的显卡信息以便调试
        logger.debug(f"Windows显卡信息: {gpu_info.stdout}")
        return gpu_info.stdout
    except Exception as e:
        logger.warning(f"获取Windows显卡信息失败: {str(e)}")
        return "Unknown GPU"


def _get_linux_gpu_info() -> str:
    """
    获取Linux系统的显卡信息

    Returns:
        str: 显卡信息字符串
    """
    try:
        # 尝试使用lspci命令（shell=True 时用字符串形式，使管道符生效）
        gpu_info = subprocess.run(
            "lspci -v -nn | grep -i 'vga\\|display'",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True, check=False
        )
        if gpu_info.stdout:
            return gpu_info.stdout

        # 如果lspci命令失败，尝试使用glxinfo
        gpu_info = subprocess.run(
            "glxinfo | grep -i 'vendor\\|renderer'",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True, check=False
        )
        if gpu_info.stdout:
            return gpu_info.stdout

        return "Unknown GPU"
    except Exception as e:
        logger.warning(f"获取Linux显卡信息失败: {str(e)}")
        return "Unknown GPU"


def get_ffmpeg_hwaccel_args() -> List[str]:
    """
    获取FFmpeg硬件加速参数

    Returns:
        List[str]: FFmpeg硬件加速参数列表
    """
    # 如果还没有检测过，先进行检测
    if _FFMPEG_HW_ACCEL_INFO["type"] is None:
        detect_hardware_acceleration()

    return _FFMPEG_HW_ACCEL_INFO["hwaccel_args"]


def get_ffmpeg_hwaccel_type() -> Optional[str]:
    """
    获取FFmpeg硬件加速类型

    Returns:
        Optional[str]: 硬件加速类型，如果不支持则返回None
    """
    # 如果还没有检测过，先进行检测
    if _FFMPEG_HW_ACCEL_INFO["type"] is None:
        detect_hardware_acceleration()

    return _FFMPEG_HW_ACCEL_INFO["type"] if _FFMPEG_HW_ACCEL_INFO["available"] else None


def get_ffmpeg_hwaccel_encoder() -> Optional[str]:
    """
    获取FFmpeg硬件加速编码器

    Returns:
        Optional[str]: 硬件加速编码器，如果不支持则返回None
    """
    # 如果还没有检测过，先进行检测
    if _FFMPEG_HW_ACCEL_INFO["type"] is None:
        detect_hardware_acceleration()

    return _FFMPEG_HW_ACCEL_INFO["encoder"] if _FFMPEG_HW_ACCEL_INFO["available"] else None


def get_ffmpeg_hwaccel_info() -> Dict[str, Union[bool, str, List[str], None]]:
    """
    获取FFmpeg硬件加速信息

    Returns:
        Dict: 包含硬件加速信息的字典
    """
    # 如果还没有检测过，先进行检测
    if _FFMPEG_HW_ACCEL_INFO["type"] is None:
        detect_hardware_acceleration()

    return _FFMPEG_HW_ACCEL_INFO


def is_ffmpeg_hwaccel_available() -> bool:
    """
    检查是否有可用的FFmpeg硬件加速

    Returns:
        bool: 如果有可用的硬件加速则返回True，否则返回False
    """
    # 如果还没有检测过，先进行检测
    if _FFMPEG_HW_ACCEL_INFO["type"] is None:
        detect_hardware_acceleration()

    return _FFMPEG_HW_ACCEL_INFO["available"]


def is_dedicated_gpu() -> bool:
    """
    检查是否使用独立显卡进行硬件加速

    Returns:
        bool: 如果使用独立显卡则返回True，否则返回False
    """
    # 如果还没有检测过，先进行检测
    if _FFMPEG_HW_ACCEL_INFO["type"] is None:
        detect_hardware_acceleration()

    return _FFMPEG_HW_ACCEL_INFO["is_dedicated_gpu"]


def get_optimal_ffmpeg_encoder() -> str:
    """
    获取最优的FFmpeg编码器

    Returns:
        str: 编码器名称
    """
    # 如果还没有检测过，先进行检测
    if _FFMPEG_HW_ACCEL_INFO["type"] is None:
        detect_hardware_acceleration()

    if _FFMPEG_HW_ACCEL_INFO["available"]:
        return _FFMPEG_HW_ACCEL_INFO["encoder"]
    elif _FFMPEG_HW_ACCEL_INFO["fallback_available"]:
        return _FFMPEG_HW_ACCEL_INFO["fallback_encoder"]
    else:
        return "libx264"  # 默认软件编码器


def get_ffmpeg_command_with_hwaccel(input_path: str, output_path: str, **kwargs) -> List[str]:
    """
    生成带有硬件加速的FFmpeg命令

    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径
        **kwargs: 其他FFmpeg参数

    Returns:
        List[str]: FFmpeg命令列表
    """
    # 如果还没有检测过，先进行检测
    if _FFMPEG_HW_ACCEL_INFO["type"] is None:
        detect_hardware_acceleration()

    cmd = ["ffmpeg", "-y"]

    # 添加硬件加速参数
    if _FFMPEG_HW_ACCEL_INFO["available"]:
        cmd.extend(_FFMPEG_HW_ACCEL_INFO["hwaccel_args"])

    # 添加输入文件
    cmd.extend(["-i", input_path])

    # 添加编码器
    encoder = get_optimal_ffmpeg_encoder()
    cmd.extend(["-c:v", encoder])

    # 添加其他参数
    for key, value in kwargs.items():
        if key.startswith("_"):  # 跳过内部参数
            continue
        if isinstance(value, list):
            cmd.extend(value)
        else:
            cmd.extend([f"-{key}", str(value)])

    # 添加输出文件
    cmd.append(output_path)

    return cmd


def test_ffmpeg_compatibility() -> Dict[str, Any]:
    """
    测试FFmpeg兼容性并返回详细报告

    Returns:
        Dict: 兼容性测试报告
    """
    report = {
        "ffmpeg_installed": False,
        "platform": platform.system().lower(),
        "gpu_vendor": "unknown",
        "hardware_acceleration": {
            "available": False,
            "type": None,
            "encoder": None,
            "tested_methods": []
        },
        "software_fallback": {
            "available": False,
            "encoder": "libx264"
        },
        "recommendations": []
    }

    # 检查FFmpeg安装
    report["ffmpeg_installed"] = check_ffmpeg_installation()
    if not report["ffmpeg_installed"]:
        report["recommendations"].append("请安装FFmpeg并确保其在系统PATH中")
        return report

    # 检测硬件加速
    hwaccel_info = detect_hardware_acceleration()
    report["gpu_vendor"] = hwaccel_info.get("gpu_vendor", "unknown")
    report["hardware_acceleration"]["available"] = hwaccel_info.get("available", False)
    report["hardware_acceleration"]["type"] = hwaccel_info.get("type")
    report["hardware_acceleration"]["encoder"] = hwaccel_info.get("encoder")
    report["hardware_acceleration"]["tested_methods"] = hwaccel_info.get("tested_methods", [])

    # 检查软件备用方案
    report["software_fallback"]["available"] = hwaccel_info.get("fallback_available", True)
    report["software_fallback"]["encoder"] = hwaccel_info.get("fallback_encoder", "libx264")

    # 生成建议
    if not report["hardware_acceleration"]["available"]:
        if report["gpu_vendor"] == "nvidia":
            report["recommendations"].append("建议安装NVIDIA驱动和CUDA工具包以启用硬件加速")
        elif report["gpu_vendor"] == "amd":
            report["recommendations"].append("AMD显卡硬件加速支持有限，建议使用软件编码")
        elif report["gpu_vendor"] == "intel":
            report["recommendations"].append("建议更新Intel显卡驱动以启用QSV硬件加速")
        else:
            report["recommendations"].append("未检测到支持的GPU，将使用软件编码")

    return report


def force_software_encoding() -> None:
    """
    强制使用软件编码，禁用硬件加速
    """
    global _FFMPEG_HW_ACCEL_INFO

    _FFMPEG_HW_ACCEL_INFO.update({
        "available": False,
        "type": "software",
        "encoder": "libx264",
        "hwaccel_args": [],
        "message": "强制使用软件编码",
        "is_dedicated_gpu": False,
        "fallback_available": True,
        "fallback_encoder": "libx264"
    })

    logger.info("已强制切换到软件编码模式")


def reset_hwaccel_detection() -> None:
    """
    Reset hardware acceleration detection cache, force re-detection.

    Useful after driver update, system config change, or re-testing.
    """
    global _FFMPEG_HW_ACCEL_INFO

    with _FFMPEG_LOCK:
        logger.info("Resetting hardware acceleration detection cache...")
        _FFMPEG_HW_ACCEL_INFO = {
            "available": False,
            "type": None,
            "encoder": None,
            "hwaccel_args": [],
            "message": "",
            "is_dedicated_gpu": False,
            "fallback_available": False,
            "fallback_encoder": None,
            "platform": None,
            "gpu_vendor": None,
            "tested_methods": []
        }


def test_nvenc_directly() -> bool:
    """
    直接测试NVENC编码器是否可用（无硬件解码）
    
    Returns:
        bool: NVENC是否可用
    """
    try:
        logger.info("🧪 直接测试NVENC编码器...")
        
        # 测试纯NVENC编码器
        test_cmd = subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=640x480:rate=30",
            "-c:v", "h264_nvenc", "-preset", "fast", "-profile:v", "main",
            "-pix_fmt", "yuv420p", "-t", "1", "-f", "null", "-"
        ], stderr=subprocess.PIPE, stdout=subprocess.PIPE, 
           encoding='utf-8', text=True, check=False)
        
        if test_cmd.returncode == 0:
            logger.info("✅ NVENC编码器测试成功！")
            return True
        else:
            logger.warning(f"❌ NVENC编码器测试失败: {test_cmd.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"NVENC测试异常: {str(e)}")
        return False


def force_use_nvenc_pure() -> None:
    """
    强制使用纯NVENC编码器模式
    
    当自动检测失败但你确定NVENC可用时使用
    """
    global _FFMPEG_HW_ACCEL_INFO
    
    logger.info("🎯 强制启用纯NVENC编码器模式...")
    
    # 先测试NVENC是否真的可用
    if test_nvenc_directly():
        _FFMPEG_HW_ACCEL_INFO["available"] = True
        _FFMPEG_HW_ACCEL_INFO["type"] = "nvenc_pure"
        _FFMPEG_HW_ACCEL_INFO["encoder"] = "h264_nvenc"
        _FFMPEG_HW_ACCEL_INFO["hwaccel_args"] = []
        _FFMPEG_HW_ACCEL_INFO["is_dedicated_gpu"] = True
        _FFMPEG_HW_ACCEL_INFO["message"] = "强制启用纯NVENC编码器"
        logger.info("✅ 已强制启用纯NVENC编码器模式")
    else:
        logger.error("❌ NVENC编码器不可用，无法强制启用")


def get_hwaccel_status() -> Dict[str, any]:
    """
    获取当前硬件加速状态的详细信息
    
    Returns:
        Dict: 硬件加速状态信息
    """
    hwaccel_info = get_ffmpeg_hwaccel_info()
    
    status = {
        "available": hwaccel_info.get("available", False),
        "type": hwaccel_info.get("type", "software"),
        "encoder": hwaccel_info.get("encoder", "libx264"),
        "message": hwaccel_info.get("message", ""),
        "is_dedicated_gpu": hwaccel_info.get("is_dedicated_gpu", False),
        "platform": platform.system(),
        "gpu_vendor": detect_gpu_vendor(),
        "ffmpeg_available": check_ffmpeg_installation()
    }
    
    return status


# 自动重置检测（在模块导入时执行）
def _auto_reset_on_import():
    """模块导入时自动重置硬件加速检测"""
    try:
        # 只在平台真正改变时才重置，而不是初始化时
        current_platform = platform.system()
        cached_platform = _FFMPEG_HW_ACCEL_INFO.get("platform")

        # 只有当已经有缓存的平台信息，且平台改变了，才需要重置
        if cached_platform is not None and cached_platform != current_platform:
            reset_hwaccel_detection()
    except Exception as e:
        logger.debug(f"自动重置检测失败: {str(e)}")

# Execute auto reset
_auto_reset_on_import()


# ============================================================
# Video processing utilities for DirectCut pipeline
# ============================================================

def extract_audio(video_path: str, output_path: str,
                  start_time: float = None, duration: float = None) -> bool:
    """Extract audio track from video file to WAV.

    Args:
        video_path: Source video file path
        output_path: Output audio file path (recommended .wav)
        start_time: Start time in seconds, None for beginning
        duration: Duration in seconds, None for end

    Returns:
        bool: True on success
    """
    cmd = ["ffmpeg", "-y", "-hide_banner"]
    if start_time is not None:
        cmd += ["-ss", str(start_time)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", output_path]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
        if result.returncode != 0:
            logger.error(f"extract_audio failed: {result.stderr[:200]}")
            return False
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except subprocess.TimeoutExpired:
        logger.error("extract_audio timed out")
        return False
    except Exception as e:
        logger.error(f"extract_audio error: {e}")
        return False


def clip_video(video_path: str, output_path: str,
               start_time: float = None, duration: float = None) -> bool:
    """Clip a video segment using stream copy (no re-encoding).

    Args:
        video_path: Source video path
        output_path: Output video path
        start_time: Start time in seconds
        duration: Clip duration in seconds

    Returns:
        bool: True on success
    """
    cmd = ["ffmpeg", "-y", "-hide_banner"]
    if start_time is not None:
        cmd += ["-ss", str(start_time)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-i", video_path, "-c", "copy", "-avoid_negative_ts", "make_zero", output_path]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
        if result.returncode != 0:
            logger.error(f"clip_video failed: {result.stderr[:200]}")
            return False
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except subprocess.TimeoutExpired:
        logger.error("clip_video timed out")
        return False
    except Exception as e:
        logger.error(f"clip_video error: {e}")
        return False


def crop_to_portrait_face_centered(input_path: str, output_path: str,
                                   target_width: int = 1080, target_height: int = 1920,
                                   _retry_count: int = 0) -> bool:
    """Face-centered portrait cropping.

    Detects face position with OpenCV, then crops to portrait (9:16) centered on face.
    Falls back to centered crop if no face detected.

    Args:
        input_path: Input video path
        output_path: Output video path
        target_width: Target width (default 1080)
        target_height: Target height (default 1920, i.e. 9:16)
        _retry_count: Internal retry counter (do not pass from outside)

    Returns:
        bool: True on success
    """
    MAX_RETRY = 2
    if _retry_count > MAX_RETRY:
        logger.warning(f"crop_to_portrait_face_centered: max retry ({MAX_RETRY}) reached, using fallback")
        return crop_to_portrait_centered(input_path, output_path, target_width, target_height)

    # Step 1: Detect face position using OpenCV, also get video dimensions
    try:
        import cv2
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            logger.error("Cannot open video for face detection")
            return crop_to_portrait_centered(input_path, output_path, target_width, target_height)

        # Get video dimensions first
        vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Sample a few frames to find a face
        face_cx = None
        sample_positions = [total_frames // 4, total_frames // 2, total_frames * 3 // 4]

        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if face_cascade.empty():
            cap.release()
            logger.warning("Face cascade classifier not loaded, fallback to center crop")
            return crop_to_portrait_centered(input_path, output_path, target_width, target_height)

        for pos in sample_positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ret, frame = cap.read()
            if not ret:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
            if len(faces) > 0:
                # Pick largest face
                largest = max(faces, key=lambda f: f[2] * f[3])
                face_cx = largest[0] + largest[2] // 2
                break

        cap.release()

        if face_cx is None:
            logger.info("No face detected, fallback to center crop")
            return crop_to_portrait_centered(input_path, output_path, target_width, target_height)

        # Step 2: Calculate crop area using already-obtained dimensions
        scale = min(target_width / vw, target_height / vh)
        crop_w = int(target_width / scale)
        crop_h = int(target_height / scale)

        # Clamp to video dimensions
        crop_w = min(crop_w, vw)
        crop_h = min(crop_h, vh)

        # Center crop area on face, clamp to video bounds
        crop_x = max(0, min(face_cx - crop_w // 2, vw - crop_w))
        crop_y = max(0, (vh - crop_h) // 2)

    except ImportError:
        logger.warning("OpenCV not available, fallback to center crop")
        return crop_to_portrait_centered(input_path, output_path, target_width, target_height)
    except Exception as e:
        logger.error(f"Face detection failed: {e}, fallback to center crop")
        return crop_to_portrait_centered(input_path, output_path, target_width, target_height)

    # Step 3: FFmpeg crop + scale
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-i", input_path,
        "-vf", f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={target_width}:{target_height}",
        "-c:v", get_optimal_ffmpeg_encoder(),
        "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
        if result.returncode != 0:
            logger.error(f"crop face-centered failed: {result.stderr[:300]}")
            return crop_to_portrait_face_centered(input_path, output_path, target_width, target_height, _retry_count + 1)
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except subprocess.TimeoutExpired:
        logger.error("crop face-centered timed out")
        return False
    except Exception as e:
        logger.error(f"crop face-centered error: {e}")
        return False


def crop_to_portrait_centered(input_path: str, output_path: str,
                              width: int = 1080, height: int = 1920) -> bool:
    """Simple centered portrait crop (no face detection).

    Args:
        input_path: Input video path
        output_path: Output video path
        width: Target width
        height: Target height

    Returns:
        bool: True on success
    """
    try:
        import cv2
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            logger.error(f"Cannot open video: {input_path}")
            return False
        vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
    except ImportError:
        logger.error("OpenCV not available for crop")
        return False
    except Exception as e:
        logger.error(f"Cannot read video dimensions: {e}")
        return False

    # Calculate crop area (centered)
    scale = min(width / vw, height / vh)
    crop_w = min(int(width / scale), vw)
    crop_h = min(int(height / scale), vh)
    crop_x = max(0, (vw - crop_w) // 2)
    crop_y = max(0, (vh - crop_h) // 2)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-i", input_path,
        "-vf", f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={width}:{height}",
        "-c:v", get_optimal_ffmpeg_encoder(),
        "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
        if result.returncode != 0:
            logger.error(f"crop centered failed: {result.stderr[:300]}")
            return False
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except subprocess.TimeoutExpired:
        logger.error("crop centered timed out")
        return False
    except Exception as e:
        logger.error(f"crop centered error: {e}")
        return False


def concat_videos(concat_list_path: str, output_path: str,
                   stream_copy: bool = True) -> bool:
    """Concatenate multiple video files using FFmpeg concat demuxer.

    Args:
        concat_list_path: Path to concat list file (format: "file '/path.mp4'" per line)
        output_path: Output video path
        stream_copy: If True, use stream copy (fast, no re-encode). If False, re-encode.

    Returns:
        bool: True on success
    """
    # Validate input
    if not os.path.isfile(concat_list_path):
        logger.error(f"concat list not found: {concat_list_path}")
        return False
    
    # Check for empty concat list
    try:
        with open(concat_list_path, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            if not first_line:
                logger.error(f"concat list is empty: {concat_list_path}")
                return False
    except Exception as e:
        logger.error(f"cannot read concat list: {e}")
        return False

    if stream_copy:
        cmd = [
            "ffmpeg", "-y", "-hide_banner",
            "-f", "concat", "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-hide_banner",
            "-f", "concat", "-safe", "0",
            "-i", concat_list_path,
            "-c:v", get_optimal_ffmpeg_encoder(),
            "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            output_path
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=600)
        if result.returncode != 0:
            logger.error(f"concat_videos failed: {result.stderr[:300]}")
            return False
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except subprocess.TimeoutExpired:
        logger.error("concat_videos timed out")
        return False
    except Exception as e:
        logger.error(f"concat_videos error: {e}")
        return False


def mix_audio_video(video_path: str, audio_path: str, output_path: str,
                    original_audio_volume: float = 0.15) -> bool:
    """Mix video with audio overlay (reduce original audio + add new audio track).

    Fallback for AI narration mode when merge_materials is unavailable.

    Args:
        video_path: Input video path
        audio_path: Audio to overlay
        output_path: Output video path
        original_audio_volume: Original volume ratio (0.0-1.0), default 0.15

    Returns:
        bool: True on success
    """
    cmd = [
        "ffmpeg", "-y", "-hide_banner",
        "-i", video_path,
        "-i", audio_path,
        "-filter_complex",
        f"[0:a]volume={original_audio_volume}[bg];[1:a][bg]amix=inputs=2:duration=first[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
        if result.returncode != 0:
            logger.error(f"mix_audio_video failed: {result.stderr[:300]}")
            return False
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except subprocess.TimeoutExpired:
        logger.error("mix_audio_video timed out")
        return False
    except Exception as e:
        logger.error(f"mix_audio_video error: {e}")
        return False
