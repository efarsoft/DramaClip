# GitHub Actions CI/CD 配置指南

## 概述

本项目使用 GitHub Actions 自动构建 Windows 安装包。

## 工作流程

```
┌─────────────────────────────────────────────────────────────────┐
│                      GitHub Actions 触发                         │
├─────────────────────────────────────────────────────────────────┤
│  触发条件：                                                      │
│  1. 推送 tag（如 v1.0.0）→ 自动构建 + 创建 Release              │
│  2. 手动触发（workflow_dispatch）→ 仅构建                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      构建步骤                                    │
├─────────────────────────────────────────────────────────────────┤
│  1. 检出代码                                                     │
│  2. 设置 Node.js 20 + Python 3.11                               │
│  3. 安装 FFmpeg（choco install ffmpeg）                          │
│  4. 安装 Python 依赖 + PyInstaller                              │
│  5. 安装 Node.js 依赖（npm ci）                                  │
│  6. 构建 Python 后端（PyInstaller → backend.exe）                │
│  7. 复制 FFmpeg 到 resources/                                    │
│  8. 构建前端（npm run build:vite）                               │
│  9. 打包 Electron（electron-builder → NSIS 安装包）              │
│  10. 上传产物 + 创建 Release                                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      输出产物                                    │
├─────────────────────────────────────────────────────────────────┤
│  - DramaClip Setup x.x.x.exe  (NSIS 安装包)                     │
│  - DramaClip-x.x.x-win.zip    (便携版)                          │
└─────────────────────────────────────────────────────────────────┘
```

## 使用方法

### 方法一：自动发布（推荐）

1. **更新版本号**

   编辑 `package.json`：
   ```json
   {
     "version": "1.0.0"
   }
   ```

2. **提交更改**
   ```bash
   git add -A
   git commit -m "chore: bump version to 1.0.0"
   git push
   ```

3. **创建 tag 并推送**
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

4. **等待构建完成**
   - 访问 https://github.com/your-username/DramaClip/actions
   - 查看构建进度
   - 构建完成后，Release 页面会自动创建

### 方法二：手动触发

1. 访问 GitHub 仓库的 Actions 页面
2. 选择 "Build Windows Installer" 工作流
3. 点击 "Run workflow"
4. 等待构建完成
5. 在 Actions 的 Artifacts 中下载安装包

## 配置文件说明

### `.github/workflows/build-windows.yml`

```yaml
# 触发条件
on:
  push:
    tags:
      - 'v*'  # 推送 v 开头的 tag 时触发
  workflow_dispatch:  # 允许手动触发

# 构建任务
jobs:
  build-windows:
    runs-on: windows-latest  # 使用 Windows 环境
    
    steps:
      # ... 构建步骤
```

### `electron-builder.yml`

```yaml
appId: com.dramaclip.app
productName: DramaClip
win:
  target:
    - target: nsis  # NSIS 安装包
      arch:
        - x64       # 64 位
nsis:
  oneClick: false                    # 非一键安装
  allowToChangeInstallationDirectory: true  # 允许选择安装目录
  createDesktopShortcut: true        # 创建桌面快捷方式
  createStartMenuShortcut: true      # 创建开始菜单快捷方式
```

## 高级配置

### 1. 代码签名（可选）

如果需要代码签名，需要：

1. **购买代码签名证书**
   - 推荐：Sectigo, DigiCert, GlobalSign

2. **配置 GitHub Secrets**
   - `CSC_LINK`: 证书文件（base64 编码）
   - `CSC_KEY_PASSWORD`: 证书密码

3. **更新 workflow**
   ```yaml
   - name: Build Electron app
     run: npx electron-builder --win --publish never
     env:
       CSC_LINK: ${{ secrets.CSC_LINK }}
       CSC_KEY_PASSWORD: ${{ secrets.CSC_KEY_PASSWORD }}
   ```

### 2. 自动更新

配置 `electron-updater`：

1. **安装依赖**
   ```bash
   npm install electron-updater
   ```

2. **更新 `electron-builder.yml`**
   ```yaml
   publish:
     provider: github
     owner: your-username
     repo: DramaClip
   ```

3. **在主进程中添加更新逻辑**
   ```typescript
   import { autoUpdater } from 'electron-updater';
   
   autoUpdater.checkForUpdatesAndNotify();
   ```

### 3. 多平台构建

如果需要同时构建 macOS 和 Linux 版本：

```yaml
jobs:
  build:
    strategy:
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    
    runs-on: ${{ matrix.os }}
    
    steps:
      # ... 构建步骤
```

## 故障排除

### 问题 1：FFmpeg 找不到

**症状**：构建失败，提示找不到 FFmpeg

**解决**：
```yaml
- name: Install FFmpeg
  run: |
    choco install ffmpeg -y
    # 确保 FFmpeg 在 PATH 中
    ffmpeg -version
```

### 问题 2：PyInstaller 打包失败

**症状**：`backend.exe` 构建失败

**解决**：
1. 检查 `requirements.txt` 是否包含所有依赖
2. 确保 `app/backend_main.py` 入口文件存在
3. 检查是否有隐藏的导入需要手动添加

### 问题 3：electron-builder 失败

**症状**：安装包构建失败

**解决**：
1. 检查 `electron-builder.yml` 配置
2. 确保 `build/` 目录包含 `icon.ico`
3. 检查是否有文件路径问题

### 问题 4：GitHub Token 权限不足

**症状**：无法创建 Release

**解决**：
1. 访问仓库 Settings → Actions → General
2. 确保 "Workflow permissions" 设置为 "Read and write permissions"

## 最佳实践

1. **版本管理**
   - 使用语义化版本（SemVer）
   - 在 `package.json` 和 `config.example.toml` 中同步版本号

2. **发布流程**
   ```bash
   # 1. 更新版本号
   npm version patch  # 或 minor, major
   
   # 2. 推送更改和 tag
   git push && git push --tags
   
   # 3. 等待 CI 构建完成
   # 4. 在 GitHub 上编辑 Release，添加说明
   ```

3. **测试**
   - 在推送 tag 之前，先手动触发 workflow 测试
   - 确保所有测试通过

## 相关链接

- [GitHub Actions 文档](https://docs.github.com/en/actions)
- [electron-builder 文档](https://www.electron.build/)
- [PyInstaller 文档](https://pyinstaller.org/)
