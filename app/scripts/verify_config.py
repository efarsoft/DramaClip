#!/usr/bin/env python3
"""
配置系统验证脚本
验证所有服务模块是否正确使用UnifiedConfig
"""

import sys
import traceback
from pathlib import Path
from typing import Dict, List, Tuple

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from app.config.unified_config import config


def test_config_load() -> Tuple[bool, str]:
    """测试配置加载"""
    try:
        # 测试配置获取
        output_path = config.get_output_config()
        llm_config = config.get_llm_config()
        asr_config = config.get_asr_config()
        
        # 检查基本配置是否存在
        if not output_path:
            return False, "输出路径配置为空"
        if not llm_config:
            return False, "LLM配置为空"
        if not asr_config:
            return False, "ASR配置为空"
            
        return True, "配置加载成功"
    except Exception as e:
        return False, f"配置加载失败: {str(e)}"


def test_config_validation() -> Tuple[bool, str]:
    """测试配置验证"""
    try:
        is_valid = config.validate()
        errors = config.get_validation_errors()
        
        if not is_valid and errors:
            error_msg = "; ".join(errors[:3])  # 只显示前3个错误
            return False, f"配置验证失败: {error_msg}"
        
        return True, "配置验证通过"
    except Exception as e:
        return False, f"配置验证异常: {str(e)}"


def test_service_imports() -> List[Tuple[str, bool, str]]:
    """测试服务模块导入"""
    services_to_test = [
        "app.services.subtitle",
        "app.services.task",
        "app.services.state",
        "app.services.llm.openai_compatible_provider",
        "app.services.llm.config_validator",
        "app.services.multi_episode_processor",
        "app.services.clip.modular_direct_cut",
        "app.services.SDE.short_drama_explanation",
    ]
    
    results = []
    for service_name in services_to_test:
        try:
            __import__(service_name)
            results.append((service_name, True, "导入成功"))
        except Exception as e:
            results.append((service_name, False, f"导入失败: {str(e)}"))
    
    return results


def test_config_access() -> List[Tuple[str, bool, str]]:
    """测试配置访问方法"""
    tests = [
        ("get_llm_config", lambda: config.get_llm_config("openai_protocol")),
        ("get_output_config", lambda: config.get_output_config()),
        ("get_tts_config", lambda: config.get_tts_config()),
        ("get_asr_config", lambda: config.get_asr_config()),
        ("get_vision_config", lambda: config.get_vision_config()),
        ("get_text_config", lambda: config.get_text_config()),
        ("get_material_config", lambda: config.get_material_config()),
        ("get_api_key", lambda: config.get_api_key("vision")),
        ("get_material_directory", lambda: config.get_material_directory()),
        ("get_pexels_api_keys", lambda: config.get_pexels_api_keys()),
        ("get_pixabay_api_keys", lambda: config.get_pixabay_api_keys()),
        ("get_proxy_config", lambda: config.get_proxy_config()),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, True, f"返回: {type(result)}"))
        except Exception as e:
            results.append((test_name, False, f"访问失败: {str(e)}"))
    
    return results


def main():
    """主验证函数"""
    print("=" * 60)
    print("DramaClip 配置系统验证")
    print("=" * 60)
    
    # 1. 测试配置加载
    print("\n1. 测试配置加载...")
    load_ok, load_msg = test_config_load()
    print(f"   结果: {'✅ 通过' if load_ok else '❌ 失败'} - {load_msg}")
    
    # 2. 测试配置验证
    print("\n2. 测试配置验证...")
    valid_ok, valid_msg = test_config_validation()
    print(f"   结果: {'✅ 通过' if valid_ok else '❌ 失败'} - {valid_msg}")
    
    # 3. 测试服务导入
    print("\n3. 测试服务模块导入...")
    import_results = test_service_imports()
    import_success = 0
    failed_services = []
    for service_name, success, msg in import_results:
        status = "✅" if success else "❌"
        print(f"   {status} {service_name}: {msg}")
        if success:
            import_success += 1
        else:
            failed_services.append((service_name, msg))
    
    if failed_services:
        print(f"\n   失败的服务: {len(failed_services)}")
        for service_name, msg in failed_services:
            print(f"     - {service_name}: {msg}")
    
    # 4. 测试配置访问
    print("\n4. 测试配置访问方法...")
    access_results = test_config_access()
    access_success = 0
    for method_name, success, msg in access_results:
        status = "✅" if success else "❌"
        print(f"   {status} {method_name}: {msg}")
        if success:
            access_success += 1
    
    # 总结
    print("\n" + "=" * 60)
    print("验证总结:")
    print(f"  配置加载: {'✅ 通过' if load_ok else '❌ 失败'}")
    print(f"  配置验证: {'✅ 通过' if valid_ok else '❌ 失败'}")
    print(f"  服务导入: {import_success}/{len(import_results)} 通过")
    print(f"  配置访问: {access_success}/{len(access_results)} 通过")
    
    # 总体结果
    all_passed = (
        load_ok and 
        valid_ok and 
        import_success == len(import_results) and 
        access_success == len(access_results)
    )
    
    if all_passed:
        print("\n🎉 验证完成: 所有测试通过！配置系统正常工作。")
        return 0
    else:
        print("\n⚠️  验证完成: 部分测试失败，请检查配置。")
        return 1


if __name__ == "__main__":
    sys.exit(main())