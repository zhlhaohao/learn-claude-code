#!/bin/bash
#
# Planify CLI - Unix/Linux/macOS 启动脚本
#
# 用于在任意工作目录中启动 Planify REPL。
# 用户只需 cd 到工作目录，然后执行此脚本即可。
#

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 获取脚本文件名
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

# 如果脚本在 planify/ 目录下，使用该目录
if [ "$SCRIPT_NAME" = "planify.sh" ]; then
    PLANIFY_ROOT="$SCRIPT_DIR"
else
    PLANIFY_ROOT="$(dirname "$SCRIPT_DIR")"
fi

# 保存当前工作目录（用户 cd 到的目录）
WORK_DIR="$(pwd)"

echo "========================================"
echo "Planify CLI - Single User Mode"
echo "========================================"
echo "Work Directory: $WORK_DIR"
echo "Planify Root: $PLANIFY_ROOT"
echo "========================================"
echo ""

# 检查 Python 是否可用
if ! command -v python &> /dev/null; then
    if ! command -v python3 &> /dev/null; then
        echo "Error: Python or python3 not found"
        exit 1
    fi
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python"
fi

echo "Using Python: $PYTHON_CMD"
echo ""

# 设置 PYTHONPATH 包含 planify 根目录
export PYTHONPATH="$PLANIFY_ROOT:$PYTHONPATH"

# 切换到 planify 根目录检查 cli.py
cd "$PLANIFY_ROOT"

# 检查 cli.py 是否存在
if [ ! -f "cli.py" ]; then
    echo "Error: cli.py not found in $PLANIFY_ROOT"
    echo "Looking for cli.py in $(pwd)"
    ls -la | grep cli || echo "cli.py not found"
    exit 1
fi

# 执行 cli.py（先切换到工作目录，确保 Path.cwd() 返回用户目录）
cd "$WORK_DIR"
exec "$PYTHON_CMD" "$PLANIFY_ROOT/cli.py"