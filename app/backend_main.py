"""
Backend 入口点
通过 PyInstaller 打包为 backend.exe
"""

import sys
import os
from pathlib import Path
from loguru import logger

# 添加项目根目录到 Python 路径（app/ 的父目录）
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def setup_logging():
    """配置日志"""
    # 开发模式输出到 stderr，生产模式输出到文件
    log_dir = Path.home() / ".dramaclip" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_dir / "backend.log",
        rotation="10 MB",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}"
    )

    # 开发模式也输出到 stderr
    if not getattr(sys, 'frozen', False):
        logger.add(
            sys.stderr,
            level="DEBUG",
            format="{time:HH:mm:ss} | {level} | {message}"
        )


def setup_resources():
    """配置资源路径"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包模式
        # sys._MEIPASS 指向临时解压目录
        base_dir = Path(sys._MEIPASS)
        # 可执行文件所在目录（安装目录/backend/）
        exe_dir = Path(sys.executable).parent
    else:
        base_dir = project_root
        exe_dir = project_root

    # FFmpeg 路径查找（按优先级）
    ffmpeg_candidates = [
        exe_dir / "resources",           # 安装目录/backend/resources/
        base_dir / "resources",          # PyInstaller 临时目录/resources/
        exe_dir.parent / "resources",    # 安装目录/resources/
    ]
    
    for ffmpeg_dir in ffmpeg_candidates:
        if ffmpeg_dir.exists():
            os.environ["DRAMACLIP_FFMPEG_PATH"] = str(ffmpeg_dir)
            logger.info(f"FFmpeg path set to: {ffmpeg_dir}")
            break

    # 模型路径
    models_candidates = [
        exe_dir / "resources" / "models",
        base_dir / "resources" / "models",
        exe_dir.parent / "resources" / "models",
    ]
    
    for models_dir in models_candidates:
        if models_dir.exists():
            os.environ["DRAMACLIP_MODELS_PATH"] = str(models_dir)
            logger.info(f"Models path set to: {models_dir}")
            break

    return base_dir


def main():
    """主入口"""
    base_dir = setup_resources()
    setup_logging()

    logger.info("=" * 60)
    logger.info("DramaClip Backend starting...")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Working directory: {os.getcwd()}")
    logger.info(f"Base directory: {base_dir}")
    logger.info("=" * 60)

    try:
        from app.ipc.server import IpcServer
        from app.ipc.router import create_router

        # 创建路由
        router = create_router()
        logger.info(f"Registered methods: {router.list_methods()}")

        # 创建 IPC 服务器
        server = IpcServer(router)

        # 注册服务器引用到 handlers，用于发送进度通知
        from app.ipc import handlers as ipc_handlers
        ipc_handlers.set_server(server)

        # 发送就绪通知
        server.send_notification("ready", {
            "version": "1.0.0",
            "name": "DramaClip Backend",
            "timestamp": int(__import__("time").time() * 1000)
        })

        # 运行主循环
        logger.info("IPC Server listening on stdin...")
        server.run()

    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.exception(f"Backend fatal error: {e}")
        sys.exit(1)
    finally:
        logger.info("Backend stopped")


if __name__ == "__main__":
    main()
