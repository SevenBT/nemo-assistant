@echo off
chcp 65001 >nul
echo ============================================================
echo  AI Agent  ^—  打包构建脚本
echo ============================================================

echo [1/4] 安装 PyInstaller...
python -m pip install --quiet --upgrade pyinstaller
if errorlevel 1 ( echo [错误] PyInstaller 安装失败 & pause & exit /b 1 )

echo [2/4] 安装项目依赖...
python -m pip install --quiet -r requirements.txt
if errorlevel 1 ( echo [错误] 依赖安装失败 & pause & exit /b 1 )

echo [3/4] 打包中，请稍候...
python -m PyInstaller --clean --noconfirm AI_Agent.spec
if errorlevel 1 ( echo [错误] PyInstaller 打包失败 & pause & exit /b 1 )

echo [4/4] 复制 tools 目录...
if exist "tools" (
    xcopy /E /I /Y "tools" "dist\tools" >nul
    echo      tools 目录已复制
)

echo.
echo ============================================================
echo  构建完成！可执行文件：dist\AI Agent.exe
echo ============================================================
pause
