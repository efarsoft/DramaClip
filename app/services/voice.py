"""向后兼容 - 已迁移到 app.services.tts.voice"""
from app.services.tts.voice import *  # noqa: F401,F403
from app.services.tts.voice import (  # noqa: F401 - explicit re-exports
    mktimestamp, new_sub_maker, add_subtitle_event,
    get_all_azure_voices, parse_voice_name, is_azure_v2_voice,
    should_use_azure_speech_services, tts, azure_tts_v1, azure_tts_v2,
    create_subtitle_from_multiple, get_edge_tts_proxy,
)
