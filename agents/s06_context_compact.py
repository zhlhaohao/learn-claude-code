#!/usr/bin/env python3
# Harness: compression -- clean memory for infinite sessions.
"""
s06_context_compact.py - Compact（上下文压缩）

三层压缩流水线，让 Agent 可以无限期工作：

    每一轮：
    +------------------+
    | Tool call result |
    +------------------+
            |
            v
    [Layer 1: micro_compact]        （静默，每轮执行）
      将最近 3 轮之前的 tool_result 内容
      替换为 "[Previous: used {tool_name}]"
            |
            v
    [检查: tokens > 50000?]
       |               |
       no              yes
       |               |
       v               v
    continue    [Layer 2: auto_compact]
                  保存完整对话到 .transcripts/
                  让 LLM 总结对话
                  用 [summary] 替换所有消息
                        |
                        v
                [Layer 3: compact tool]
                  模型调用 compact -> 立即压缩
                  与 auto 相同，但由手动触发

关键洞察: "Agent 可以策略性地遗忘，从而无限期工作。"
"""

# =============================================================================
# 导入依赖
# =============================================================================
import json
import os
import subprocess
import time
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

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks."

# =============================================================================
# 压缩相关常量
# =============================================================================
THRESHOLD = 50000       # 触发自动压缩的 token 阈值
TRANSCRIPT_DIR = WORKDIR / ".transcripts"  # 完整对话存档目录
KEEP_RECENT = 3         # micro_compact 保留的最近工具结果数量


def estimate_tokens(messages: list) -> int:
    """
    粗略估算消息的 token 数量

    使用简单的启发式方法：约 4 个字符 = 1 个 token

    Args:
        messages: 消息列表

    Returns:
        估算的 token 数量
    """
    return len(str(messages)) // 4


# =============================================================================
# Layer 1: micro_compact - 微压缩
#
# 策略：静默替换旧的 tool_result 内容为简短占位符
# - 每轮都执行（静默）
# - 保留最近 KEEP_RECENT 个工具结果的完整内容
# - 旧的结果替换为 "[Previous: used {tool_name}]"
#
# 效果：渐进式压缩，避免突然的上下文膨胀
# =============================================================================
def micro_compact(messages: list) -> list:
    """
    微压缩：替换旧的 tool_result 为占位符

    工作流程：
    1. 收集所有 tool_result 条目
    2. 如果数量 <= KEEP_RECENT，不做任何处理
    3. 找到每个 tool_result 对应的工具名称
    4. 将旧结果的内容替换为简短占位符

    Args:
        messages: 消息列表（会被原地修改）

    Returns:
        修改后的消息列表
    """
    # 收集所有 tool_result 条目：(消息索引, 部分索引, tool_result 字典)
    tool_results = []
    for msg_idx, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part_idx, part in enumerate(msg["content"]):
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    tool_results.append((msg_idx, part_idx, part))

    # 如果工具结果数量不超过保留数量，无需压缩
    if len(tool_results) <= KEEP_RECENT:
        return messages

    # 建立 tool_use_id -> tool_name 的映射
    # 通过遍历之前的 assistant 消息来匹配
    tool_name_map = {}
    for msg in messages:
        if msg["role"] == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "type") and block.type == "tool_use":
                        tool_name_map[block.id] = block.name

    # 压缩旧结果（保留最后 KEEP_RECENT 个）
    to_clear = tool_results[:-KEEP_RECENT]
    for _, _, result in to_clear:
        # 只压缩内容较长的结果（>100 字符）
        if isinstance(result.get("content"), str) and len(result["content"]) > 100:
            tool_id = result.get("tool_use_id", "")
            tool_name = tool_name_map.get(tool_id, "unknown")
            result["content"] = f"[Previous: used {tool_name}]"

    return messages


# =============================================================================
# Layer 2: auto_compact - 自动压缩
#
# 策略：当 token 数超过阈值时，完整压缩对话
# 1. 保存完整对话到 .transcripts/ 目录（不丢失任何信息）
# 2. 调用 LLM 生成对话摘要
# 3. 用摘要替换所有消息
#
# 效果：大幅减少上下文，同时保留关键信息
# =============================================================================
def auto_compact(messages: list) -> list:
    """
    自动压缩：保存对话并生成摘要

    工作流程：
    1. 将完整对话保存到 JSONL 文件（存档）
    2. 调用 LLM 生成对话摘要
    3. 返回压缩后的消息列表（包含摘要）

    Args:
        messages: 当前消息列表

    Returns:
        压缩后的新消息列表
    """
    # 1. 保存完整对话到磁盘（可追溯）
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    print(f"[transcript saved: {transcript_path}]")

    # 2. 调用 LLM 生成摘要
    conversation_text = json.dumps(messages, default=str)[:80000]  # 截断防止超出限制
    response = client.messages.create(
        model=MODEL,
        messages=[{
            "role": "user",
            "content": (
                "Summarize this conversation for continuity. Include: "
                "1) What was accomplished, 2) Current state, 3) Key decisions made. "
                "Be concise but preserve critical details.\n\n" + conversation_text
            )
        }],
        max_tokens=2000,
    )
    summary = response.content[0].text

    # 3. 返回压缩后的消息（用摘要替换所有历史）
    return [
        {
            "role": "user",
            "content": f"[Conversation compressed. Transcript: {transcript_path}]\n\n{summary}"
        },
        {
            "role": "assistant",
            "content": "Understood. I have the context from the summary. Continuing."
        },
    ]


# =============================================================================
# 工具实现函数
# =============================================================================
def safe_path(p: str) -> Path:
    """安全地解析文件路径，防止路径遍历攻击"""
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    """执行 shell 命令，包含危险命令过滤"""
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
    """读取文件内容"""
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    """写入文件"""
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    """编辑文件：精确替换文本"""
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
    # compact 工具：模型手动触发压缩，返回提示信息
    "compact":    lambda **kw: "Manual compression requested.",
}

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    # compact 工具：允许模型手动触发对话压缩
    {"name": "compact", "description": "Trigger manual conversation compression.",
     "input_schema": {"type": "object", "properties": {"focus": {"type": "string", "description": "What to preserve in the summary"}}}},
]


# =============================================================================
# Agent 主循环（集成三层压缩）
#
# 压缩触发时机：
# - Layer 1 (micro_compact): 每轮 LLM 调用前
# - Layer 2 (auto_compact): token 超过阈值时
# - Layer 3 (manual compact): 模型调用 compact 工具时
# =============================================================================
def agent_loop(messages: list):
    """
    Agent 主循环，集成三层压缩机制

    压缩时机：
    1. 每轮开始前执行 micro_compact
    2. token 超过 THRESHOLD 时执行 auto_compact
    3. 模型调用 compact 工具时执行手动压缩
    """
    while True:
        # Layer 1: 微压缩（每轮静默执行）
        micro_compact(messages)

        # Layer 2: 自动压缩（token 超过阈值时触发）
        if estimate_tokens(messages) > THRESHOLD:
            print("[auto_compact triggered]")
            messages[:] = auto_compact(messages)

        # 调用 LLM
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return

        # 处理工具调用
        results = []
        manual_compact = False
        for block in response.content:
            if block.type == "tool_use":
                # 检测 compact 工具调用
                if block.name == "compact":
                    manual_compact = True
                    output = "Compressing..."
                else:
                    handler = TOOL_HANDLERS.get(block.name)
                    try:
                        output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                    except Exception as e:
                        output = f"Error: {e}"

                print(f"> {block.name}: {str(output)[:200]}")
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output)
                })

        messages.append({"role": "user", "content": results})

        # Layer 3: 手动压缩（模型主动请求）
        if manual_compact:
            print("[manual compact]")
            messages[:] = auto_compact(messages)


# =============================================================================
# 主程序入口（REPL 模式）
# =============================================================================
if __name__ == "__main__":
    history = []

    while True:
        try:
            query = input("\033[36ms06 >> \033[0m")
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
