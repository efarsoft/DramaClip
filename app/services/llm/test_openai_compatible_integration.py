"""
OpenAI 兼容接口集成测试脚本

用于快速检查统一 LLM Provider 是否注册成功。
"""

from loguru import logger

from app.services.llm.manager import LLMServiceManager
from app.services.llm.providers import register_all_providers


def test_provider_registration() -> bool:
    """检查 OpenAI 兼容 provider 是否注册成功。"""
    logger.info("测试：Provider 注册检查")
    register_all_providers()

    vision_providers = LLMServiceManager.list_vision_providers()
    text_providers = LLMServiceManager.list_text_providers()

    assert "openai" in vision_providers, "❌ OpenAI 兼容 Vision Provider 未注册"
    assert "openai" in text_providers, "❌ OpenAI 兼容 Text Provider 未注册"

    logger.success("✅ OpenAI 兼容 providers 已成功注册")
    return True


if __name__ == "__main__":
    try:
        ok = test_provider_registration()
        if ok:
            logger.success("\n🎉 集成检查通过")
    except Exception as exc:
        logger.error(f"\n❌ 集成检查失败: {exc}")
        raise
