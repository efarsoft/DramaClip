@echo off
chcp 65001 >nul
title DramaClip - 短剧自动高光剪辑

echo ========================================
echo    DramaClip 短剧自动高光剪辑系统
echo ========================================
echo.

:: 检查 Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

:: 检查依赖是否已安装
python -c "import streamlit" >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 首次运行，正在安装依赖...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)

:: 检查配置文件
if not exist "config.toml" (
    if exist "config.example.toml" (
        echo [提示] 正在复制配置文件模板...
        copy config.example.toml config.toml
        echo [提示] 已创建 config.toml，请编辑填入 API Key
    )
)

:: 启动服务
echo.
echo [启动] 正在启动 WebUI，请稍候...
echo [提示] 浏览器自动打开后，请编辑 config.toml 填入 API Key
echo.
python webui.py

pause
