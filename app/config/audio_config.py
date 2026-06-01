"""
音频配置

仅保留被活跃使用的 DUCKING_CONFIG（声音避让参数）。
原 AudioConfig 类及其辅助函数（get_optimized_volumes、apply_volume_profile 等）
均为死代码，已在架构清理中移除。
"""

# 声音避让 (Audio Ducking) 配置
# 已大幅软化（质量修复）：解决"音量忽大忽小、和原声打架"
DUCKING_CONFIG = {
    'enabled': True,
    'threshold': -24.0,           # 更温和触发（原 -30 太猛）
    'ratio': 4.2,                 # 大幅降低压缩比（原12，极易产生泵音）
    'attack': 0.04,               # 放慢响应，更自然
    'release': 0.72,              # 更长恢复，避免突然弹回
    'ducked_volume': 0.42,        # 避让时原声保留更多（原0.25太闷）
    'fade_duration': 0.28,
}
