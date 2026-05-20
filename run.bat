@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe main.py %*
) else (
    echo [警告] 未找到虚拟环境，使用全局 Python 启动...
    python main.py %*
)
