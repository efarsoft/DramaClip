import os
import time
from pathlib import Path
from loguru import logger

def main():
    target_dir = os.path.normpath("D:/DramaClip/resources/models/asr/iic/SenseVoiceSmall")
    logger.info(f"开始执行 SenseVoiceSmall 模型一键下载...")
    logger.info(f"目标物理存储路径: {target_dir}")
    
    # 确保父级目录存在
    Path(target_dir).mkdir(parents=True, exist_ok=True)
    
    start_time = time.time()
    try:
        from modelscope.hub.snapshot_download import snapshot_download
        
        logger.info("正在调起 ModelScope 纯净下载通道 (使用 local_dir 平铺)...")
        # snapshot_download 的 local_dir 参数会把该模型仓库中的所有文件直接平铺输出到指定目录下，没有冗余嵌套
        downloaded_path = snapshot_download(
            "iic/SenseVoiceSmall",
            local_dir=target_dir,
            cache_dir=None
        )
        
        elapsed = time.time() - start_time
        logger.success(f"模型下载并平铺完成！耗时: {elapsed:.2f} 秒")
        logger.info(f"下载文件绝对路径: {downloaded_path}")
        
        # 验证核心文件是否存在
        required_files = ["model.pt", "config.yaml", "tokens.json"]
        missing_files = []
        for file in required_files:
            file_path = os.path.join(target_dir, file)
            if os.path.exists(file_path):
                size_mb = os.path.getsize(file_path) / (1024 * 1024)
                logger.info(f" - [验证通过] {file} ({size_mb:.2f} MB)")
            else:
                missing_files.append(file)
                
        if missing_files:
            logger.error(f"警告: 缺少核心文件: {missing_files}")
        else:
            logger.success("所有核心模型文件完整，100% 物理绝对路径直读已就绪！")
            
    except Exception as e:
        logger.error(f"模型下载失败: {e}")
        raise

if __name__ == "__main__":
    main()
