@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  Nemo Assistant  ^—  打包构建脚本
echo ============================================================

REM 优先使用虚拟环境
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

echo [1/3] 安装 PyInstaller...
%PYTHON% -m pip install --quiet --upgrade pyinstaller
if errorlevel 1 ( echo [错误] PyInstaller 安装失败 & pause & exit /b 1 )

echo [2/3] 安装项目依赖...
%PYTHON% -m pip install --quiet .
if errorlevel 1 ( echo [错误] 依赖安装失败 & pause & exit /b 1 )

set "DIST_EXE=dist\Nemo Assistant.exe"
if exist "%DIST_EXE%" (
    echo [准备] 清理旧可执行文件...
    del /f /q "%DIST_EXE%" >nul 2>nul
    if exist "%DIST_EXE%" (
        echo [错误] 无法覆盖 "%DIST_EXE%"。
        echo        请关闭正在运行的 Nemo Assistant，或手动删除该文件后重试。
        pause
        exit /b 1
    )
)

echo [3/3] 打包中，请稍候...
set "LITELLM_LOCAL_MODEL_COST_MAP=True"
%PYTHON% -m PyInstaller --clean --noconfirm Nemo_Assistant.spec
if errorlevel 1 ( echo [错误] PyInstaller 打包失败 & pause & exit /b 1 )

echo.
echo ============================================================
echo  构建完成！单文件可执行程序：dist\Nemo Assistant.exe
echo  内置 tools/assets 已打包进 exe；用户自定义工具存于 data\user_tools
echo ============================================================
pause
