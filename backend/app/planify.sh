#!/bin/bash
#
# Planify CLI - Unix/Linux/macOS 启动脚本
#
# 用于在任意工作目录中启动 Planify REPL。
# 用户只需 cd 到工作目录，然后执行此脚本即可。
#

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 获取 planify 根目录（向上两级）
PLANIFY_ROOT="$(dirname "$SCRIPT_DIR")"

# 切换到当前工作目录（用户的工作目录）
WORK_DIR="$(pwd)"

echo "========================================"
echo "Planify CLI - 单用户模式"
echo "========================================"
echo "工作目录: $WORK_DIR"
echo "Planify 根目录: $PLANIFY_ROOT"
echo "========================================"
echo ""

# 检查 Python 是否可用
if ! command -v python &> /dev/null; then
    if ! command -v python3 &> /dev/null; then
        echo "错误: 未找到 Python 或 python3"
        exit 1
    fi
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python"
fi

echo "使用 Python: $PYTHON_CMD"
echo ""

# 运行 cli.py（单用户模式）
# 设置 PYTHONPATH 包含 planify 根目录
export PYTHONPATH="$PLANIFY_ROOT:$PYTHONPATH"

# 执行 cli.py
"$PYTHON_CMD" "$PLANIFY_ROOT/cli.py"
