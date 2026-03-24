#!/usr/bin/env python3
# Harness: context isolation -- protecting the model's clarity of thought.
"""
s04_subagent.py - Subagent（子代理）模式

本示例展示了如何通过生成子代理来实现上下文隔离。
子代理使用全新的 messages=[] 开始工作，共享文件系统，
完成后只返回摘要给父代理。

架构图：
    Parent agent                     Subagent
    +------------------+             +------------------+
    | messages=[...]   |             | messages=[]      |  <-- 全新上下文
    |                  |  dispatch   |                  |
    | tool: task       | ---------->| while tool_use:  |
    |   prompt="..."   |            |   call tools     |
    |   description="" |            |   append results |
    |                  |  summary   |                  |
    |   result = "..." | <--------- | return last text |
    +------------------+             +------------------+
              |
    Parent context stays clean.      （父代理上下文保持清洁）
    Subagent context is discarded.   （子代理上下文被丢弃）

关键洞察: "进程隔离天然带来上下文隔离。"
"""

# =============================================================================
# 导入依赖
# =============================================================================
import os
import subprocess
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

# 加载环境变量
load_dotenv(override=True)

# 如果配置了自定义 API 端点，移除默认的 auth token
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# =============================================================================
# 全局配置
# =============================================================================
WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

# 父代理系统提示词：强调使用 task 工具委派子任务
SYSTEM = f"You are a coding agent at {WORKDIR}. Use the task tool to delegate exploration or subtasks."

# 子代理系统提示词：强调完成任务并总结结果
SUBAGENT_SYSTEM = f"You are a coding subagent at {WORKDIR}. Complete the given task, then summarize your findings."


# =============================================================================
# 工具实现函数（父代理和子代理共享）
#
# 这些是基础的文件操作和命令执行工具，不涉及代理调度。
# 所有工具都有：
# - 安全检查（路径验证、危险命令过滤）
# - 错误处理
# - 输出截断（防止上下文膨胀）
# =============================================================================

def safe_path(p: str) -> Path:
    """
    安全地解析文件路径，防止路径遍历攻击

    Args:
        p: 相对路径字符串

    Returns:
        解析后的绝对路径

    Raises:
        ValueError: 当路径试图逃出工作目录时
    """
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    """
    执行 shell 命令

    包含危险命令黑名单，超时限制为 120 秒。

    Args:
        command: 要执行的 shell 命令

    Returns:
        命令输出，截断至 50000 字符
    """
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(
            command, shell=True, cwd=WORKDIR,
            capture_output=True, text=True, timeout=120
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int = None) -> str:
    """
    读取文件内容

    Args:
        path: 文件路径
        limit: 可选的行数限制

    Returns:
        文件内容，截断至 50000 字符
    """
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    """
    写入文件（覆盖现有文件）
    """
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    """
    编辑文件：精确替换第一个匹配的文本
    """
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# =============================================================================
# 工具处理器映射
# =============================================================================
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}

# =============================================================================
# 子代理工具定义
#
# 注意：子代理只有基础工具，没有 "task" 工具
# 这样可以防止递归生成子代理（子代理不能再生成孙代理）
# =============================================================================
CHILD_TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
]


# =============================================================================
# 子代理执行器
#
# 核心特点：
# 1. 全新上下文：messages=[] 从零开始
# 2. 过滤工具集：只有基础工具，无 task 工具
# 3. 只返回摘要：子代理的所有中间过程都被丢弃
# 4. 安全限制：最多 30 轮，防止无限循环
# =============================================================================
def run_subagent(prompt: str) -> str:
    """
    启动一个子代理来执行任务

    子代理的工作流程：
    1. 使用全新的 messages=[] 开始（上下文隔离）
    2. 最多运行 30 轮工具调用
    3. 完成后只返回最终的文本摘要
    4. 子代理的完整上下文被丢弃

    Args:
        prompt: 传递给子代理的任务描述

    Returns:
        子代理的最终文本摘要（用于注入父代理上下文）
    """
    # 全新的消息历史 -- 这是上下文隔离的关键
    sub_messages = [{"role": "user", "content": prompt}]

    # 最多 30 轮，防止无限循环
    for _ in range(30):
        response = client.messages.create(
            model=MODEL,
            system=SUBAGENT_SYSTEM,
            messages=sub_messages,
            tools=CHILD_TOOLS,  # 只有基础工具，无 task 工具
            max_tokens=8000,
        )

        sub_messages.append({"role": "assistant", "content": response.content})

        # 如果不是因为工具调用而停止，说明任务完成
        if response.stop_reason != "tool_use":
            break

        # 处理工具调用
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                # 工具结果也截断，防止子代理上下文膨胀
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output)[:50000]
                })

        sub_messages.append({"role": "user", "content": results})

    # 只返回最终的文本摘要 -- 子代理上下文被丢弃
    # 这保护了父代理的上下文不被子代理的中间过程污染
    return "".join(b.text for b in response.content if hasattr(b, "text")) or "(no summary)"


# =============================================================================
# 父代理工具定义
#
# 父代理拥有：
# - 所有基础工具（bash, read_file, write_file, edit_file）
# - task 工具（用于派发子代理）
# =============================================================================
PARENT_TOOLS = CHILD_TOOLS + [
    {
        "name": "task",
        "description": "Spawn a subagent with fresh context. It shares the filesystem but not conversation history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "description": {"type": "string", "description": "Short description of the task"}
            },
            "required": ["prompt"]
        }
    },
]


# =============================================================================
# 父代理主循环
#
# 职责：
# - 处理用户请求
# - 调用基础工具（bash, read_file, write_file, edit_file）
# - 通过 task 工具派发子代理
# - 将子代理的摘要结果注入到自己的上下文中
# =============================================================================
def agent_loop(messages: list):
    """
    父代理的主循环

    与普通 agent 循环的区别：
    - 额外处理 "task" 工具
    - task 工具调用 run_subagent() 并获取摘要
    """
    while True:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=PARENT_TOOLS,  # 包含 task 工具
            max_tokens=8000,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return

        results = []
        for block in response.content:
            if block.type == "tool_use":
                # 特殊处理 task 工具
                if block.name == "task":
                    desc = block.input.get("description", "subtask")
                    print(f"> task ({desc}): {block.input['prompt'][:80]}")
                    # 调用子代理执行任务
                    output = run_subagent(block.input["prompt"])
                else:
                    # 其他基础工具直接调用
                    handler = TOOL_HANDLERS.get(block.name)
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"

                # 打印工具结果（截断显示）
                print(f"  {str(output)[:200]}")

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output)
                })

        messages.append({"role": "user", "content": results})


# =============================================================================
# 主程序入口（REPL 模式）
# =============================================================================
if __name__ == "__main__":
    history = []

    while True:
        try:
            query = input("\033[36ms04 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        if query.strip().lower() in ("q", "exit", ""):
            break

        history.append({"role": "user", "content": query})
        agent_loop(history)

        # 打印最终响应
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()
