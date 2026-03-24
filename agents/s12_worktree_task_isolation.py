#!/usr/bin/env python3
# Harness: directory isolation -- parallel execution lanes that never collide.
"""
s12_worktree_task_isolation.py - Worktree + Task Isolation

目录级别的隔离，用于并行任务执行。
任务是控制平面，worktrees 是执行平面。

    .tasks/task_12.json
      {
        "id": 12,
        "subject": "Implement auth refactor",
        "status": "in_progress",
        "worktree": "auth-refactor"
      }

    .worktrees/index.json
      {
        "worktrees": [
          {
            "name": "auth-refactor",
            "path": ".../.worktrees/auth-refactor",
            "branch": "wt/auth-refactor",
            "task_id": 12,
            "status": "active"
          }
        ]
      }

关键洞察: "通过目录隔离，通过任务 ID 协调。"
"""

# =============================================================================
# 导入依赖
# =============================================================================
import json
import os
import re
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


# =============================================================================
# Git 仓库根检测
# =============================================================================
def detect_repo_root(cwd: Path) -> Path | None:
    """
    检测 Git 仓库根目录

    如果当前目录在 Git 仓库内，返回仓库根目录。
    否则返回 None。

    Args:
        cwd: 当前工作目录

    Returns:
        仓库根目录路径或 None
    """
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            return None
        root = Path(r.stdout.strip())
        return root if root.exists() else None
    except Exception:
        return None


# 检测仓库根目录，如果在仓库外则使用 WORKDIR
REPO_ROOT = detect_repo_root(WORKDIR) or WORKDIR


# =============================================================================
# 系统提示词
# =============================================================================
SYSTEM = (
    f"You are a coding agent at {WORKDIR}. "
    "Use task + worktree tools for multi-task work. "
    "For parallel or risky changes: create tasks, allocate worktree lanes, "
    "run commands in those lanes, then choose keep/remove for closeout. "
    "Use worktree_events when you need lifecycle visibility."
)


# =============================================================================
# EventBus: 追加写事件日志
#
# 职责：
# - 记录工作树和任务的生命周期事件
# - 提供可观测性（lifecycle visibility）
# - 追加写模式（append-only），保留完整历史
#
# 事件类型：
# - worktree.create.before/after
# - worktree.remove.before/after
# - worktree.keep
# - worktree.create.failed
# - worktree.remove.failed
# - task.completed
# =============================================================================
class EventBus:
    def __init__(self, event_log_path: Path):
        """
        初始化事件总线

        Args:
            event_log_path: 事件日志文件路径
        """
        self.path = event_log_path
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # 确保日志文件存在
        if not self.path.exists():
            self.path.write_text("")

    def emit(
        self,
        event: str,
        task: dict | None = None,
        worktree: dict | None = None,
        error: str | None = None,
    ):
        """
        发出一个事件到日志

        Args:
            event: 事件名称
            task: 关联的任务信息（可选）
            worktree: 关联的工作树信息（可选）
            error: 错误信息（可选）
        """
        payload = {
            "event": event,
            "ts": time.time(),
            "task": task or {},
            "worktree": worktree or {},
        }
        if error:
            payload["error"] = error

        # 追加写模式，使用 UTF-8 编码
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def list_recent(self, limit: int = 20) -> str:
        """
        列出最近的事件

        Args:
            limit: 要返回的事件数量（默认 20）

        Returns:
            最近事件的 JSON 字符串
        """
        n = max(1, min(int(limit or 20), 200))
        lines = self.path.read_text(encoding="utf-8").splitlines()
        recent = lines[-n:]

        items = []
        for line in recent:
            try:
                items.append(json.loads(line))
            except Exception:
                items.append({"event": "parse_error", "raw": line})

        return json.dumps(items, indent=2)


# =============================================================================
# TaskManager: 任务管理器（带工作树绑定）
#
# 职责：
# - 持久化任务到 .tasks/task_*.json
# - 管理任务状态（pending/in_progress/completed）
# - 绑定任务到工作树（worktree 字段）
# - 支持任务所有者（owner）分配
# =============================================================================
class TaskManager:
    def __init__(self, tasks_dir: Path):
        """
        初始化任务管理器

        Args:
            tasks_dir: 任务文件存储目录
        """
        self.dir = tasks_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._next_id = self._max_id() + 1

    def _max_id(self) -> int:
        """获取当前最大的任务 ID"""
        ids = []
        for f in self.dir.glob("task_*.json"):
            try:
                ids.append(int(f.stem.split("_")[1]))
            except Exception:
                pass
        return max(ids) if ids else 0

    def _path(self, task_id: int) -> Path:
        """获取任务文件路径"""
        return self.dir / f"task_{task_id}.json"

    def _load(self, task_id: int) -> dict:
        """从文件加载任务"""
        path = self._path(task_id)
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text())

    def _save(self, task: dict):
        """保存任务到文件"""
        self._path(task["id"]).write_text(json.dumps(task, indent=2))

    def create(self, subject: str, description: str = "") -> str:
        """
        创建新任务

        Args:
            subject: 任务标题
            description: 任务详细描述

        Returns:
            新任务的 JSON 字符串
        """
        task = {
            "id": self._next_id,
            "subject": subject,
            "description": description,
            "status": "pending",
            "owner": "",
            "worktree": "",
            "blockedBy": [],
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        self._save(task)
        self._next_id += 1
        return json.dumps(task, indent=2)

    def get(self, task_id: int) -> str:
        """获取任务详情"""
        return json.dumps(self._load(task_id), indent=2)

    def exists(self, task_id: int) -> bool:
        """检查任务是否存在"""
        return self._path(task_id).exists()

    def update(self, task_id: int, status: str = None, owner: str = None) -> str:
        """
        更新任务

        Args:
            task_id: 任务 ID
            status: 新状态（pending/in_progress/completed）
            owner: 任务所有者

        Returns:
            更新后的任务 JSON 字符串
        """
        task = self._load(task_id)

        if status:
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Invalid status: {status}")
            task["status"] = status

        if owner is not None:
            task["owner"] = owner

        task["updated_at"] = time.time()
        self._save(task)
        return json.dumps(task, indent=2)

    def bind_worktree(self, task_id: int, worktree: str, owner: str = "") -> str:
        """
        绑定任务到工作树

        Args:
            task_id: 任务 ID
            worktree: 工作树名称
            owner: 可选的任务所有者

        Returns:
            更新后的任务 JSON 字符串
        """
        task = self._load(task_id)
        task["worktree"] = worktree

        if owner:
            task["owner"] = owner

        # 绑定工作树时，任务状态自动变为 in_progress
        if task["status"] == "pending":
            task["status"] = "in_progress"

        task["updated_at"] = time.time()
        self._save(task)
        return json.dumps(task, indent=2)

    def unbind_worktree(self, task_id: int) -> str:
        """
        解除任务与工作树的绑定

        Args:
            task_id: 任务 ID

        Returns:
            更新后的任务 JSON 字符串
        """
        task = self._load(task_id)
        task["worktree"] = ""
        task["updated_at"] = time.time()
        self._save(task)
        return json.dumps(task, indent=2)

    def list_all(self) -> str:
        """
        列出所有任务

        显示格式：
        [ ] #1: Task A
        [>] #2: Task B wt=auth-refactor
        [x] #3: Task C owner=alice
        """
        tasks = []
        for f in sorted(self.dir.glob("task_*.json")):
            tasks.append(json.loads(f.read_text()))

        if not tasks:
            return "No tasks."

        lines = []
        for t in tasks:
            # 状态标记
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
            }.get(t["status"], "[?]")

            # 所有者和工作树信息
            owner = f" owner={t['owner']}" if t.get("owner") else ""
            wt = f" wt={t['worktree']}" if t.get("worktree") else ""

            lines.append(f"{marker} #{t['id']}: {t['subject']}{owner}{wt}")

        return "\n".join(lines)


# =============================================================================
# 初始化全局管理器
# =============================================================================
TASKS = TaskManager(REPO_ROOT / ".tasks")
EVENTS = EventBus(REPO_ROOT / ".worktrees" / "events.jsonl")


# =============================================================================
# WorktreeManager: 工作树管理器
#
# 职责：
# - 创建/列表/运行/删除 git worktree
# - 管理工作树索引（.worktrees/index.json）
# - 追踪工作树状态（active/removed/kept）
# - 提供生命周期事件
# - 运行命令在工作树目录中
#
# 基于 Git worktree：git worktree <name> [-b <branch>] <path>
# 索引文件：.worktrees/index.json 追踪所有工作树
# =============================================================================
class WorktreeManager:
    def __init__(self, repo_root: Path, tasks: TaskManager, events: EventBus):
        """
        初始化工作树管理器

        Args:
            repo_root: Git 仓库根目录
            tasks: 任务管理器引用
            events: 事件总线引用
        """
        self.repo_root = repo_root
        self.tasks = tasks
        self.events = events

        self.dir = repo_root / ".worktrees"
        self.dir.mkdir(parents=True, exist_ok=True)

        # 工作树索引文件
        self.index_path = self.dir / "index.json"

        # 初始化索引（如果不存在）
        if not self.index_path.exists():
            self.index_path.write_text(json.dumps({"worktrees": []}, indent=2))

        self.git_available = self._is_git_repo()

    def _is_git_repo(self) -> bool:
        """检查是否在 Git 仓库中"""
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _run_git(self, args: list[str]) -> str:
        """
        运行 Git 命令

        Args:
            args: Git 命令参数列表

        Returns:
            命令输出

        Raises:
            RuntimeError: 如果不是 Git 仓库或命令失败
        """
        if not self.git_available:
            raise RuntimeError("Not in a git repository. worktree tools require git.")

        r = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if r.returncode != 0:
            msg = (r.stdout + r.stderr).strip()
            raise RuntimeError(msg or f"git {' '.join(args)} failed")

        return (r.stdout + r.stderr).strip() or "(no output)"

    def _load_index(self) -> dict:
        """加载工作树索引"""
        return json.loads(self.index_path.read_text())

    def _save_index(self, data: dict):
        """保存工作树索引"""
        self.index_path.write_text(json.dumps(data, indent=2))

    def _find(self, name: str) -> dict | None:
        """在工作树索引中查找指定名称的工作树"""
        idx = self._load_index()
        for wt in idx.get("worktrees", []):
            if wt.get("name") == name:
                return wt
        return None

    def _validate_name(self, name: str):
        """
        验证工作树名称

        Git worktree 的命名规则：
        - 1-40 个字符
        - 只包含字母、数字、点、下划线、连字符
        - 不能以点开头

        Args:
            name: 工作树名称

        Raises:
            ValueError: 如果名称无效
        """
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", name or ""):
            raise ValueError(
                "Invalid worktree name. Use 1-40 chars: letters, numbers, ., _, -"
            )

    def create(self, name: str, task_id: int = None, base_ref: str = "HEAD") -> str:
        """
        创建新的工作树

        Args:
            name: 工作树名称（1-40 字符）
            task_id: 可选，绑定的任务 ID
            base_ref: 基准引用（默认 HEAD）

        Returns:
            新工作树的索引条目 JSON 字符串

        Raises:
            ValueError: 如果工作树已存在或任务不存在
        """
        self._validate_name(name)

        if self._find(name):
            raise ValueError(f"Worktree '{name}' already exists in index")

        if task_id is not None and not self.tasks.exists(task_id):
            raise ValueError(f"Task {task_id} not found")

        # 发出创建前事件
        path = self.dir / name
        branch = f"wt/{name}"
        self.events.emit(
            "worktree.create.before",
            task={"id": task_id} if task_id is not None else {},
            worktree={"name": name, "base_ref": base_ref},
        )

        try:
            # 创建工作树：git worktree add -b <branch> <path> <base_ref>
            self._run_git(["worktree", "add", "-b", branch, str(path), base_ref])

            # 更新索引
            entry = {
                "name": name,
                "path": str(path),
                "branch": branch,
                "task_id": task_id,
                "status": "active",
                "created_at": time.time(),
            }

            idx = self._load_index()
            idx["worktrees"].append(entry)
            self._save_index(idx)

            # 绑定任务到工作树
            if task_id is not None:
                self.tasks.bind_worktree(task_id, name)

            # 发出创建后事件
            self.events.emit(
                "worktree.create.after",
                task={"id": task_id} if task_id is not None else {},
                worktree={
                    "name": name,
                    "path": str(path),
                    "branch": branch,
                    "status": "active",
                },
            )

            return json.dumps(entry, indent=2)

        except Exception as e:
            # 创建失败，发出失败事件
            self.events.emit(
                "worktree.create.failed",
                task={"id": task_id} if task_id is not None else {},
                worktree={"name": name, "base_ref": base_ref},
                error=str(e),
            )
            raise

    def list_all(self) -> str:
        """
        列出所有工作树

        输出格式：
        [active] auth-refactor -> path/to/... (wt/auth-refactor) task=12
        [unknown] other-worktree -> path/to/... (-)
        [kept] kept-worktree -> path/to/... task=12
        [removed] removed-worktree -> path/to/... task=12
        """
        idx = self._load_index()
        wts = idx.get("worktrees", [])

        if not wts:
            return "No worktrees in index."

        lines = []
        for wt in wts:
            suffix = f" task={wt['task_id']}" if wt.get("task_id") else ""
            lines.append(
                f"[{wt.get('status', 'unknown')}] {wt['name']} -> "
                f"{wt['path']} ({wt.get('branch', '-')}){suffix}"
            )

        return "\n".join(lines)

    def status(self, name: str) -> str:
        """
        查询工作树状态

        Args:
            name: 工作树名称

        Returns:
            Git 状态信息或 "Clean worktree"（如果工作树干净）
        """
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"

        path = Path(wt["path"])
        if not path.exists():
            return f"Error: Worktree path missing: {path}"

        # 运行 git status
        r = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=60,
        )

        text = (r.stdout + r.stderr).strip()
        return text or "Clean worktree"

    def run(self, name: str, command: str) -> str:
        """
        在工作树中运行命令

        Args:
            name: 工作树名称
            command: 要执行的命令

        Returns:
            命令输出

        Raises:
            subprocess.TimeoutExpired: 如果命令超时
        """
        # 危险命令过滤
        dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
        if any(d in command for d in dangerous):
            return "Error: Dangerous command blocked"

        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"

        path = Path(wt["path"])
        if not path.exists():
            return f"Error: Worktree path missing: {path}"

        try:
            r = subprocess.run(
                command,
                shell=True,
                cwd=path,
                capture_output=True,
                text=True,
                timeout=300,
            )
            out = (r.stdout + r.stderr).strip()
            return out[:50000] if out else "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: Timeout (300s)"

    def remove(self, name: str, force: bool = False, complete_task: bool = False) -> str:
        """
        删除工作树

        Args:
            name: 工作树名称
            force: 是否强制删除（--force）
            complete_task: 是否将关联任务标记为完成

        Returns:
            删除结果的 JSON 字符串

        Raises:
            Exception: 如果删除失败
        """
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"

        # 发出删除前事件
        self.events.emit(
            "worktree.remove.before",
            task={"id": wt.get("task_id")} if wt.get("task_id") is not None else {},
            worktree={"name": name, "path": wt.get("path")},
        )

        try:
            # 运行 git worktree remove [--force] <name>
            args = ["worktree", "remove"]
            if force:
                args.append("--force")
            args.append(wt["path"])
            self._run_git(args)

            # 如果指定了完成任务且有关联任务
            if complete_task and wt.get("task_id") is not None:
                task_id = wt["task_id"]

                # 加载任务前的状态
                before = json.loads(self.tasks.get(task_id))

                # 更新任务状态为 completed
                task_id_int = int(task_id)
                self.tasks.update(task_id_int, status="completed")
                self.tasks.unbind_worktree(task_id_int)

                # 发出任务完成事件
                self.events.emit(
                    "task.completed",
                    task={
                        "id": task_id,
                        "subject": before.get("subject", ""),
                        "status": "completed",
                    },
                    worktree={"name": name},
                )

            # 更新索引状态
            idx = self._load_index()
            for item in idx.get("worktrees", []):
                if item.get("name") == name:
                    item["status"] = "removed"
                    item["removed_at"] = time.time()
            self._save_index(idx)

            # 发出删除后事件
            self.events.emit(
                "worktree.remove.after",
                task={"id": wt.get("task_id")} if wt.get("task_id") is not None else {},
                worktree={"name": name, "path": wt.get("path"), "status": "removed"},
            )

            return f"Removed worktree '{name}'"

        except Exception as e:
            # 删除失败，发出失败事件
            self.events.emit(
                "worktree.remove.failed",
                task={"id": wt.get("task_id")} if wt.get("task_id") is not None else {},
                worktree={"name": name, "path": wt.get("path")},
                error=str(e),
            )
            raise

    def keep(self, name: str) -> str:
        """
        保留工作树（在生命周期中标记为 kept）

        Args:
            name: 工作树名称

        Returns:
            保留的工作树索引条目 JSON 字符串
        """
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"

        # 更新索引状态
        idx = self._load_index()
        kept = None
        for item in idx.get("worktrees", []):
            if item.get("name") == name:
                item["status"] = "kept"
                item["kept_at"] = time.time()
                kept = item

        self._save_index(idx)

        # 发出保留事件
        self.events.emit(
            "worktree.keep",
            task={"id": wt.get("task_id")} if wt.get("task_id") is not None else {},
            worktree={
                "name": name,
                "path": wt.get("path"),
                "status": "kept",
            },
        )

        return json.dumps(kept, indent=2) if kept else f"Error: Unknown worktree '{name}'"


# =============================================================================
# 初始化工作树管理器
# =============================================================================
WORKTREES = WorktreeManager(REPO_ROOT, TASKS, EVENTS)


# =============================================================================
# 基础工具实现函数（与之前会话相同）
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
            command,
            shell=True,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=120,
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
# 工具处理器映射（14 个工具类别）
#
# 工具类别：
# 1. 基础工具：bash, read_file, write_file, edit_file
# 2. 任务工具：task_create, task_list, task_get, task_update, task_bind_worktree
# 3. 工作树工具：worktree_create, worktree_list, worktree_status, worktree_run, worktree_remove, worktree_keep
# 4. 事件工具：worktree_events
# =============================================================================
TOOL_HANDLERS = {
    "bash":              lambda **kw: run_bash(kw["command"]),
    "read_file":         lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file":        lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":         lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "task_create":       lambda **kw: TASKS.create(kw["subject"], kw.get("description", "")),
    "task_list":         lambda **kw: TASKS.list_all(),
    "task_get":          lambda **kw: TASKS.get(kw["task_id"]),
    "task_update":       lambda **kw: TASKS.update(kw["task_id"], kw.get("status"), kw.get("owner")),
    "task_bind_worktree": lambda **kw: TASKS.bind_worktree(kw["task_id"], kw["worktree"], kw.get("owner", "")),
    "worktree_create":   lambda **kw: WORKTREES.create(kw["name"], kw.get("task_id"), kw.get("base_ref", "HEAD")),
    "worktree_list":     lambda **kw: WORKTREES.list_all(),
    "worktree_status":   lambda **kw: WORKTREES.status(kw["name"]),
    "worktree_run":       lambda **kw: WORKTREES.run(kw["name"], kw["command"]),
    "worktree_keep":       lambda **kw: WORKTREES.keep(kw["name"]),
    "worktree_remove":     lambda **kw: WORKTREES.remove(kw["name"], kw.get("force", False), kw.get("complete_task", False)),
    "worktree_events":   lambda **kw: EVENTS.list_recent(kw.get("limit", 20)),
}

# 工具定义（传递给 Claude API）
TOOLS = [
    # 基础工具：在当前工作区运行（阻塞）
    {
        "name": "bash",
        "description": "Run a shell command in the current workspace (blocking).",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read file contents.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace exact text in file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    # 任务工具：管理共享任务板
    {
        "name": "task_create",
        "description": "Create a new task on the shared task board.",
        "input_schema": {
            "type": "object",
            "properties": {"subject": {"type": "string"}, "description": {"type": "string"}},
            "required": ["subject"],
        },
    },
    {
        "name": "task_list",
        "description": "List all tasks with status, owner, and worktree binding.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "task_get",
        "description": "Get task details by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "task_update",
        "description": "Update task status or owner.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                "owner": {"type": "string"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "task_bind_worktree",
        "description": "Bind a task to a worktree name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "worktree": {"type": "string"},
                "owner": {"type": "string"},
            },
            "required": ["task_id", "worktree"],
        },
    },
    # 工作树工具：基于 Git worktree 的目录隔离
    {
        "name": "worktree_create",
        "description": "Create a git worktree and optionally bind it to a task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "task_id": {"type": "integer"},
                "base_ref": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "worktree_list",
        "description": "List worktrees tracked in .worktrees/index.json.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "worktree_status",
        "description": "Show git status for one worktree.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "worktree_run",
        "description": "Run a shell command in a named worktree directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "command": {"type": "string"},
            },
            "required": ["name", "command"],
        },
    },
    {
        "name": "worktree_remove",
        "description": "Remove a worktree and optionally mark its bound task completed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "force": {"type": "boolean"},
                "complete_task": {"type": "boolean"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "worktree_keep",
        "description": "Mark a worktree as kept in lifecycle state without removing it.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "worktree_events",
        "description": "List recent worktree/task lifecycle events from .worktrees/events.jsonl.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
]


# =============================================================================
# Agent 主循环
# =============================================================================
def agent_loop(messages: list):
    """
    Agent 主循环

    标准的工具调用循环，处理所有工具类别。
    """
    while True:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
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
                    "content": str(output),
                })

        messages.append({"role": "user", "content": results})


# =============================================================================
# 主程序入口（REPL 模式）
# =============================================================================
if __name__ == "__main__":
    print(f"Repo root for s12: {REPO_ROOT}")
    if not WORKTREES.git_available:
        print("Note: Not in a git repo. worktree_* tools will return errors.")

    history = []
    while True:
        try:
            query = input("\033[36ms12 >> \033[0m")
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
