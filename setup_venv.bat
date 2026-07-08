@echo off
:: 设置字符集为 UTF-8，防止控制台中文乱码
chcp 65001 >nul
title MITAKO 客服 Agent 虚拟环境重建工具

echo ===================================================
echo   MITAKO 虾淘AI客服系统 - Python 虚拟环境初始化
echo ===================================================
echo.

:: 1. 检查 Python 环境
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 本机未检测到 Python 命令，请确认已安装 Python 3 并将其添加到系统环境变量 PATH 中。
    pause
    exit /b 1
)

:: 2. 创建 Python 虚拟环境 (venv)
echo [*] 正在创建虚拟环境 venv ...
if exist venv (
    echo [提示] 发现已存在 venv 文件夹，正在清除旧环境...
    rd /s /q venv
)
python -m venv venv
if %errorlevel% neq 0 (
    echo [错误] 创建虚拟环境失败，请检查 Python 版本或权限。
    pause
    exit /b 1
)
echo [成功] 虚拟环境 venv 创建完毕。
echo.

:: 3. 升级 pip (使用清华镜像加速)
echo [*] 正在升级 pip 并配置清华大学镜像源...
venv\Scripts\python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
if %errorlevel% neq 0 (
    echo [警告] 升级 pip 失败，将尝试默认方式安装依赖...
)
echo.

:: 4. 安装 PyTorch CUDA 13 加速版 (针对 2080Ti 等本地 GPU 加速设备)
echo [*] 正在安装 PyTorch 和 torchvision (CUDA 13.2 专版，显卡加速支持)...
echo [提示] 正在从 PyTorch 官方 GPU 仓库安装，请耐心等待...
venv\Scripts\pip.exe install torch torchvision --index-url https://download.pytorch.org/whl/cu132
if %errorlevel% neq 0 (
    echo [错误] GPU 版本的 PyTorch 安装失败，正在尝试使用国内镜像源降级安装 CPU 版本...
    venv\Scripts\pip.exe install torch torchvision -i https://pypi.tuna.tsinghua.edu.cn/simple
)
echo.

:: 5. 一键安装 requirements.txt 依赖库 (使用清华镜像加速)
echo [*] 正在从清华镜像源一键安装 requirements.txt 依赖...
venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if %errorlevel% neq 0 (
    echo [错误] 核心依赖库安装失败，请检查网络连接。
    pause
    exit /b 1
)
echo [成功] 所有依赖库安装完毕！
echo.

echo ===================================================
echo   配置已成功完成！
echo   1. 运行 一键启动-Windows.bat 启动系统。
echo   2. 前端已在 dist/ 下编译打包，main.py 会直接托管最新的 UI。
echo ===================================================
echo.
pause
