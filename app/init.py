"""
应用启动初始化模块
P0 核心：确保配置系统、清理服务等在应用启动时被正确初始化

这个模块应该在 backend_main.py 的 main() 函数开头调用
"""

from typing import List, Tuple
from loguru import logger


def init_unified_config() -> Tuple[bool, List[str]]:
    """
    初始化统一配置系统

    这确保了：
    1. settings.json 被正确加载
    2. 配置系统就绪
    3. 后续服务可以使用统一的配置

    Returns:
        (是否有效, 错误/警告信息列表)
    """
    try:
        from app.config.unified_config import config, validate_config

        # 触发配置加载
        _ = config.get("openai_protocol.api_key")

        # 验证配置
        valid, messages = validate_config()

        if valid:
            if messages:
                logger.warning(f"[Init] 配置验证通过，但有警告: {messages}")
            else:
                logger.info("[Init] 统一配置系统已初始化并验证通过")
        else:
            logger.error(f"[Init] 配置验证失败: {messages}")

        return valid, messages

    except Exception as e:
        logger.error(f"[Init] 统一配置初始化失败: {e}")
        return False, [str(e)]


def init_cleanup_service():
    """
    初始化自动清理服务

    这确保了：
    1. 临时文件会被定期清理
    2. 磁盘空间不会被耗尽
    3. 应用长期运行的稳定性
    """
    try:
        from app.services.cleanup_service import start_cleanup_service
        start_cleanup_service(
            interval_seconds=300,  # 5分钟检查一次
            max_temp_age_hours=24,  # 临时文件最大保留24小时
            max_disk_usage_gb=10.0  # 最大使用10GB磁盘
        )
        logger.info("[Init] 自动清理服务已启动")
    except Exception as e:
        logger.error(f"[Init] 自动清理服务启动失败: {e}")


def init_job_store():
    """
    初始化任务持久化存储

    清扫上次运行遗留的孤儿任务（pending/running → failed），
    避免前端显示虚假的加载动画。
    """
    try:
        from app.services.state import state
        if hasattr(state, 'sweep_orphans'):
            n = state.sweep_orphans()
            if n > 0:
                logger.info(f"[Init] 已清扫 {n} 个孤儿任务")
        logger.info("[Init] 任务持久化存储已初始化")
    except Exception as e:
        logger.error(f"[Init] 任务持久化存储初始化失败: {e}")


def init_llm_providers():
    """
    初始化 LLM 提供商注册

    这确保了：
    1. LLM 提供商被正确注册
    2. 后续可以使用统一配置创建提供商实例
    """
    try:
        from app.services.llm.providers import register_all_providers
        register_all_providers()
        logger.info("[Init] LLM 提供商已注册")
    except Exception as e:
        logger.error(f"[Init] LLM 提供商注册失败: {e}")


def init_path_manager():
    """
    初始化路径管理器

    这确保了：
    1. 所有必要的目录被创建
    2. 路径管理器就绪
    """
    try:
        from app.utils.path_manager import init_path_manager, get_path_manager
        path_mgr = init_path_manager()
        # 触发目录创建
        _ = path_mgr.temp_root
        _ = path_mgr.output_root
        _ = path_mgr.cache_root
        logger.info("[Init] 路径管理器已初始化")
    except Exception as e:
        logger.error(f"[Init] 路径管理器初始化失败: {e}")


def init_database():
    """
    初始化数据库

    这确保了：
    1. 数据库连接就绪
    2. 表结构被正确创建
    """
    try:
        from app.services.project.manager_sqlite import get_manager
        manager = get_manager()
        logger.info("[Init] 数据库已初始化")
    except Exception as e:
        logger.error(f"[Init] 数据库初始化失败: {e}")


def init_all():
    """
    执行所有初始化步骤

    按依赖顺序初始化各个服务
    """
    import os
    from pathlib import Path
    
    # 设置国内 Hugging Face 镜像加速，解决模型下载卡死或超时问题
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    
    # 将所有本地 AI 模型缓存重定向至项目 resources 目录下的 models 文件夹（便于 Electron 打包分发与 Git 管理）
    models_dir = os.environ.get("DRAMACLIP_MODELS_PATH")
    if not models_dir:
        from app.utils.utils import root_dir
        models_dir = os.path.join(root_dir(), "resources", "models")
    workspace_models = Path(models_dir)
    os.environ["HF_HOME"] = str(workspace_models / ".cache" / "huggingface")
    os.environ["MODELSCOPE_CACHE"] = str(workspace_models / ".cache" / "modelscope")
    os.environ["XDG_CACHE_HOME"] = str(workspace_models / ".cache" / "styletts2")


    # 使用用户提供的令牌登录 ModelScope 平台 (异步执行，避免因网络响应慢或断网阻塞主线程 IPC 建立)
    def do_modelscope_login():
        try:
            from modelscope.hub.api import HubApi
            api = HubApi()
            api.login('ms-17a92991-9999-43fe-a68e-0dd996ca18dd')
            logger.info("[Init] 已成功使用提供令牌完成 ModelScope 平台身份验证")
        except Exception as ms_login_err:
            logger.warning(f"[Init] ModelScope 平台身份验证失败: {ms_login_err}")

    import threading
    login_thread = threading.Thread(target=do_modelscope_login, name="ModelScopeAuthThread", daemon=True)
    login_thread.start()
    logger.info("[Init] 后台 ModelScope 平台身份验证已启动")


    logger.info("=" * 60)
    logger.info("开始应用初始化...")
    logger.info("=" * 60)

    # 1. 首先初始化路径管理器（其他服务依赖它）
    init_path_manager()

    # 2. 初始化统一配置系统（后续服务依赖配置）
    config_valid, config_messages = init_unified_config()

    # 3. 初始化任务持久化存储（清扫孤儿任务）
    init_job_store()

    # 4. 初始化 LLM 提供商
    init_llm_providers()

    # 5. 初始化数据库
    init_database()

    # 6. 最后启动自动清理服务（依赖其他服务就绪）
    init_cleanup_service()

    logger.info("=" * 60)
    if config_valid:
        logger.info("应用初始化完成")
    else:
        logger.warning("应用初始化完成，但配置验证失败")
        logger.warning(f"配置问题: {config_messages}")
    logger.info("=" * 60)

    return config_valid, config_messages
