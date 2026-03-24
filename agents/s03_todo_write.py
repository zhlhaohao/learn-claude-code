#!/usr/bin/env python3
# Harness: planning -- keeping the model on course without scripting the route.
"""
s03_todo_write.py - TodoWrite 示例

本示例展示了如何让 AI Agent 通过 TodoManager 追踪自己的任务进度。
当模型忘记更新待办事项时，会自动注入一个提醒。

核心机制：
    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> | Tools   |
    |  prompt  |      |       |      | + todo  |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                                |
                    +-----------+-----------+
                    | TodoManager state     |
                    | [ ] task A            |
                    | [>] task B <- doing   |
                    | [x] task C            |
                    +-----------------------+
                                |
                    if rounds_since_todo >= 3:
                      inject <reminder>

关键洞察: "Agent 可以追踪自己的进度 —— 而且我可以看到它。"
"""

# =============================================================================
# 导入依赖
# =============================================================================
import os
import subprocess
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量，override=True 表示覆盖已存在的环境变量
load_dotenv(override=True)

# 如果配置了自定义 API 端点，移除默认的 auth token（避免冲突）
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# =============================================================================
# 全局配置
# =============================================================================
WORKDIR = Path.cwd()  # 当前工作目录，用于限制文件操作范围
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))  # Anthropic API 客户端
MODEL = os.environ["MODEL_ID"]  # 使用的模型 ID

# 系统提示词：定义 Agent 的行为规范
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use the todo tool to plan multi-step tasks. Mark in_progress before starting, completed when done.
Prefer tools over prose."""


# =============================================================================
# TodoManager: 结构化的任务状态管理器
#
# 职责：
# - 管理待办事项列表（最多 20 项）
# - 验证任务状态（pending/in_progress/completed）
# - 确保同一时间只有一个任务处于 in_progress 状态
# - 渲染可读的任务列表输出
# =============================================================================
class TodoManager:
    def __init__(self):
        """初始化空的待办事项列表"""
        self.items = []

    def update(self, items: list) -> str:
        """
        更新待办事项列表

        Args:
            items: 待办事项列表，每项包含 id, text, status

        Returns:
            渲染后的待办事项字符串

        Raises:
            ValueError: 当超过 20 项、缺少必要字段、状态无效或多任务同时进行时
        """
        # 限制最多 20 个待办事项，防止上下文膨胀
        if len(items) > 20:
            raise ValueError("Max 20 todos allowed")

        validated = []
        in_progress_count = 0

        for i, item in enumerate(items):
            # 提取并清理字段
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))

            # 验证 text 字段
            if not text:
                raise ValueError(f"Item {item_id}: text required")

            # 验证 status 字段（只允许三种状态）
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {item_id}: invalid status '{status}'")

            # 统计 in_progress 数量
            if status == "in_progress":
                in_progress_count += 1

            validated.append({"id": item_id, "text": text, "status": status})

        # 确保同一时间只有一个任务在进行中（避免多任务混乱）
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")

        self.items = validated
        return self.render()

    def render(self) -> str:
        """
        渲染待办事项为可读字符串

        格式示例：
            [ ] #1: 待处理的任务
            [>] #2: 正在进行的任务
            [x] #3: 已完成的任务

            (1/3 completed)
        """
        if not self.items:
            return "No todos."

        lines = []
        for item in self.items:
            # 状态标记：[ ] 待处理, [>] 进行中, [x] 已完成
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")

        # 计算完成进度
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")

        return "\n".join(lines)


# 全局 TodoManager 实例
TODO = TodoManager()


# =============================================================================
# 工具实现函数
#
# 这些函数实现了 Agent 可用的工具，所有工具都：
# - 接受字符串参数
# - 返回字符串结果
# - 处理异常并返回错误信息
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

    包含基本的安全检查，阻止危险的系统命令。
    超时限制为 120 秒。

    Args:
        command: 要执行的 shell 命令

    Returns:
        命令的输出（stdout + stderr），截断至 50000 字符
    """
    # 危险命令黑名单
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"

    try:
        r = subprocess.run(
            command,
            shell=True,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=120
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int = None) -> str:
    """
    读取文件内容

    Args:
        path: 文件路径（相对于工作目录）
        limit: 可选，限制读取的行数

    Returns:
        文件内容，截断至 50000 字符
    """
    try:
        lines = safe_path(path).read_text().splitlines()
        # 如果指定了行数限制，截断并添加提示
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    """
    写入文件内容（覆盖现有文件）

    Args:
        path: 文件路径（相对于工作目录）
        content: 要写入的内容

    Returns:
        操作结果信息
    """
    try:
        fp = safe_path(path)
        # 自动创建父目录
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    """
    编辑文件：替换精确匹配的文本（仅替换第一个匹配）

    Args:
        path: 文件路径
        old_text: 要替换的原文
        new_text: 替换后的新文本

    Returns:
        操作结果信息
    """
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        # 只替换第一个匹配项
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# =============================================================================
# 工具注册
#
# TOOL_HANDLERS: 工具名称到处理函数的映射
# TOOLS: 传递给 Claude API 的工具定义（符合 Anthropic 工具使用规范）
# =============================================================================
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),
}

TOOLS = [
    # bash 工具：执行 shell 命令
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},

    # read_file 工具：读取文件
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},

    # write_file 工具：写入文件
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},

    # edit_file 工具：编辑文件（精确文本替换）
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},

    # todo 工具：更新待办事项列表
    {"name": "todo", "description": "Update task list. Track progress on multi-step tasks.",
     "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["id", "text", "status"]}}}, "required": ["items"]}},
]


# =============================================================================
# Agent 主循环（带提醒注入机制）
#
# 核心逻辑：
# 1. 调用 Claude API 获取响应
# 2. 处理工具调用
# 3. 追踪是否使用了 todo 工具
# 4. 如果连续 3 轮未使用 todo，注入提醒
# =============================================================================
def agent_loop(messages: list):
    """
    Agent 主循环

    Args:
        messages: 对话历史列表

    核心机制：
    - rounds_since_todo: 追踪距离上次使用 todo 工具的轮数
    - 当达到 3 轮时，自动注入 "<reminder>Update your todos.</reminder>"
    """
    rounds_since_todo = 0

    while True:
        # 调用 Claude API（提醒会在下方作为 tool_result 注入）
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )

        # 将助手响应添加到对话历史
        messages.append({"role": "assistant", "content": response.content})

        # 如果不是因为工具调用而停止，则结束循环
        if response.stop_reason != "tool_use":
            return

        # 处理所有工具调用
        results = []
        used_todo = False

        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"

                # 打印工具调用结果（截断至 200 字符）
                print(f"> {block.name}: {str(output)[:200]}")

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output)
                })

                # 检查是否使用了 todo 工具
                if block.name == "todo":
                    used_todo = True

        # 更新计数器：使用了 todo 则重置，否则递增
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1

        # 如果连续 3 轮未使用 todo，在结果开头注入提醒
        if rounds_since_todo >= 3:
            results.insert(0, {"type": "text", "text": "<reminder>Update your todos.</reminder>"})

        # 将工具结果添加到对话历史
        messages.append({"role": "user", "content": results})


# =============================================================================
# 主程序入口
#
# REPL (Read-Eval-Print Loop) 模式：
# - 读取用户输入
# - 调用 agent_loop 处理
# - 打印最终响应
# =============================================================================
if __name__ == "__main__":
    history = []  # 对话历史

    while True:
        try:
            # 读取用户输入（青色提示符）
            query = input("\033[36ms03 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        # 退出条件：q, exit, 或空输入
        if query.strip().lower() in ("q", "exit", ""):
            break

        # 添加用户消息到历史
        history.append({"role": "user", "content": query})

        # 运行 Agent 循环
        agent_loop(history)

        # 打印最终响应
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()
