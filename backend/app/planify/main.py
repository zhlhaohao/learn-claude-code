#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Planify - REPL 交互式命令行

提供交互式命令行界面，与代理系统进行对话。

支持的命令：
- 正常对话输入
- /compact - 手动压缩
- /tasks - 列出任务
- /team - 列出队友
- /inbox - 读取收件箱
- /exit - 退出
"""

# ============================================================
# 重要：在任何其他导入之前设置 UTF-8 编码
# ============================================================
import json
import logging
import os
import sys

from pathlib import Path

# 编码模块必须在其他任何导入之前导入
from .core import setup_encoding, apply_safe_stdio

# 应用编码设置
setup_encoding()
apply_safe_stdio()

# 重新配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[]
)

# 确保父目录在导入路径中
sys.path.insert(0, str(Path(__file__).parent))

# 应用导入
from .bootstrap import initialize, get_state
from .agent import run_agent_loop
from .context import auto_compact


def repl() -> None:
    """
    运行交互式命令行界面 (REPL)。
    """
    state = get_state()
    history = []

    while True:
        try:
            query = input("\033[36mplanify >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        query = query.strip()

        # 退出命令
        if query == "/exit":
            break

        # /compact - 手动压缩
        if query == "/compact":
            if history:
                history[:] = auto_compact(
                    history, state.client, state.model, state.config["transcript_dir"]
                )
            continue

        # /tasks - 列出任务
        if query == "/tasks":
            print(state.task_mgr.list_all())
            continue

        # /team - 列出队友
        if query == "/team":
            print(state.team.list_all())
            continue

        # /inbox - 读取收件箱
        if query == "/inbox":
            print(json.dumps(state.bus.read_inbox("lead"), indent=2))
            continue

        # 正常对话
        history.append({"role": "user", "content": query})
        run_agent_loop(
            messages=history,
            client=state.client,
            model=state.model,
            tools=state.tools,
            tool_handlers=state.tool_handlers,
            todo_manager=state.todo_mgr,
            bg_manager=state.bg_mgr,
            bus=state.bus,
            skills_loader=state.skills,
            config=state.config,
            logger=state.logger,
        )

        # 打印最终回答
        if history and len(history) >= 2:
            last_msg = history[-1]
            if last_msg.get("role") == "assistant":
                content = last_msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if hasattr(block, "text"):
                            print(block.text)
                else:
                    print(content)
        print()


# =============================================================================
# 主入口
# =============================================================================
if __name__ == "__main__":
    try:
        initialize()
        repl()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting...")
    except Exception as e:
        print(f"Error: {e}")
        raise
