@echo off
chcp 65001 >nul
echo ==============================
echo  证件照排版工具 - Windows 打包
echo ==============================

echo [1/3] 安装依赖...
pip install Pillow PyQt5 pyinstaller

echo [2/3] 清理旧构建...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [3/3] 开始打包（单文件）...
pyinstaller build.spec --clean --noconfirm

echo.
echo ==============================
echo  打包完成！
echo  文件位于：dist\证件照排版工具.exe
echo ==============================
pause
