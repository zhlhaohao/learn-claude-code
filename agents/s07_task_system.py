#!/usr/bin/env python3
# Harness: persistent tasks -- goals that outlive any single conversation.
"""
s07_task_system.py - Tasks（持久化任务系统）

任务以 JSON 文件形式持久化到 .tasks/ 目录，即使上下文压缩后也能存活。
每个任务都有依赖关系图（blockedBy/blocks）。

目录结构：
    .tasks/
      task_1.json  {"id":1, "subject":"...", "status":"completed", ...}
      task_2.json  {"id":2, "blockedBy":[1], "status":"pending", ...}
      task_3.json  {"id":3, "blockedBy":[2], "blocks":[], ...}

依赖解析：
    +----------+     +----------+     +----------+
    | task 1   | --> | task 2   | --> | task 3   |
    | complete |     | blocked  |     | blocked  |
    +----------+     +----------+     +----------+
         |                ^
         +--- 完成 task 1 会将其从 task 2 的 blockedBy 中移除

关键洞察: "能存活于压缩之外的状态 —— 因为它在对话之外。"
"""

# =============================================================================
# 导入依赖
# =============================================================================
import json
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
TASKS_DIR = WORKDIR / ".tasks"  # 任务持久化目录

SYSTEM = f"You are a coding agent at {WORKDIR}. Use task tools to plan and track work."


# =============================================================================
# TaskManager: 任务管理器
#
# 职责：
# - CRUD 操作（创建、读取、更新、列出）
# - 依赖图管理（blockedBy/blocks 双向同步）
# - 任务完成时自动解除依赖阻塞
#
# 任务文件格式（task_{id}.json）：
# {
#   "id": 1,
#   "subject": "任务标题",
#   "description": "详细描述",
#   "status": "pending" | "in_progress" | "completed",
#   "blockedBy": [2, 3],  // 被哪些任务阻塞
#   "blocks": [4, 5],     // 阻塞了哪些任务
#   "owner": ""           // 所有者（预留字段）
# }
# =============================================================================
class TaskManager:
    def __init__(self, tasks_dir: Path):
        """
        初始化任务管理器

        Args:
            tasks_dir: 任务文件存储目录
        """
        self.dir = tasks_dir
        self.dir.mkdir(exist_ok=True)
        # 计算下一个可用的任务 ID（基于现有最大 ID + 1）
        self._next_id = self._max_id() + 1

    def _max_id(self) -> int:
        """获取当前最大的任务 ID"""
        ids = [int(f.stem.split("_")[1]) for f in self.dir.glob("task_*.json")]
        return max(ids) if ids else 0

    def _load(self, task_id: int) -> dict:
        """
        从文件加载任务

        Args:
            task_id: 任务 ID

        Returns:
            任务字典

        Raises:
            ValueError: 任务不存在
        """
        path = self.dir / f"task_{task_id}.json"
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text())

    def _save(self, task: dict):
        """
        保存任务到文件

        Args:
            task: 任务字典
        """
        path = self.dir / f"task_{task['id']}.json"
        path.write_text(json.dumps(task, indent=2))

    def create(self, subject: str, description: str = "") -> str:
        """
        创建新任务

        Args:
            subject: 任务标题
            description: 任务详细描述

        Returns:
            JSON 格式的任务信息
        """
        task = {
            "id": self._next_id,
            "subject": subject,
            "description": description,
            "status": "pending",
            "blockedBy": [],  # 被哪些任务阻塞
            "blocks": [],     # 阻塞了哪些任务
            "owner": "",
        }
        self._save(task)
        self._next_id += 1
        return json.dumps(task, indent=2)

    def get(self, task_id: int) -> str:
        """
        获取任务详情

        Args:
            task_id: 任务 ID

        Returns:
            JSON 格式的任务详情
        """
        return json.dumps(self._load(task_id), indent=2)

    def update(self, task_id: int, status: str = None,
               add_blocked_by: list = None, add_blocks: list = None) -> str:
        """
        更新任务

        Args:
            task_id: 任务 ID
            status: 新状态（pending/in_progress/completed）
            add_blocked_by: 添加阻塞依赖（这些任务完成后才能开始本任务）
            add_blocks: 添加被阻塞依赖（本任务完成前这些任务不能开始）

        Returns:
            JSON 格式的更新后任务信息
        """
        task = self._load(task_id)

        # 更新状态
        if status:
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Invalid status: {status}")
            task["status"] = status
            # 当任务完成时，自动从其他任务的 blockedBy 中移除
            if status == "completed":
                self._clear_dependency(task_id)

        # 添加阻塞依赖（本任务被哪些任务阻塞）
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))

        # 添加被阻塞依赖（本任务阻塞哪些任务）
        if add_blocks:
            task["blocks"] = list(set(task["blocks"] + add_blocks))
            # 双向同步：更新被阻塞任务的 blockedBy 列表
            for blocked_id in add_blocks:
                try:
                    blocked = self._load(blocked_id)
                    if task_id not in blocked["blockedBy"]:
                        blocked["blockedBy"].append(task_id)
                        self._save(blocked)
                except ValueError:
                    pass  # 忽略不存在的任务

        self._save(task)
        return json.dumps(task, indent=2)

    def _clear_dependency(self, completed_id: int):
        """
        清除已完成任务的依赖关系

        当任务完成时，从所有其他任务的 blockedBy 列表中移除该任务 ID。
        这样被阻塞的任务就可以开始执行了。

        Args:
            completed_id: 已完成的任务 ID
        """
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text())
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                self._save(task)

    def list_all(self) -> str:
        """
        列出所有任务

        Returns:
            格式化的任务列表字符串
        """
        tasks = []
        for f in sorted(self.dir.glob("task_*.json")):
            tasks.append(json.loads(f.read_text()))

        if not tasks:
            return "No tasks."

        lines = []
        for t in tasks:
            # 状态标记
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(t["status"], "[?]")
            # 显示阻塞信息
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            lines.append(f"{marker} #{t['id']}: {t['subject']}{blocked}")

        return "\n".join(lines)


# =============================================================================
# 初始化任务管理器
# =============================================================================
TASKS = TaskManager(TASKS_DIR)


# =============================================================================
# 基础工具实现函数
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
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# =============================================================================
# 工具处理器映射
#
# 包含：
# - 基础工具（bash, read_file, write_file, edit_file）
# - 任务工具（task_create, task_update, task_list, task_get）
# =============================================================================
TOOL_HANDLERS = {
    "bash":        lambda **kw: run_bash(kw["command"]),
    "read_file":   lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file":  lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":   lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    # 任务工具
    "task_create": lambda **kw: TASKS.create(kw["subject"], kw.get("description", "")),
    "task_update": lambda **kw: TASKS.update(kw["task_id"], kw.get("status"), kw.get("addBlockedBy"), kw.get("addBlocks")),
    "task_list":   lambda **kw: TASKS.list_all(),
    "task_get":    lambda **kw: TASKS.get(kw["task_id"]),
}

TOOLS = [
    # 基础工具
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},

    # 任务工具
    {"name": "task_create", "description": "Create a new task.",
     "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}}, "required": ["subject"]}},
    {"name": "task_update", "description": "Update a task's status or dependencies.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}, "addBlockedBy": {"type": "array", "items": {"type": "integer"}}, "addBlocks": {"type": "array", "items": {"type": "integer"}}}, "required": ["task_id"]}},
    {"name": "task_list", "description": "List all tasks with status summary.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "task_get", "description": "Get full details of a task by ID.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
]


# =============================================================================
# Agent 主循环
# =============================================================================
def agent_loop(messages: list):
    """
    Agent 主循环

    标准的工具调用循环，处理任务工具和基础工具。
    """
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return

        results = []
        for block in response.content:
            if block.type == "tool_use":
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


# =============================================================================
# 主程序入口（REPL 模式）
# =============================================================================
if __name__ == "__main__":
    history = []

    while True:
        try:
            query = input("\033[36ms07 >> \033[0m")
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
