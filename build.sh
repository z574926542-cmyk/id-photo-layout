#!/bin/bash
# 证件照排版工具 - macOS/Linux 一键打包脚本
# 用法：bash build.sh

set -e
cd "$(dirname "$0")"

echo "=============================="
echo " 证件照排版工具 - 打包脚本"
echo "=============================="

echo "[1/3] 安装依赖..."
pip3 install Pillow PyQt5 pyinstaller

echo "[2/3] 清理旧构建..."
rm -rf build dist __pycache__

echo "[3/3] 开始打包（单文件）..."
pyinstaller build.spec --clean --noconfirm

echo ""
echo "=============================="
echo " 打包完成！"
echo " 可执行文件位于：dist/证件照排版工具"
echo "=============================="
