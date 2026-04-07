import streamlit as st
import os
from uuid import uuid4
from app.config import config
from app.services import voice
from app.models.schema import AudioVolumeDefaults
from app.utils import utils
from webui.utils.cache import get_songs_cache


def get_soulvoice_voices():
    """获取 SoulVoice 语音列表"""
    # 检查是否配置了 SoulVoice API key
    api_key = config.soulvoice.get("api_key", "")
    if not api_key:
        return []

    # 只返回一个 SoulVoice 选项，音色通过输入框自定义
    return ["soulvoice:custom"]


def get_tts_engine_options():
    """获取TTS引擎选项"""
    return {
        "edge_tts": "Edge TTS",
        "azure_speech": "Azure Speech Services",
        "tencent_tts": "腾讯云 TTS",
        "qwen3_tts": "通义千问 Qwen3 TTS",
        "cosyvoice": "CosyVoice 情感语音",
        "indextts2": "IndexTTS2 语音克隆"
    }


def get_tts_engine_descriptions():
    """获取TTS引擎详细描述"""
    return {
        "edge_tts": {
            "title": "Edge TTS",
            "features": "完全免费，但服务稳定性一般，不支持语音克隆功能",
            "use_case": "测试和轻量级使用",
            "registration": None
        },
        "azure_speech": {
            "title": "Azure Speech Services",
            "features": "提供一定免费额度，超出后按量付费，需要绑定海外信用卡",
            "use_case": "企业级应用，需要稳定服务",
            "registration": "https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/SpeechServices"
        },
        "tencent_tts": {
            "title": "腾讯云 TTS",
            "features": "提供免费额度，音质优秀，支持多种音色，国内访问速度快",
            "use_case": "个人和企业用户，需要稳定的中文语音合成",
            "registration": "https://console.cloud.tencent.com/tts"
        },
        "qwen3_tts": {
            "title": "通义千问 Qwen3 TTS",
            "features": "阿里云通义千问语音合成，音质优秀，支持情感指令控制（instruct模型）",
            "use_case": "需要高质量中文语音合成+情感控制的用户",
            "registration": "https://dashscope.aliyuncs.com/"
        },
        "cosyvoice": {
            "title": "CosyVoice 情感语音",
            "features": "阿里CosyVoice大模型，支持自然语言情感指令（如'用激动的语气'），V3音色100+种，短剧解说推荐",
            "use_case": "短剧解说、有声书、情感化配音",
            "registration": "https://dashscope.aliyuncs.com/"
        },
        "indextts2": {
            "title": "IndexTTS2 语音克隆",
            "features": "零样本语音克隆，上传参考音频即可合成相同音色的语音，需要本地或私有部署",
            "use_case": "下载地址：https://pan.quark.cn/s/0767c9bcefd5",
            "registration": None
        }
    }


def is_valid_azure_voice_name(voice_name: str) -> bool:
    """检查是否为有效的Azure音色名称格式"""
    if not voice_name or not isinstance(voice_name, str):
        return False

    voice_name = voice_name.strip()

    # Azure音色名称通常格式为: [语言]-[地区]-[名称]Neural
    # 例如: zh-CN-YunzeNeural, en-US-AvaMultilingualNeural
    import re
    pattern = r'^[a-z]{2}-[A-Z]{2}-\w+Neural$'
    return bool(re.match(pattern, voice_name))


def render_audio_panel(tr):
    """渲染音频设置面板"""
    with st.container(border=True):
        st.write(tr("Audio Settings"))

        # 渲染TTS设置
        render_tts_settings(tr)

        # 渲染背景音乐设置
        render_bgm_settings(tr)


def render_tts_settings(tr):
    """渲染TTS(文本转语音)设置"""

    # 1. TTS引擎选择器
    # st.subheader("🎤 TTS引擎选择")

    engine_options = get_tts_engine_options()
    engine_descriptions = get_tts_engine_descriptions()

    # 获取保存的TTS引擎设置
    saved_tts_engine = config.ui.get("tts_engine", "edge_tts")

    # 确保保存的引擎在可用选项中
    if saved_tts_engine not in engine_options:
        saved_tts_engine = "edge_tts"

    # TTS引擎选择下拉框
    selected_engine = st.selectbox(
        "选择TTS引擎",
        options=list(engine_options.keys()),
        format_func=lambda x: engine_options[x],
        index=list(engine_options.keys()).index(saved_tts_engine),
        help="选择您要使用的文本转语音引擎"
    )

    # 保存TTS引擎选择
    config.ui["tts_engine"] = selected_engine
    st.session_state['tts_engine'] = selected_engine

    # 2. 显示引擎详细说明
    if selected_engine in engine_descriptions:
        desc = engine_descriptions[selected_engine]

        with st.expander(f"📋 {desc['title']} 详细说明", expanded=True):
            st.markdown(f"**特点：** {desc['features']}")
            st.markdown(f"**适用场景：** {desc['use_case']}")

            if desc['registration']:
                st.markdown(f"**注册地址：** [{desc['registration']}]({desc['registration']})")

    # 3. 根据选择的引擎渲染对应的配置界面
    # st.subheader("⚙️ 引擎配置")

    if selected_engine == "edge_tts":
        render_edge_tts_settings(tr)
    elif selected_engine == "azure_speech":
        render_azure_speech_settings(tr)
    elif selected_engine == "soulvoice":
        render_soulvoice_engine_settings(tr)
    elif selected_engine == "tencent_tts":
        render_tencent_tts_settings(tr)
    elif selected_engine == "qwen3_tts":
        render_qwen3_tts_settings(tr)
    elif selected_engine == "cosyvoice":
        render_cosyvoice_tts_settings(tr)
    elif selected_engine == "indextts2":
        render_indextts2_tts_settings(tr)

    # 4. 试听功能
    render_voice_preview_new(tr, selected_engine)


def render_edge_tts_settings(tr):
    """渲染 Edge TTS 引擎设置"""
    # 获取支持的语音列表
    support_locales = ["zh-CN", "en-US"]
    all_voices = voice.get_all_azure_voices(filter_locals=support_locales)

    # 只保留标准版本的语音（Edge TTS专用，不包含V2）
    edge_voices = [v for v in all_voices if "-V2" not in v]

    # 创建友好的显示名称
    friendly_names = {}
    for v in edge_voices:
        friendly_names[v] = v.replace("Female", tr("Female")).replace("Male", tr("Male")).replace("Neural", "")

    # 获取保存的语音设置
    saved_voice_name = config.ui.get("edge_voice_name", "zh-CN-XiaoxiaoNeural-Female")

    # 确保保存的音色在可用列表中
    if saved_voice_name not in friendly_names:
        # 选择与UI语言匹配的第一个语音
        for v in edge_voices:
            if v.lower().startswith(st.session_state.get("ui_language", "zh-CN").lower()):
                saved_voice_name = v
                break
        else:
            # 如果没找到匹配的，使用第一个
            saved_voice_name = edge_voices[0] if edge_voices else ""

    # 音色选择下拉框（Edge TTS音色相对较少，保留下拉框）
    selected_friendly_name = st.selectbox(
        "音色选择",
        options=list(friendly_names.values()),
        index=list(friendly_names.keys()).index(saved_voice_name) if saved_voice_name in friendly_names else 0,
        help="选择Edge TTS音色"
    )

    # 获取实际的语音名称
    voice_name = list(friendly_names.keys())[
        list(friendly_names.values()).index(selected_friendly_name)
    ]

    # 显示音色信息
    with st.expander("💡 Edge TTS 音色说明", expanded=False):
        st.write("**中文音色：**")
        zh_voices = [v for v in edge_voices if v.startswith("zh-CN")]
        for v in zh_voices:
            gender = "女声" if "Female" in v else "男声"
            name = v.replace("-Female", "").replace("-Male", "").replace("zh-CN-", "").replace("Neural", "")
            st.write(f"• {name} ({gender})")

        st.write("")
        st.write("**英文音色：**")
        en_voices = [v for v in edge_voices if v.startswith("en-US")][:5]  # 只显示前5个
        for v in en_voices:
            gender = "女声" if "Female" in v else "男声"
            name = v.replace("-Female", "").replace("-Male", "").replace("en-US-", "").replace("Neural", "")
            st.write(f"• {name} ({gender})")

        if len([v for v in edge_voices if v.startswith("en-US")]) > 5:
            st.write("• ... 更多英文音色")

    config.ui["edge_voice_name"] = voice_name
    config.ui["voice_name"] = voice_name  # 兼容性

    # 音量调节
    voice_volume = st.slider(
        "音量调节",
        min_value=0,
        max_value=100,
        value=int(config.ui.get("edge_volume", 80)),
        step=1,
        help="调节语音音量 (0-100)"
    )
    config.ui["edge_volume"] = voice_volume
    st.session_state['voice_volume'] = voice_volume / 100.0

    # 语速调节
    voice_rate = st.slider(
        "语速调节",
        min_value=0.5,
        max_value=2.0,
        value=config.ui.get("edge_rate", 1.0),
        step=0.1,
        help="调节语音速度 (0.5-2.0倍速)"
    )
    config.ui["edge_rate"] = voice_rate
    st.session_state['voice_rate'] = voice_rate

    # 语调调节
    voice_pitch = st.slider(
        "语调调节",
        min_value=-50,
        max_value=50,
        value=int(config.ui.get("edge_pitch", 0)),
        step=5,
        help="调节语音音调 (-50%到+50%)"
    )
    config.ui["edge_pitch"] = voice_pitch
    # 转换为比例值
    st.session_state['voice_pitch'] = 1.0 + (voice_pitch / 100.0)


def render_azure_speech_settings(tr):
    """渲染 Azure Speech Services 引擎设置"""
    # 服务区域配置
    azure_speech_region = st.text_input(
        "服务区域",
        value=config.azure.get("speech_region", ""),
        placeholder="例如：eastus",
        help="Azure Speech Services 服务区域，如：eastus, westus2, eastasia 等"
    )

    # API Key配置
    azure_speech_key = st.text_input(
        "API Key",
        value=config.azure.get("speech_key", ""),
        type="password",
        help="Azure Speech Services API 密钥"
    )

    # 保存Azure配置
    config.azure["speech_region"] = azure_speech_region
    config.azure["speech_key"] = azure_speech_key

    # 音色名称输入框
    saved_voice_name = config.ui.get("azure_voice_name", "zh-CN-XiaoxiaoMultilingualNeural")

    # 音色名称输入
    voice_name = st.text_input(
        "音色名称",
        value=saved_voice_name,
        help="输入Azure Speech Services音色名称，直接使用官方音色名称即可。例如：zh-CN-YunzeNeural",
        placeholder="zh-CN-YunzeNeural"
    )

    # 显示常用音色示例
    with st.expander("💡 常用音色参考", expanded=False):
        st.write("**中文音色：**")
        st.write("• zh-CN-XiaoxiaoMultilingualNeural (女声，多语言)")
        st.write("• zh-CN-YunzeNeural (男声)")
        st.write("• zh-CN-YunxiNeural (男声)")
        st.write("• zh-CN-XiaochenNeural (女声)")
        st.write("")
        st.write("**英文音色：**")
        st.write("• en-US-AndrewMultilingualNeural (男声，多语言)")
        st.write("• en-US-AvaMultilingualNeural (女声，多语言)")
        st.write("• en-US-BrianMultilingualNeural (男声，多语言)")
        st.write("• en-US-EmmaMultilingualNeural (女声，多语言)")
        st.write("")
        st.info("💡 更多音色请参考 [Azure Speech Services 官方文档](https://docs.microsoft.com/en-us/azure/cognitive-services/speech-service/language-support)")

    # 快速选择按钮
    st.write("**快速选择：**")
    cols = st.columns(3)
    with cols[0]:
        if st.button("中文女声", help="zh-CN-XiaoxiaoMultilingualNeural"):
            voice_name = "zh-CN-XiaoxiaoMultilingualNeural"
            st.rerun()
    with cols[1]:
        if st.button("中文男声", help="zh-CN-YunzeNeural"):
            voice_name = "zh-CN-YunzeNeural"
            st.rerun()
    with cols[2]:
        if st.button("英文女声", help="en-US-AvaMultilingualNeural"):
            voice_name = "en-US-AvaMultilingualNeural"
            st.rerun()

    # 验证音色名称并显示状态
    if voice_name.strip():
        # 检查是否为有效的Azure音色格式
        if is_valid_azure_voice_name(voice_name):
            st.success(f"✅ 音色名称有效: {voice_name}")
        else:
            st.warning(f"⚠️ 音色名称格式可能不正确: {voice_name}")
            st.info("💡 Azure音色名称通常格式为: [语言]-[地区]-[名称]Neural")

    # 保存配置
    config.ui["azure_voice_name"] = voice_name
    config.ui["voice_name"] = voice_name  # 兼容性

    # 音量调节
    voice_volume = st.slider(
        "音量调节",
        min_value=0,
        max_value=100,
        value=int(config.ui.get("azure_volume", 80)),
        step=1,
        help="调节语音音量 (0-100)"
    )
    config.ui["azure_volume"] = voice_volume
    st.session_state['voice_volume'] = voice_volume / 100.0

    # 语速调节
    voice_rate = st.slider(
        "语速调节",
        min_value=0.5,
        max_value=2.0,
        value=config.ui.get("azure_rate", 1.0),
        step=0.1,
        help="调节语音速度 (0.5-2.0倍速)"
    )
    config.ui["azure_rate"] = voice_rate
    st.session_state['voice_rate'] = voice_rate

    # 语调调节
    voice_pitch = st.slider(
        "语调调节",
        min_value=-50,
        max_value=50,
        value=int(config.ui.get("azure_pitch", 0)),
        step=5,
        help="调节语音音调 (-50%到+50%)"
    )
    config.ui["azure_pitch"] = voice_pitch
    # 转换为比例值
    st.session_state['voice_pitch'] = 1.0 + (voice_pitch / 100.0)

    # 显示配置状态
    if azure_speech_region and azure_speech_key:
        st.success("✅ Azure Speech Services 配置已设置")
    elif not azure_speech_region:
        st.warning("⚠️ 请配置服务区域")
    elif not azure_speech_key:
        st.warning("⚠️ 请配置 API Key")


def render_tencent_tts_settings(tr):
    """渲染腾讯云 TTS 引擎设置"""
    # Secret ID 输入
    secret_id = st.text_input(
        "Secret ID",
        value=config.tencent.get("secret_id", ""),
        help="请输入您的腾讯云 Secret ID"
    )

    # Secret Key 输入
    secret_key = st.text_input(
        "Secret Key",
        value=config.tencent.get("secret_key", ""),
        type="password",
        help="请输入您的腾讯云 Secret Key"
    )

    # 地域选择
    region_options = [
        "ap-beijing",
        "ap-shanghai",
        "ap-guangzhou",
        "ap-chengdu",
        "ap-nanjing",
        "ap-singapore",
        "ap-hongkong"
    ]
    
    saved_region = config.tencent.get("region", "ap-beijing")
    if saved_region not in region_options:
        region_options.append(saved_region)
    
    region = st.selectbox(
        "服务地域",
        options=region_options,
        index=region_options.index(saved_region),
        help="选择腾讯云 TTS 服务地域"
    )

    # 音色选择
    voice_type_options = {
        "101001": "智瑜 - 女声（推荐）",
        "101002": "智聆 - 女声",
        "101003": "智美 - 女声",
        "101004": "智云 - 男声",
        "101005": "智莉 - 女声",
        "101006": "智言 - 男声",
        "101007": "智娜 - 女声",
        "101008": "智琪 - 女声",
        "101009": "智芸 - 女声",
        "101010": "智华 - 男声",
        "101011": "智燕 - 女声",
        "101012": "智丹 - 女声",
        "101013": "智辉 - 男声",
        "101014": "智宁 - 女声",
        "101015": "智萌 - 女声",
        "101016": "智甜 - 女声",
        "101017": "智蓉 - 女声",
        "101018": "智靖 - 男声"
    }
    
    saved_voice_type = config.ui.get("tencent_voice_type", "101001")
    if saved_voice_type not in voice_type_options:
        voice_type_options[saved_voice_type] = f"自定义音色 ({saved_voice_type})"
    
    selected_voice_display = st.selectbox(
        "音色选择",
        options=list(voice_type_options.values()),
        index=list(voice_type_options.keys()).index(saved_voice_type),
        help="选择腾讯云 TTS 音色"
    )
    
    # 获取实际的音色ID
    voice_type = list(voice_type_options.keys())[
        list(voice_type_options.values()).index(selected_voice_display)
    ]
    
    # 语速调节
    voice_rate = st.slider(
        "语速调节",
        min_value=0.5,
        max_value=2.0,
        value=config.ui.get("tencent_rate", 1.0),
        step=0.1,
        help="调节语音速度 (0.5-2.0)"
    )
    
    config.ui["voice_name"] = saved_voice_type  # 兼容性
    
    # 显示音色说明
    with st.expander("💡 腾讯云 TTS 音色说明", expanded=False):
        st.write("**女声音色：**")
        female_voices = [(k, v) for k, v in voice_type_options.items() if "女声" in v]
        for voice_id, voice_desc in female_voices[:6]:  # 显示前6个
            st.write(f"• {voice_desc} (ID: {voice_id})")
        
        st.write("")
        st.write("**男声音色：**")
        male_voices = [(k, v) for k, v in voice_type_options.items() if "男声" in v]
        for voice_id, voice_desc in male_voices:
            st.write(f"• {voice_desc} (ID: {voice_id})")
        
        st.write("")
        st.info("💡 更多音色请参考腾讯云官方文档")
    
    # 保存配置
    config.tencent["secret_id"] = secret_id
    config.tencent["secret_key"] = secret_key
    config.tencent["region"] = region
    config.ui["tencent_voice_type"] = voice_type
    config.ui["tencent_rate"] = voice_rate
    config.ui["voice_name"] = saved_voice_type #兼容性


def render_qwen3_tts_settings(tr):
    """渲染 Qwen3 TTS 设置（含情感控制）"""
    api_key = st.text_input(
        "API Key",
        value=config.tts_qwen.get("api_key", ""),
        type="password",
        help="通义千问 DashScope API Key"
    )

    # 情感控制开关
    enable_instruct = st.toggle(
        "启用情感控制",
        value=config.tts_qwen.get("enable_instruct", False),
        help="启用后将使用 qwen3-tts-instruct-flash 模型，支持自然语言情感指令"
    )

    model_name = st.text_input(
        "模型名称",
        value=config.tts_qwen.get("model_name", "qwen3-tts-instruct-flash" if enable_instruct else "qwen3-tts-flash"),
        help="启用情感时推荐 qwen3-tts-instruct-flash，否则用 qwen3-tts-flash"
    )

    # Qwen3 TTS 音色选项 - 中文名: 英文参数
    voice_options = {
        "芊悦": "Cherry",
        "晨煦": "Ethan",
        "不吃鱼": "Nofish",
        "詹妮弗": "Jennifer",
        "甜茶": "Ryan",
        "卡捷琳娜": "Katerina",
        "墨讲师": "Elias",
        "上海-阿珍": "Jada",
        "北京-晓东": "Dylan",
        "四川-晴儿": "Sunny",
        "南京-老李": "Li",
        "陕西-秦川": "Marcus",
        "闽南-阿杰": "Roy",
        "天津-李彼得": "Peter",
        "粤语-阿强": "Rocky",
        "粤语-阿清": "Kiki",
        "四川-程川": "Eric"
    }
    
    # 显示给用户的中文名称列表
    display_names = list(voice_options.keys())
    saved_voice_param = config.ui.get("qwen_voice_type", "Cherry")
    
    # 如果保存的英文参数不在选项中，查找对应的中文名称
    saved_display_name = "芊悦"  # 默认值
    for chinese_name, english_param in voice_options.items():
        if english_param == saved_voice_param:
            saved_display_name = chinese_name
            break
    
    # 如果保存的音色不在选项中，添加到自定义选项
    if saved_display_name not in display_names:
        display_names.append(saved_display_name)
        voice_options[saved_display_name] = saved_voice_param

    selected_display_name = st.selectbox(
        "音色选择",
        options=display_names,
        index=display_names.index(saved_display_name) if saved_display_name in display_names else 0,
        help="选择Qwen3 TTS音色"
    )
    
    # 获取对应的英文参数
    voice_type = voice_options.get(selected_display_name, "Cherry")

    voice_rate = st.slider(
        "语速调节",
        min_value=0.5,
        max_value=2.0,
        value=1.0,
        step=0.1,
        help="调节语音速度 (0.5-2.0)"
    )

    # 情感指令输入（仅启用情感控制时显示）
    if enable_instruct:
        st.divider()
        st.markdown("**🎭 情感控制**")

        # 预设情感模板
        emotion_presets = {
            "不设置": "",
            "激动兴奋": "语调欢快，充满热情和能量",
            "温柔亲切": "语速轻柔，声音温暖，带有亲切感",
            "紧张悬疑": "语速稍快，语气紧张，带有悬念感",
            "低沉悲伤": "语速缓慢，声音低沉，带有忧伤感",
            "严肃认真": "语速平稳，语气庄重严肃",
            "活泼可爱": "语调活泼跳跃，充满童趣",
        }

        preset_name = st.selectbox(
            "情感预设",
            options=list(emotion_presets.keys()),
            index=0,
            help="选择预设情感模板，或自定义输入"
        )

        instructions = st.text_area(
            "情感指令",
            value=emotion_presets.get(preset_name, config.tts_qwen.get("instructions", "")),
            height=60,
            placeholder="例如：语调欢快，充满热情和能量",
            help="自然语言描述你想要的语音风格（仅 instruct 模型支持）"
        )

        with st.expander("💡 情感指令示例", expanded=False):
            st.write("- **激动**: \"语调欢快，充满热情和能量\"")
            st.write("- **温柔**: \"语速轻柔，声音温暖，带有亲切感\"")
            st.write("- **悬疑**: \"语速稍快，语气紧张，带有悬念感\"")
            st.write("- **悲伤**: \"语速缓慢，声音低沉，带有忧伤感\"")
            st.write("- **解说**: \"语速适中，吐字清晰，像专业的影视解说\"")
    else:
        instructions = ""

    # 保存配置
    config.tts_qwen["api_key"] = api_key
    config.tts_qwen["model_name"] = model_name
    config.tts_qwen["enable_instruct"] = enable_instruct
    config.tts_qwen["instructions"] = instructions
    config.ui["qwen_voice_type"] = voice_type
    config.ui["qwen3_rate"] = voice_rate
    config.ui["voice_name"] = voice_type


def render_cosyvoice_tts_settings(tr):
    """渲染 CosyVoice TTS 设置（含情感指令控制）"""
    api_key = st.text_input(
        "API Key",
        value=config.cosyvoice.get("api_key", ""),
        type="password",
        help="DashScope API Key (与Qwen3 TTS可共用同一Key)"
    )

    # 模型选择
    model_options = {
        "CosyVoice V3 Flash (推荐)": "cosyvoice-v3-flash",
        "CosyVoice V3 Plus": "cosyvoice-v3-plus",
        "CosyVoice V2": "cosyvoice-v2",
        "CosyVoice V1": "cosyvoice-v1",
    }

    saved_model = config.cosyvoice.get("model", "cosyvoice-v3-flash")
    saved_model_display = "CosyVoice V3 Flash (推荐)"
    for display, value in model_options.items():
        if value == saved_model:
            saved_model_display = display
            break

    selected_model_display = st.selectbox(
        "模型选择",
        options=list(model_options.keys()),
        index=list(model_options.keys()).index(saved_model_display) if saved_model_display in model_options else 0,
        help="V3 系列支持情感 Instruct（需搭配支持 Instruct 的音色）"
    )
    selected_model = model_options[selected_model_display]

    # 音色选择 - 按场景分类
    # V3 系列音色（含情感支持标记）
    voice_categories = {
        "🎬 短视频配音": {
            "龙机器 (男)": ("longjiqi_v3", False),
            "龙猴哥 (男)": ("longhouge_v3", False),
            "龙黛玉 (女)": ("longdaiyu_v3", False),
        },
        "📖 有声书": {
            "龙妙 (女)": ("longmiao_v3", False),
            "龙三叔 (男)": ("longsanshu_v3", False),
            "龙婉君 (女)": ("longwanjun_v3", False),
        },
        "💬 社交陪伴": {
            "龙安洋 (男) ★情感": ("longanyang", True),
            "龙安欢 (女) ★情感": ("longanhuan", True),
            "龙寒 (男)": ("longhan_v3", False),
            "龙颜 (女)": ("longyan_v3", False),
        },
        "📞 客服": {
            "龙应询 (男)": ("longyingxun_v3", False),
            "龙应静 (女)": ("longyingjing_v3", False),
            "龙应聆 (女)": ("longyingling_v3", False),
        },
        "📻 新闻播报": {
            "龙书 (男)": ("longshu_v3", False),
            "龙硕 (男)": ("longshuo_v3", False),
        },
        "👶 童声": {
            "龙呼呼 ★情感": ("longhuhu_v3", True),
        },
    }

    # V2 音色补充
    voice_categories_v2 = {
        "🎬 短视频配音 (V2)": {
            "龙机心 (男)": ("longjixin", False),
            "龙高僧 (男)": ("longgaoseng", False),
        },
        "📖 有声书 (V2)": {
            "龙白芷 (女)": ("longbaizhi", False),
            "龙逸尘 (男)": ("longyichen", False),
        },
    }

    # 根据选择的模型决定音色范围
    use_v2_voices = "v2" in selected_model or "v1" in selected_model

    saved_voice = config.cosyvoice.get("voice", "longanyang")

    # 构建音色选项
    all_voice_options = {}
    for cat_name, voices in voice_categories.items():
        for disp_name, (voice_id, support_emotion) in voices.items():
            all_voice_options[f"{cat_name} > {disp_name}"] = voice_id

    if use_v2_voices:
        for cat_name, voices in voice_categories_v2.items():
            for disp_name, (voice_id, support_emotion) in voices.items():
                all_voice_options[f"{cat_name} > {disp_name}"] = voice_id

    display_voice_list = list(all_voice_options.keys())
    saved_voice_display = display_voice_list[0]
    for disp, vid in all_voice_options.items():
        if vid == saved_voice:
            saved_voice_display = disp
            break

    selected_voice_display = st.selectbox(
        "音色选择",
        options=display_voice_list,
        index=display_voice_list.index(saved_voice_display) if saved_voice_display in display_voice_list else 0,
        help="带 ★情感 标记的音色支持情感 Instruct（仅 V3 模型）"
    )
    selected_voice = all_voice_options.get(selected_voice_display, "longanyang")

    # 语速调节
    voice_rate = st.slider(
        "语速调节",
        min_value=0.5,
        max_value=2.0,
        value=1.0,
        step=0.1,
        help="调节语音速度 (0.5-2.0)"
    )

    # 情感指令（仅 V3 + 支持 Instruct 的音色）
    st.divider()
    st.markdown("**🎭 情感指令控制**")

    # 检查是否支持情感
    is_v3 = "v3" in selected_model
    support_instruct = is_v3 and any(
        vid == selected_voice and emo for _, voices in voice_categories.items()
        for _, (vid, emo) in voices.items()
    )

    if not is_v3:
        st.warning("⚠️ 当前选择的模型不支持情感控制，请切换到 V3 模型")
    elif not support_instruct:
        st.warning("⚠️ 当前选择的音色不支持情感 Instruct，请选择带 ★情感 标记的音色")

    emotion_presets_cosy = {
        "不设置": "",
        "激动兴奋": "用激动的语气说，充满热情和能量",
        "温柔亲切": "用温柔亲切的语气说，语速轻柔",
        "紧张悬疑": "用紧张的语气说，语速稍快，带有悬念感",
        "低沉悲伤": "用悲伤的语气说，语速缓慢，声音低沉",
        "严肃解说": "用专业的语气解说，吐字清晰，语速适中",
        "活泼可爱": "用活泼可爱的语气说，语调跳跃",
        "愤怒暴躁": "用愤怒的语气说，声音洪亮，语速急促",
    }

    preset_name = st.selectbox(
        "情感预设",
        options=list(emotion_presets_cosy.keys()),
        index=0,
        help="选择预设情感模板，或自定义输入",
        disabled=not (is_v3 and support_instruct)
    )

    instruction = st.text_area(
        "情感指令",
        value=emotion_presets_cosy.get(preset_name, config.cosyvoice.get("instruction", "")),
        height=60,
        placeholder="例如：用激动的语气说，充满热情和能量",
        help="自然语言描述你想要的情感和语调（CosyVoice V3 Instruct）",
        disabled=not (is_v3 and support_instruct)
    )

    with st.expander("💡 CosyVoice 使用说明", expanded=False):
        st.markdown("""
        **情感控制说明：**
        - 仅 **V3 模型** + **带 ★情感 标记的音色** 支持情感 Instruct
        - 情感指令支持自然语言描述，如"用激动的语气说"
        - 音色选择建议：短剧解说推荐「龙机器」或「龙黛玉」

        **模型对比：**
        | 模型 | 情感支持 | 音色数 | 速度 |
        |------|---------|--------|------|
        | V3 Flash | ★ | 60+ | 快 |
        | V3 Plus | ★ | 2 | 中 |
        | V2 | ✗ | 100+ | 中 |
        """)

    # 保存配置
    config.cosyvoice["api_key"] = api_key
    config.cosyvoice["model"] = selected_model
    config.cosyvoice["voice"] = selected_voice
    config.cosyvoice["instruction"] = instruction if (is_v3 and support_instruct) else ""
    config.ui["cosyvoice_rate"] = voice_rate
    config.ui["voice_name"] = f"cosyvoice:{selected_voice}"


def render_indextts2_tts_settings(tr):
    """渲染 IndexTTS2 TTS 设置"""
    import os
    
    # API 地址配置
    api_url = st.text_input(
        "API 地址",
        value=config.indextts2.get("api_url", "http://127.0.0.1:8081/tts"),
        help="IndexTTS2 API 服务地址"
    )
    
    # 参考音频文件路径
    reference_audio = st.text_input(
        "参考音频路径",
        value=config.indextts2.get("reference_audio", ""),
        help="用于语音克隆的参考音频文件路径（WAV 格式，建议 3-10 秒）"
    )
    
    # 文件上传功能
    uploaded_file = st.file_uploader(
        "或上传参考音频文件",
        type=["wav", "mp3"],
        help="上传一段清晰的音频用于语音克隆"
    )
    
    if uploaded_file is not None:
        # 保存上传的文件
        import tempfile
        temp_dir = tempfile.gettempdir()
        audio_path = os.path.join(temp_dir, f"indextts2_ref_{uploaded_file.name}")
        with open(audio_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        reference_audio = audio_path
        st.success(f"✅ 音频已上传: {audio_path}")
    
    # 推理模式
    infer_mode = st.selectbox(
        "推理模式",
        options=["普通推理", "快速推理"],
        index=0 if config.indextts2.get("infer_mode", "普通推理") == "普通推理" else 1,
        help="普通推理质量更高但速度较慢，快速推理速度更快但质量略低"
    )
    
    # 高级参数折叠面板
    with st.expander("🔧 高级参数", expanded=False):
        col1, col2 = st.columns(2)
        
        with col1:
            temperature = st.slider(
                "采样温度 (Temperature)",
                min_value=0.1,
                max_value=2.0,
                value=float(config.indextts2.get("temperature", 1.0)),
                step=0.1,
                help="控制随机性，值越高输出越随机，值越低越确定"
            )
            
            top_p = st.slider(
                "Top P",
                min_value=0.0,
                max_value=1.0,
                value=float(config.indextts2.get("top_p", 0.8)),
                step=0.05,
                help="nucleus 采样的概率阈值，值越小结果越确定"
            )
            
            top_k = st.slider(
                "Top K",
                min_value=0,
                max_value=100,
                value=int(config.indextts2.get("top_k", 30)),
                step=5,
                help="top-k 采样的 k 值，0 表示不使用 top-k"
            )
        
        with col2:
            num_beams = st.slider(
                "束搜索 (Num Beams)",
                min_value=1,
                max_value=10,
                value=int(config.indextts2.get("num_beams", 3)),
                step=1,
                help="束搜索的 beam 数量，值越大质量可能越好但速度越慢"
            )
            
            repetition_penalty = st.slider(
                "重复惩罚 (Repetition Penalty)",
                min_value=1.0,
                max_value=20.0,
                value=float(config.indextts2.get("repetition_penalty", 10.0)),
                step=0.5,
                help="值越大越能避免重复，但过大可能导致不自然"
            )
            
            do_sample = st.checkbox(
                "启用采样",
                value=config.indextts2.get("do_sample", True),
                help="启用采样可以获得更自然的语音"
            )
    
    # 显示使用说明
    with st.expander("💡 IndexTTS2 使用说明", expanded=False):
        st.markdown("""
        **零样本语音克隆**
        
        1. **准备参考音频**：上传或指定一段清晰的音频文件（建议 3-10 秒）
        2. **设置 API 地址**：确保 IndexTTS2 服务正常运行
        3. **开始合成**：系统会自动使用参考音频的音色合成新语音
        
        **注意事项**：
        - 参考音频质量直接影响合成效果
        - 建议使用无背景噪音的清晰音频
        - 文本长度建议控制在合理范围内
        - 首次合成可能需要较长时间
        """)
    
    # 保存配置
    config.indextts2["api_url"] = api_url
    config.indextts2["reference_audio"] = reference_audio
    config.indextts2["infer_mode"] = infer_mode
    config.indextts2["temperature"] = temperature
    config.indextts2["top_p"] = top_p
    config.indextts2["top_k"] = top_k
    config.indextts2["num_beams"] = num_beams
    config.indextts2["repetition_penalty"] = repetition_penalty
    config.indextts2["do_sample"] = do_sample
    
    # 保存 voice_name 用于兼容性
    if reference_audio:
        config.ui["voice_name"] = f"indextts2:{reference_audio}"


def render_voice_preview_new(tr, selected_engine):
    """渲染新的语音试听功能"""
    if st.button("🎵 试听语音合成", use_container_width=True):
        play_content = "感谢关注 DramaClip，短剧高光自动剪辑，让精彩不再错过"

        # 根据选择的引擎获取对应的语音配置
        voice_name = ""
        voice_rate = 1.0
        voice_pitch = 1.0

        if selected_engine == "edge_tts":
            voice_name = config.ui.get("edge_voice_name", "zh-CN-XiaoyiNeural-Female")
            voice_rate = config.ui.get("edge_rate", 1.0)
            voice_pitch = 1.0 + (config.ui.get("edge_pitch", 0) / 100.0)
        elif selected_engine == "azure_speech":
            voice_name = config.ui.get("azure_voice_name", "zh-CN-XiaoxiaoMultilingualNeural")
            voice_rate = config.ui.get("azure_rate", 1.0)
            voice_pitch = 1.0 + (config.ui.get("azure_pitch", 0) / 100.0)
        elif selected_engine == "soulvoice":
            voice_uri = config.soulvoice.get("voice_uri", "")
            if voice_uri:
                if not voice_uri.startswith("soulvoice:") and not voice_uri.startswith("speech:"):
                    voice_name = f"soulvoice:{voice_uri}"
                else:
                    voice_name = voice_uri if voice_uri.startswith("soulvoice:") else f"soulvoice:{voice_uri}"
            voice_rate = 1.0  # SoulVoice 使用默认语速
            voice_pitch = 1.0  # SoulVoice 不支持音调调节
        elif selected_engine == "tencent_tts":
            voice_type = config.ui.get("tencent_voice_type", "101001")
            voice_name = f"tencent:{voice_type}"
            voice_rate = config.ui.get("tencent_rate", 1.0)
            voice_pitch = 1.0  # 腾讯云 TTS 不支持音调调节
        elif selected_engine == "qwen3_tts":
            vt = config.ui.get("qwen_voice_type", "Cherry")
            voice_name = f"qwen3:{vt}"
            voice_rate = config.ui.get("qwen3_rate", 1.0)
            voice_pitch = 1.0  # Qwen3 TTS 不支持音调调节
        elif selected_engine == "cosyvoice":
            cv = config.cosyvoice.get("voice", "longanyang")
            voice_name = f"cosyvoice:{cv}"
            voice_rate = config.ui.get("cosyvoice_rate", 1.0)
            voice_pitch = 1.0  # CosyVoice 不支持音调调节
        elif selected_engine == "indextts2":
            reference_audio = config.indextts2.get("reference_audio", "")
            if reference_audio:
                voice_name = f"indextts2:{reference_audio}"
            voice_rate = 1.0  # IndexTTS2 不支持速度调节
            voice_pitch = 1.0  # IndexTTS2 不支持音调调节

        if not voice_name:
            st.error("请先配置语音设置")
            return

        with st.spinner("正在合成语音..."):
            temp_dir = utils.storage_dir("temp", create=True)
            audio_file = os.path.join(temp_dir, f"tmp-voice-{str(uuid4())}.mp3")

            sub_maker = voice.tts(
                text=play_content,
                voice_name=voice_name,
                voice_rate=voice_rate,
                voice_pitch=voice_pitch,
                voice_file=audio_file,
                tts_engine=st.session_state.get('tts_engine')
            )

            if sub_maker and os.path.exists(audio_file):
                st.success("✅ 语音合成成功！")

                # 播放音频
                with open(audio_file, 'rb') as audio_file_obj:
                    audio_bytes = audio_file_obj.read()
                    st.audio(audio_bytes, format='audio/mp3')

                # 清理临时文件
                try:
                    os.remove(audio_file)
                except:
                    pass
            else:
                st.error("❌ 语音合成失败，请检查配置")


def render_azure_v2_settings(tr):
    """渲染Azure V2语音设置（保留兼容性）"""
    saved_azure_speech_region = config.azure.get("speech_region", "")
    saved_azure_speech_key = config.azure.get("speech_key", "")

    azure_speech_region = st.text_input(
        tr("Speech Region"),
        value=saved_azure_speech_region
    )
    azure_speech_key = st.text_input(
        tr("Speech Key"),
        value=saved_azure_speech_key,
        type="password"
    )

    config.azure["speech_region"] = azure_speech_region
    config.azure["speech_key"] = azure_speech_key


def render_voice_parameters(tr, voice_name):
    """渲染语音参数设置（保留兼容性）"""
    # 音量 - 使用统一的默认值
    voice_volume = st.slider(
        tr("Speech Volume"),
        min_value=AudioVolumeDefaults.MIN_VOLUME,
        max_value=AudioVolumeDefaults.MAX_VOLUME,
        value=AudioVolumeDefaults.VOICE_VOLUME,
        step=0.01,
        help=tr("Adjust the volume of the original audio")
    )
    st.session_state['voice_volume'] = voice_volume

    # 检查是否为 SoulVoice 引擎
    is_soulvoice = voice.is_soulvoice_voice(voice_name)

    # 语速
    if is_soulvoice:
        # SoulVoice 支持更精细的语速控制
        voice_rate = st.slider(
            tr("Speech Rate"),
            min_value=0.5,
            max_value=2.0,
            value=1.0,
            step=0.1,
            help="SoulVoice 语音速度控制"
        )
    else:
        # Azure TTS 使用预设选项
        voice_rate = st.selectbox(
            tr("Speech Rate"),
            options=[0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0],
            index=2,
        )
    st.session_state['voice_rate'] = voice_rate

    # 音调 - SoulVoice 不支持音调调节
    if not is_soulvoice:
        voice_pitch = st.selectbox(
            tr("Speech Pitch"),
            options=[0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0],
            index=2,
        )
        st.session_state['voice_pitch'] = voice_pitch
    else:
        # SoulVoice 不支持音调调节，设置默认值
        st.session_state['voice_pitch'] = 1.0
        st.info("ℹ️ SoulVoice 引擎不支持音调调节")


def render_voice_preview(tr, voice_name):
    """渲染语音试听功能"""
    if st.button(tr("Play Voice")):
        play_content = "感谢关注 DramaClip，短剧高光自动剪辑，让精彩不再错过"
        if not play_content:
            play_content = st.session_state.get('video_script', '')
        if not play_content:
            play_content = tr("Voice Example")

        with st.spinner(tr("Synthesizing Voice")):
            temp_dir = utils.storage_dir("temp", create=True)
            audio_file = os.path.join(temp_dir, f"tmp-voice-{str(uuid4())}.mp3")

            sub_maker = voice.tts(
                text=play_content,
                voice_name=voice_name,
                voice_rate=st.session_state.get('voice_rate', 1.0),
                voice_pitch=st.session_state.get('voice_pitch', 1.0),
                voice_file=audio_file,
            )

            # 如果语音文件生成失败，使用默认内容重试
            if not sub_maker:
                play_content = "This is a example voice. if you hear this, the voice synthesis failed with the original content."
                sub_maker = voice.tts(
                    text=play_content,
                    voice_name=voice_name,
                    voice_rate=st.session_state.get('voice_rate', 1.0),
                    voice_pitch=st.session_state.get('voice_pitch', 1.0),
                    voice_file=audio_file,
                )

            if sub_maker and os.path.exists(audio_file):
                st.success(tr("Voice synthesis successful"))
                st.audio(audio_file, format="audio/mp3")
                if os.path.exists(audio_file):
                    os.remove(audio_file)
            else:
                st.error(tr("Voice synthesis failed"))


def render_bgm_settings(tr):
    """渲染背景音乐设置"""
    # 背景音乐选项
    bgm_options = [
        (tr("No Background Music"), ""),
        (tr("Random Background Music"), "random"),
        (tr("Custom Background Music"), "custom"),
    ]

    selected_index = st.selectbox(
        tr("Background Music"),
        index=1,
        options=range(len(bgm_options)),
        format_func=lambda x: bgm_options[x][0],
    )

    # 获取选择的背景音乐类型
    bgm_type = bgm_options[selected_index][1]
    st.session_state['bgm_type'] = bgm_type

    # 自定义背景音乐处理
    if bgm_type == "custom":
        custom_bgm_file = st.text_input(tr("Custom Background Music File"))
        if custom_bgm_file and os.path.exists(custom_bgm_file):
            st.session_state['bgm_file'] = custom_bgm_file

    # 背景音乐音量 - 使用统一的默认值
    bgm_volume = st.slider(
        tr("Background Music Volume"),
        min_value=AudioVolumeDefaults.MIN_VOLUME,
        max_value=AudioVolumeDefaults.MAX_VOLUME,
        value=AudioVolumeDefaults.BGM_VOLUME,
        step=0.01,
        help=tr("Adjust the volume of the original audio")
    )
    st.session_state['bgm_volume'] = bgm_volume


def get_audio_params():
    """获取音频参数"""
    return {
        'voice_name': config.ui.get("voice_name", ""),
        'voice_volume': st.session_state.get('voice_volume', AudioVolumeDefaults.VOICE_VOLUME),
        'voice_rate': st.session_state.get('voice_rate', 1.0),
        'voice_pitch': st.session_state.get('voice_pitch', 1.0),
        'bgm_type': st.session_state.get('bgm_type', 'random'),
        'bgm_file': st.session_state.get('bgm_file', ''),
        'bgm_volume': st.session_state.get('bgm_volume', AudioVolumeDefaults.BGM_VOLUME),
        'tts_engine': st.session_state.get('tts_engine', "edge_tts"),
    }
