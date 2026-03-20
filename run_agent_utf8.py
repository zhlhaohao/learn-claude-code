#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动脚本 - 自动设置 UTF-8 环境并运行 agents
"""

import os
import subprocess
import sys
from pathlib import Path

def set_utf8_env():
    """设置环境变量确保 UTF-8 支持"""
    # Windows 下设置 PYTHONIOENCODING
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    # 设置 Windows 终端代码页
    if os.name == 'nt':
        try:
            subprocess.run(['chcp', '65001'], check=True, capture_output=True)
        except:
            pass

def main():
    # 检查传入的参数，决定运行哪个 agent
    agent = sys.argv[1] if len(sys.argv) > 1 else 's02'

    print("🚀 启动 Agent (UTF-8 模式)...")
    print(f"运行 {agent}_tool_use.py")
    print()

    # 设置环境
    set_utf8_env()

    # 根据参数运行不同的 agent
    if agent in ['s02', 's02_tool_use']:
        # 运行 s02
        try:
            from agents.s02_tool_use import agent_loop
            history = []
            while True:
                try:
                    query = input("\033[36ms02 >> \033[0m")
                except (EOFError, KeyboardInterrupt):
                    break
                if query.strip().lower() in ("q", "exit", ""):
                    break
                history.append({"role": "user", "content": query})
                agent_loop(history)
                response_content = history[-1]["content"]
                if isinstance(response_content, list):
                    for block in response_content:
                        if hasattr(block, "text"):
                            print(block.text)
                print()
        except ImportError:
            print("错误: 无法导入 s02_tool_use.py")
    elif agent in ['s_full', 'full']:
        # 运行 s_full
        try:
            from agents.s_full import agent_loop
            history = []
            while True:
                try:
                    query = input("\033[36ms_full >> \033[0m")
                except (EOFError, KeyboardInterrupt):
                    break
                if query.strip().lower() in ("q", "exit", ""):
                    break
                if query.strip() == "/compact":
                    if history:
                        print("[手动压缩]")
                        history = history  # 需要实现压缩功能
                    continue
                if query.strip() == "/tasks":
                    print("TODO: 实现任务列表功能")
                    continue
                if query.strip() == "/team":
                    print("TODO: 实现团队列表功能")
                    continue
                if query.strip() == "/inbox":
                    print("TODO: 实现收件箱功能")
                    continue
                history.append({"role": "user", "content": query})
                agent_loop(history)
                print()
        except ImportError:
            print("错误: 无法导入 s_full.py")
    else:
        print(f"错误: 未知 agent '{agent}'")
        print("支持的 agent: s02, s_full")

if __name__ == "__main__":
    main()