#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Planify 代理系统入口脚本

从 backend/app 目录运行，确保 planify 作为包正确导入。
"""

import sys
from pathlib import Path

# 当前目录设为 backend/app
app_dir = Path(__file__).parent
sys.path.insert(0, str(app_dir))

# 作为包导入 planify.main
from planify.main import initialize, repl

if __name__ == "__main__":
    try:
        initialize()
        repl()
    except KeyboardInterrupt:
        print("\n\n已中断。退出...")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        input("按回车键退出...")
