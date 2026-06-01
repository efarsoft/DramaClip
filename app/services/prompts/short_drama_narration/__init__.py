#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
@Project: NarratoAI
@File   : __init__.py
@Author : viccy同学
@Date   : 2025/1/7
@Description: 短剧解说提示词模块
"""

from .plot_analysis import PlotAnalysisPrompt
from .script_generation import ScriptGenerationPrompt
from .highlight_narration import HighlightNarrationPrompt
from .narration_refinement import NarrationRefinementPrompt
from ..manager import PromptManager


def register_prompts():
    """注册短剧解说相关的提示词"""
    
    # 注册剧情分析提示词
    plot_analysis_prompt = PlotAnalysisPrompt()
    PromptManager.register_prompt(plot_analysis_prompt, is_default=True)
    
    # 注册解说脚本生成提示词
    script_generation_prompt = ScriptGenerationPrompt()
    PromptManager.register_prompt(script_generation_prompt, is_default=True)

    # 注册高光片段解说脚本生成提示词（NarrationPipeline 专用）
    highlight_narration_prompt = HighlightNarrationPrompt()
    PromptManager.register_prompt(highlight_narration_prompt, is_default=True)

    # 注册成片级解说文案打磨提示词
    refinement_prompt = NarrationRefinementPrompt()
    PromptManager.register_prompt(refinement_prompt, is_default=True)


__all__ = [
    "PlotAnalysisPrompt",
    "ScriptGenerationPrompt",
    "HighlightNarrationPrompt",
    "NarrationRefinementPrompt",
    "register_prompts"
]
