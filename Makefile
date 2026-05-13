# DramaClip Backend Makefile (参考)

.PHONY: help build up down restart logs shell clean deploy

# 默认目标
.DEFAULT_GOAL := help

# 颜色定义
GREEN := \033[32m
YELLOW := \033[33m
BLUE := \033[34m
RESET := \033[0m

help: ## 显示帮助信息
 @echo "$(GREEN)DramaClip 管理命令$(RESET)"
 @echo ""
 @echo "$(YELLOW)可用命令:$(RESET)"
 @awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  $(BLUE)%-15s$(RESET) %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build-backend: ## 使用 PyInstaller 打包 Python 后端
 python scripts/build-backend.py

config: ## 检查配置文件
 @if [ -f "config.toml" ]; then \
  echo "$(GREEN)config.toml 存在$(RESET)"; \
 else \
  echo "$(YELLOW)复制示例配置...$(RESET)"; \
  cp config.example.toml config.toml; \
 fi

clean: ## 清理未使用的资源
 @echo "$(YELLOW)清理未使用的资源...$(RESET)"
 rm -rf dist dist-electron build __pycache__
 rm -rf app/**/__pycache__
