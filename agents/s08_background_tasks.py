#!/usr/bin/env python3
# Harness: background execution -- the model thinks while the harness waits.
"""
s08_background_tasks.py - Background Tasks（后台任务）

在后台线程中运行命令。在每次 LLM 调用前，会清空通知队列来传递结果。

架构图：
    Main thread                Background thread
    +-----------------+        +-----------------+
    | agent loop      |        | task executes   |
    | ...             |        | ...             |
    | [LLM call] <---+------- | enqueue(result) |
    |  ^drain queue   |        +-----------------+
    +-----------------+

    时间线：
    Agent ----[spawn A]----[spawn B]----[other work]----
                 |              |
                 v              v
              [A runs]      [B runs]        (并行)
                 |              |
                 +-- notification queue --> [results injected]

关键洞察: "发射后不管 —— 命令运行时 Agent 不会阻塞。"
"""

# =============================================================================
# 导入依赖
# =============================================================================
import os
import subprocess
import threading
import uuid
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

SYSTEM = f"You are a coding agent at {WORKDIR}. Use background_run for long-running commands."


# =============================================================================
# BackgroundManager: 后台任务管理器
#
# 职责：
# - 在后台线程中执行长时间运行的命令
# - 管理任务状态（running/completed/timeout/error）
# - 维护完成通知队列，供主线程在 LLM 调用前获取
#
# 核心机制：
# - run(): 立即返回 task_id，命令在后台执行
# - _execute(): 线程目标函数，执行命令并将结果放入通知队列
# - check(): 查询任务状态
# - drain_notifications(): 获取并清空所有待处理的通知
# =============================================================================
class BackgroundManager:
    def __init__(self):
        """初始化后台任务管理器"""
        self.tasks = {}  # task_id -> {status, result, command}
        self._notification_queue = []  # 已完成任务的结果通知
        self._lock = threading.Lock()  # 保护通知队列的线程锁

    def run(self, command: str) -> str:
        """
        启动后台任务

        立即返回 task_id，命令在后台线程中执行。
        Agent 可以继续其他工作，不会被阻塞。

        Args:
            command: 要执行的 shell 命令

        Returns:
            包含 task_id 的启动确认消息
        """
        # 生成短 UUID 作为任务 ID
        task_id = str(uuid.uuid4())[:8]
        self.tasks[task_id] = {
            "status": "running",
            "result": None,
            "command": command
        }

        # 创建并启动后台线程
        thread = threading.Thread(
            target=self._execute,
            args=(task_id, command),
            daemon=True  # 守护线程，主程序退出时自动结束
        )
        thread.start()

        return f"Background task {task_id} started: {command[:80]}"

    def _execute(self, task_id: str, command: str):
        """
        后台线程的目标函数：执行命令并捕获输出

        Args:
            task_id: 任务 ID
            command: 要执行的命令

        执行完成后，将结果放入通知队列，供主线程获取。
        """
        try:
            r = subprocess.run(
                command, shell=True, cwd=WORKDIR,
                capture_output=True, text=True, timeout=300  # 5 分钟超时
            )
            output = (r.stdout + r.stderr).strip()[:50000]
            status = "completed"
        except subprocess.TimeoutExpired:
            output = "Error: Timeout (300s)"
            status = "timeout"
        except Exception as e:
            output = f"Error: {e}"
            status = "error"

        # 更新任务状态
        self.tasks[task_id]["status"] = status
        self.tasks[task_id]["result"] = output or "(no output)"

        # 将完成通知放入队列（线程安全）
        with self._lock:
            self._notification_queue.append({
                "task_id": task_id,
                "status": status,
                "command": command[:80],
                "result": (output or "(no output)")[:500],  # 通知中截断结果
            })

    def check(self, task_id: str = None) -> str:
        """
        查询后台任务状态

        Args:
            task_id: 可选，指定要查询的任务 ID
                     如果省略，则列出所有任务

        Returns:
            任务状态信息或任务列表
        """
        if task_id:
            # 查询特定任务
            t = self.tasks.get(task_id)
            if not t:
                return f"Error: Unknown task {task_id}"
            return f"[{t['status']}] {t['command'][:60]}\n{t.get('result') or '(running)'}"

        # 列出所有任务
        lines = []
        for tid, t in self.tasks.items():
            lines.append(f"{tid}: [{t['status']}] {t['command'][:60]}")
        return "\n".join(lines) if lines else "No background tasks."

    def drain_notifications(self) -> list:
        """
        获取并清空所有待处理的完成通知

        这个方法在每次 LLM 调用前被调用，将后台任务的结果
        注入到对话上下文中。

        Returns:
            通知列表，每个通知包含 task_id, status, command, result
        """
        with self._lock:
            notifs = list(self._notification_queue)
            self._notification_queue.clear()
        return notifs


# =============================================================================
# 初始化后台任务管理器
# =============================================================================
BG = BackgroundManager()


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
    """执行 shell 命令（阻塞式），包含危险命令过滤"""
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
# =============================================================================
TOOL_HANDLERS = {
    "bash":             lambda **kw: run_bash(kw["command"]),
    "read_file":        lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file":       lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":        lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    # 后台任务工具
    "background_run":   lambda **kw: BG.run(kw["command"]),
    "check_background": lambda **kw: BG.check(kw.get("task_id")),
}

TOOLS = [
    # 基础工具
    {"name": "bash", "description": "Run a shell command (blocking).",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},

    # 后台任务工具
    {"name": "background_run", "description": "Run command in background thread. Returns task_id immediately.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "check_background", "description": "Check background task status. Omit task_id to list all.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}}},
]


# =============================================================================
# Agent 主循环
#
# 核心机制：
# - 每次循环开始时，调用 drain_notifications() 获取后台任务结果
# - 将结果注入到对话上下文中
# - 继续正常的工具调用流程
# =============================================================================
def agent_loop(messages: list):
    """
    Agent 主循环，集成后台任务通知

    在每次 LLM 调用前：
    1. 清空后台任务通知队列
    2. 将完成的通知注入到对话上下文
    """
    while True:
        # 在 LLM 调用前，清空后台通知并注入到消息中
        notifs = BG.drain_notifications()
        if notifs and messages:
            notif_text = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs
            )
            # 以系统消息的形式注入后台结果
            messages.append({
                "role": "user",
                "content": f"<background-results>\n{notif_text}\n</background-results>"
            })
            messages.append({
                "role": "assistant",
                "content": "Noted background results."
            })

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
            query = input("\033[36ms08 >> \033[0m")
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
