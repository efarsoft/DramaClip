"""
Backend 入口点
通过 PyInstaller 打包为 backend.exe
"""

import sys
import os
import threading
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


def setup_exception_handler():
    """配置全局异常处理器"""
    
    def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
        """处理未捕获的异常"""
        if issubclass(exc_type, KeyboardInterrupt):
            # KeyboardInterrupt 交给系统处理
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        logger.critical(
            "未捕获的异常",
            exc_info=(exc_type, exc_value, exc_traceback)
        )
    
    def handle_thread_exception(args):
        """处理线程中的异常"""
        logger.error(
            f"线程异常: {args.threading_excepthook}",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
        )
    
    # 设置全局异常处理器
    sys.excepthook = handle_uncaught_exception
    
    # 设置线程异常处理器（Python 3.8+）
    if hasattr(threading, 'excepthook'):
        threading.excepthook = handle_thread_exception
    
    logger.info("全局异常处理器已配置")


def main():
    """主入口"""
    base_dir = setup_resources()
    setup_logging()
    setup_exception_handler()

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
    except (ImportError, ModuleNotFoundError) as e:
        # 模块导入错误通常是配置问题，不需要完整堆栈
        logger.error(f"Backend startup failed due to import error: {e}")
        sys.exit(1)
    except (OSError, PermissionError, FileNotFoundError) as e:
        # 文件或网络相关错误
        logger.error(f"Backend failed due to system error: {e}")
        sys.exit(1)
    except Exception as e:
        # 其他未预期的错误，记录完整堆栈
        logger.exception(f"Backend fatal error: {e}")
        sys.exit(1)
    finally:
        logger.info("Backend stopped")


if __name__ == "__main__":
    main()
