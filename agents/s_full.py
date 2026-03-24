#!/usr/bin/env python3
# Harness: all mechanisms combined -- the complete cockpit for the model.
"""
s_full.py - 完整参考 Agent

这是将 s01-s11 所有机制整合在一起的终极实现。
s12（任务感知的工作树隔离）作为独立主题教学。
这不是教学会话 —— 这是"把所有东西放在一起"的参考实现。

    +------------------------------------------------------------------+
    |                        FULL AGENT（完整代理）                     |
    |                                                                   |
    |  系统提示词（s05 技能加载，任务优先 + 可选 todo 提醒）            |
    |                                                                   |
    |  每次 LLM 调用前：                                                |
    |  +--------------------+  +------------------+  +--------------+  |
    |  | Microcompact (s06) |  | Drain bg (s08)   |  | Check inbox  |  |
    |  | 微压缩             |  | 耗尽后台通知     |  | 检查收件箱   |  |
    |  | Auto-compact (s06) |  |                  |  | (s09)        |  |
    |  | 自动压缩           |  |                  |  |              |  |
    |  +--------------------+  +------------------+  +--------------+  |
    |                                                                   |
    |  工具分发（s02 模式）：                                           |
    |  +--------+----------+----------+---------+-----------+          |
    |  | bash   | read     | write    | edit    | TodoWrite |          |
    |  | task   | load_sk  | compress | bg_run  | bg_check  |          |
    |  | t_crt  | t_get    | t_upd    | t_list  | spawn_tm  |          |
    |  | list_tm| send_msg | rd_inbox | bcast   | shutdown  |          |
    |  | plan   | idle     | claim    |         |           |          |
    |  +--------+----------+----------+---------+-----------+          |
    |                                                                   |
    |  Subagent (s04):  spawn -> work -> return summary                 |
    |  子代理：启动 -> 工作 -> 返回摘要                                  |
    |                                                                   |
    |  Teammate (s09):  spawn -> work -> idle -> auto-claim (s11)      |
    |  队友：启动 -> 工作 -> 空闲 -> 自动认领任务                         |
    |                                                                   |
    |  Shutdown (s10):  request_id handshake                            |
    |  关闭协议：request_id 握手机制                                     |
    |                                                                   |
    |  Plan gate (s10): submit -> approve/reject                        |
    |  计划门控：提交 -> 批准/拒绝                                       |
    +------------------------------------------------------------------+

    REPL 命令：
    - /compact  手动压缩对话上下文
    - /tasks    列出所有任务
    - /team     列出所有队友状态
    - /inbox    读取 lead 的收件箱

整合的功能模块：
    s01 - Agent Loop（代理循环）：核心的 while 循环
    s02 - Tool Use（工具使用）：工具定义和分发
    s03 - TodoWrite（待办写入）：任务进度追踪
    s04 - Subagent（子代理）：临时委托代理
    s05 - Skills（技能）：从文件加载专业知识
    s06 - Context Compact（上下文压缩）：微压缩 + 自动压缩
    s07 - File Tasks（文件任务）：持久化任务系统
    s08 - Background Tasks（后台任务）：异步命令执行
    s09 - Agent Teams（代理团队）：持久化队友 + 消息总线
    s10 - Team Protocols（团队协议）：关闭握手 + 计划审批
    s11 - Autonomous Agents（自主代理）：空闲时自动认领任务
"""

# =============================================================================
# 导入依赖
# =============================================================================
import json
import logging
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from queue import Queue

from anthropic import Anthropic
from zhipuai import ZhipuAI
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量，override=True 表示覆盖已存在的环境变量
load_dotenv(override=True)

# =============================================================================
# 日志配置
#
# 配置调试日志，用于记录 LLM 调用和工具执行的详细信息。
# 日志文件按日期命名，存放在 agents/logs/ 目录下。
# =============================================================================
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"debug_{datetime.now().strftime('%Y%m%d')}.log"


class SafeFileHandler(logging.FileHandler):
    """
    安全的文件日志处理器

    继承自 logging.FileHandler，添加了编码错误处理。
    当遇到无法编码的字符时，自动替换为 UTF-8 安全字符。
    """
    def emit(self, record):
        try:
            super().emit(record)
        except (UnicodeDecodeError, UnicodeEncodeError):
            # 处理编码错误，移除问题字符
            record.msg = record.msg.encode('utf-8', errors='replace').decode('utf-8')
            super().emit(record)


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        SafeFileHandler(LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)
logger.info("=" * 50 + " Session Started " + "=" * 50)

# =============================================================================
# 全局配置
#
# 初始化 API 客户端和各种目录路径。如果配置了自定义 API 端点，
# 移除默认的 auth token 以避免冲突。
# =============================================================================
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()  # 当前工作目录，用于限制文件操作范围
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))  # Anthropic API 客户端
zhipu_client = ZhipuAI(api_key=os.getenv("ANTHROPIC_API_KEY"))  # 智谱 AI 客户端（用于 web_search）
MODEL = os.environ["MODEL_ID"]  # 使用的模型 ID

# 目录配置
TEAM_DIR = WORKDIR / ".team"  # 团队配置目录
INBOX_DIR = TEAM_DIR / "inbox"  # 消息收件箱目录
TASKS_DIR = WORKDIR / ".tasks"  # 持久化任务目录
SKILLS_DIR = WORKDIR / "skills"  # 技能文件目录
TRANSCRIPT_DIR = WORKDIR / ".transcripts"  # 压缩后的对话记录目录

# 阈值和超时配置
TOKEN_THRESHOLD = 100000  # 触发自动压缩的 token 阈值
POLL_INTERVAL = 5  # 空闲轮询间隔（秒）
IDLE_TIMEOUT = 60  # 空闲超时时间（秒）

# 有效的消息类型集合（s09/s10）
VALID_MSG_TYPES = {
    "message",               # 普通消息
    "broadcast",             # 广播消息
    "shutdown_request",      # 关闭请求
    "shutdown_response",     # 关闭响应
    "plan_approval_response" # 计划审批响应
}


# =============================================================================
# SECTION: 基础工具函数 (s02)
#
# 提供文件操作和命令执行的基础工具。所有路径操作都经过安全检查，
# 确保不会逃逸工作目录。命令执行有危险命令过滤和超时保护。
# =============================================================================

def safe_path(p: str) -> Path:
    """
    安全路径解析

    将相对路径解析为绝对路径，并检查是否在工作目录内。
    防止路径遍历攻击（如 ../../../etc/passwd）。

    Args:
        p: 相对路径字符串

    Returns:
        解析后的绝对路径

    Raises:
        ValueError: 如果路径逃逸工作目录
    """
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    """
    执行 shell 命令

    在沙箱环境中执行命令，包含以下安全措施：
    - 危险命令过滤（rm -rf /, sudo, shutdown 等）
    - 超时保护（120 秒）
    - 输出截断（50000 字符）

    Args:
        command: 要执行的 shell 命令

    Returns:
        命令的标准输出和错误输出，或错误信息
    """
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int = None) -> str:
    """
    读取文件内容

    Args:
        path: 相对文件路径
        limit: 可选的行数限制

    Returns:
        文件内容（可能截断）
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
    写入文件内容

    自动创建不存在的父目录。

    Args:
        path: 相对文件路径
        content: 要写入的内容

    Returns:
        操作结果信息
    """
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    """
    编辑文件（替换文本）

    精确匹配并替换第一次出现的文本。

    Args:
        path: 相对文件路径
        old_text: 要替换的文本
        new_text: 新文本

    Returns:
        操作结果信息
    """
    try:
        fp = safe_path(path)
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def run_web_search(query: str) -> str:
    """
    使用智谱 AI 的内置 web_search 工具搜索网络信息

    通过智谱 GLM-4-Flash 模型的 web_search 工具获取实时网络信息。

    Args:
        query: 搜索查询字符串

    Returns:
        搜索结果内容
    """
    try:
        response = zhipu_client.chat.completions.create(
            model="glm-4-flash",
            messages=[{"role": "user", "content": query}],
            tools=[
                {
                    "type": "web_search",
                    "web_search": {
                        "enable": "True",
                        "search_engine": "search_pro",
                        "search_result": "True",
                        "count": "5",
                        "search_recency_filter": "noLimit",
                        "content_size": "high",
                    },
                }
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {e}"


def run_weather(cities: list, date: str) -> str:
    """
    查询多个城市天气

    使用智谱 AI 的 web_search 工具查询天气，返回结构化的 JSON 格式。

    Args:
        cities: 城市名列表
        date: 日期（如 '今天', '明天', '2024-03-20'）

    Returns:
        JSON 数组格式的天气信息
    """
    city_str = "、".join(cities) if isinstance(cities, list) else cities
    query = f"{city_str}{date}天气"

    try:
        response = zhipu_client.chat.completions.create(
            model="glm-4-flash",
            messages=[
                {
                    "role": "user",
                    "content": f"""搜索"{query}"，然后仅返回以下JSON数组格式，不要任何其他文字：
[{{"city": "城市名", "date": "日期", "weather": "天气状况", "temp_high": "最高温度", "temp_low": "最低温度", "humidity": "湿度", "wind": "风向风力"}}]"""
                }
            ],
            tools=[
                {
                    "type": "web_search",
                    "web_search": {
                        "enable": "True",
                        "search_engine": "search_pro",
                        "search_result": "True",
                        "count": "5",
                        "search_recency_filter": "oneDay",
                        "content_size": "high",
                    },
                }
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        return f'{{"error": "{e}"}}'


# =============================================================================
# SECTION: TodoManager (s03)
#
# 结构化的任务状态管理器，用于追踪 Agent 的工作进度。
#
# 职责：
# - 管理待办事项列表（最多 20 项）
# - 验证任务状态（pending/in_progress/completed）
# - 确保同一时间只有一个任务处于 in_progress 状态
# - 渲染可读的任务列表输出
#
# 关键洞察："Agent 可以追踪自己的进度 —— 而且我可以看到它。"
# =============================================================================

class TodoManager:
    """待办事项管理器"""

    def __init__(self):
        """初始化空的待办事项列表"""
        self.items = []

    def update(self, items: list) -> str:
        """
        更新待办事项列表

        验证并更新整个待办列表，确保数据一致性。

        Args:
            items: 待办事项列表，每项包含：
                - content: 任务内容（必填）
                - status: 状态 pending/in_progress/completed（必填）
                - activeForm: 进行中时的进行时描述（必填）

        Returns:
            渲染后的任务列表字符串

        Raises:
            ValueError: 如果验证失败（缺少字段、状态无效、多个 in_progress 等）
        """
        validated, ip = [], 0
        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            af = str(item.get("activeForm", "")).strip()
            if not content: raise ValueError(f"Item {i}: content required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {i}: invalid status '{status}'")
            if not af: raise ValueError(f"Item {i}: activeForm required")
            if status == "in_progress": ip += 1
            validated.append({"content": content, "status": status, "activeForm": af})
        if len(validated) > 20: raise ValueError("Max 20 todos")
        if ip > 1: raise ValueError("Only one in_progress allowed")
        self.items = validated
        return self.render()

    def render(self) -> str:
        """
        渲染待办列表为可读字符串

        格式示例：
            [x] 已完成的任务
            [>] 进行中的任务 <- doing
            [ ] 待处理的任务

            (1/3 completed)

        Returns:
            格式化的任务列表字符串
        """
        if not self.items: return "No todos."
        lines = []
        for item in self.items:
            m = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}.get(item["status"], "[?]")
            suffix = f" <- {item['activeForm']}" if item["status"] == "in_progress" else ""
            lines.append(f"{m} {item['content']}{suffix}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)

    def has_open_items(self) -> bool:
        """
        检查是否有未完成的任务

        用于判断是否需要发送提醒（s03 的 nag 机制）。
        """
        return any(item.get("status") != "completed" for item in self.items)


# =============================================================================
# SECTION: Subagent 子代理 (s04)
#
# 临时委托代理，用于隔离的探索或工作。
#
# 生命周期：spawn -> execute -> return summary -> destroyed
#
# 与 Teammate (s09) 的区别：
# - Subagent: 临时的，任务完成后销毁，返回摘要
# - Teammate: 持久化的，可以空闲后继续工作，直到显式关闭
#
# agent_type 参数：
# - "Explore": 只读工具（bash, read_file），用于探索代码库
# - "general-purpose": 读写工具，用于修改文件
# =============================================================================

def run_subagent(prompt: str, agent_type: str = "Explore") -> str:
    """
    启动子代理执行隔离任务

    创建一个临时的代理循环，执行完任务后返回摘要。

    Args:
        prompt: 任务提示词
        agent_type: 代理类型
            - "Explore": 只读探索（只能用 bash 和 read_file）
            - "general-purpose": 通用代理（可以写文件）

    Returns:
        任务执行摘要
    """
    # 根据代理类型配置可用工具
    sub_tools = [
        {"name": "bash", "description": "Run command.",
         "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
        {"name": "read_file", "description": "Read file.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    ]
    # 非探索类型代理可以写文件
    if agent_type != "Explore":
        sub_tools += [
            {"name": "write_file", "description": "Write file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "edit_file", "description": "Edit file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
        ]

    # 工具处理器映射
    sub_handlers = {
        "bash": lambda **kw: run_bash(kw["command"]),
        "read_file": lambda **kw: run_read(kw["path"]),
        "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
        "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    }

    # 子代理消息循环
    sub_msgs = [{"role": "user", "content": prompt}]
    resp = None
    for _ in range(30):  # 最多 30 轮
        resp = client.messages.create(model=MODEL, messages=sub_msgs, tools=sub_tools, max_tokens=8000)
        sub_msgs.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            break
        # 执行工具调用
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                h = sub_handlers.get(b.name, lambda **kw: "Unknown tool")
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(h(**b.input))[:50000]})
        sub_msgs.append({"role": "user", "content": results})

    # 返回摘要
    if resp:
        return "".join(b.text for b in resp.content if hasattr(b, "text")) or "(no summary)"
    return "(subagent failed)"


# =============================================================================
# SECTION: SkillLoader 技能加载器 (s05)
#
# 从文件系统加载专业知识技能。技能是 Markdown 文件，包含：
# - YAML front matter（元数据）
# - Markdown 正文（指令内容）
#
# 文件格式示例 (skills/my_skill/SKILL.md):
#     ---
#     name: my_skill
#     description: 技能描述
#     ---
#     # 技能指令
#     详细的使用说明...
#
# 关键洞察："模型可以在运行时学习新能力。"
# =============================================================================

class SkillLoader:
    """技能加载器，从文件系统加载专业技能"""

    def __init__(self, skills_dir: Path):
        """
        初始化并扫描技能目录

        扫描 skills_dir 下所有的 SKILL.md 文件，解析元数据和内容。

        Args:
            skills_dir: 技能文件根目录
        """
        self.skills = {}
        if skills_dir.exists():
            for f in sorted(skills_dir.rglob("SKILL.md")):
                text = f.read_text()
                # 解析 YAML front matter
                match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
                meta, body = {}, text
                if match:
                    for line in match.group(1).strip().splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            meta[k.strip()] = v.strip()
                    body = match.group(2).strip()
                name = meta.get("name", f.parent.name)
                self.skills[name] = {"meta": meta, "body": body}

    def descriptions(self) -> str:
        """
        获取所有技能的描述列表

        Returns:
            格式化的技能描述字符串
        """
        if not self.skills: return "(no skills)"
        return "\n".join(f"  - {n}: {s['meta'].get('description', '-')}" for n, s in self.skills.items())

    def load(self, name: str) -> str:
        """
        加载指定技能的完整内容

        Args:
            name: 技能名称

        Returns:
            XML 格式的技能内容，用于注入到对话中
        """
        s = self.skills.get(name)
        if not s: return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        return f"<skill name=\"{name}\">\n{s['body']}\n</skill>"


# =============================================================================
# SECTION: Context Compression 上下文压缩 (s06)
#
# 管理对话上下文的压缩，包括两种策略：
#
# 1. Microcompact（微压缩）：
#    - 在每轮循环开始时自动执行
#    - 清理旧的 tool_result 内容，只保留最近 3 个
#    - 被清理的内容替换为 "[cleared]"
#
# 2. Auto-compact（自动压缩）：
#    - 当 token 估计值超过阈值时触发
#    - 使用 LLM 生成对话摘要
#    - 保存原始对话到 .transcripts/ 目录
#    - 用摘要替换整个对话历史
#
# 关键洞察："可以无限继续 —— 只需要偶尔压缩上下文。"
# =============================================================================

def estimate_tokens(messages: list) -> int:
    """
    估算消息列表的 token 数量

    使用简单的字符数除以 4 的启发式方法。
    实际 token 数可能有所不同，但用于阈值判断足够准确。

    Args:
        messages: 消息列表

    Returns:
        估算的 token 数量
    """
    return len(json.dumps(messages, default=str)) // 4


def microcompact(messages: list):
    """
    微压缩：清理旧的 tool_result

    在每轮循环开始时调用，将超过 3 个的旧 tool_result 内容清空。
    这是原地修改（in-place），不返回新列表。

    Args:
        messages: 消息列表（会被修改）
    """
    indices = []
    for i, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part in msg["content"]:
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    indices.append(part)
    if len(indices) <= 3:
        return
    # 清理除了最近 3 个之外的所有 tool_result
    for part in indices[:-3]:
        if isinstance(part.get("content"), str) and len(part["content"]) > 100:
            part["content"] = "[cleared]"


def auto_compact(messages: list) -> list:
    """
    自动压缩：使用 LLM 生成对话摘要

    当上下文超过阈值时，将整个对话发送给 LLM 生成摘要，
    然后用摘要替换对话历史。原始对话保存到 .transcripts/ 目录。

    Args:
        messages: 原始消息列表

    Returns:
        新的消息列表，包含摘要和确认消息
    """
    # 保存原始对话记录
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")

    # 生成摘要
    conv_text = json.dumps(messages, default=str)[:80000]
    resp = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content": f"Summarize for continuity:\n{conv_text}"}],
        max_tokens=2000,
    )
    summary = resp.content[0].text

    # 返回新的压缩后消息
    return [
        {"role": "user", "content": f"[Compressed. Transcript: {path}]\n{summary}"},
        {"role": "assistant", "content": "Understood. Continuing with summary context."},
    ]


# =============================================================================
# SECTION: TaskManager 文件任务管理 (s07)
#
# 持久化的任务管理系统，使用 JSON 文件存储。
#
# 任务文件格式 (.tasks/task_N.json):
#     {
#         "id": 1,
#         "subject": "任务标题",
#         "description": "任务描述",
#         "status": "pending",  // pending/in_progress/completed/deleted
#         "owner": "agent_name",  // 可选，任务认领者
#         "blockedBy": [2, 3],  // 可选，阻塞此任务的任务 ID
#         "blocks": [4]  // 可选，被此任务阻塞的任务 ID
#     }
#
# 与 TodoManager (s03) 的区别：
# - TodoManager: 内存中的短期待办列表
# - TaskManager: 文件持久化的长期任务系统，支持依赖关系
#
# 关键洞察："Agent 可以创建、追踪和完成长期任务。"
# =============================================================================

class TaskManager:
    """持久化任务管理器"""

    def __init__(self):
        """初始化任务目录"""
        TASKS_DIR.mkdir(exist_ok=True)

    def _next_id(self) -> int:
        """获取下一个可用的任务 ID"""
        ids = [int(f.stem.split("_")[1]) for f in TASKS_DIR.glob("task_*.json")]
        return max(ids, default=0) + 1

    def _load(self, tid: int) -> dict:
        """加载指定 ID 的任务"""
        p = TASKS_DIR / f"task_{tid}.json"
        if not p.exists(): raise ValueError(f"Task {tid} not found")
        return json.loads(p.read_text())

    def _save(self, task: dict):
        """保存任务到文件"""
        (TASKS_DIR / f"task_{task['id']}.json").write_text(json.dumps(task, indent=2))

    def create(self, subject: str, description: str = "") -> str:
        """
        创建新任务

        Args:
            subject: 任务标题
            description: 任务描述（可选）

        Returns:
            JSON 格式的任务信息
        """
        task = {"id": self._next_id(), "subject": subject, "description": description,
                "status": "pending", "owner": None, "blockedBy": [], "blocks": []}
        self._save(task)
        return json.dumps(task, indent=2)

    def get(self, tid: int) -> str:
        """
        获取任务详情

        Args:
            tid: 任务 ID

        Returns:
            JSON 格式的任务信息
        """
        return json.dumps(self._load(tid), indent=2)

    def update(self, tid: int, status: str = None,
               add_blocked_by: list = None, add_blocks: list = None) -> str:
        """
        更新任务状态或依赖关系

        当任务完成时，自动解除其他任务对此任务的阻塞。

        Args:
            tid: 任务 ID
            status: 新状态（可选）
            add_blocked_by: 添加阻塞依赖（可选）
            add_blocks: 添加被阻塞的任务（可选）

        Returns:
            JSON 格式的更新后任务信息
        """
        task = self._load(tid)
        if status:
            task["status"] = status
            # 完成任务时，解除其他任务对此任务的阻塞
            if status == "completed":
                for f in TASKS_DIR.glob("task_*.json"):
                    t = json.loads(f.read_text())
                    if tid in t.get("blockedBy", []):
                        t["blockedBy"].remove(tid)
                        self._save(t)
            # 删除任务
            if status == "deleted":
                (TASKS_DIR / f"task_{tid}.json").unlink(missing_ok=True)
                return f"Task {tid} deleted"
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if add_blocks:
            task["blocks"] = list(set(task["blocks"] + add_blocks))
        self._save(task)
        return json.dumps(task, indent=2)

    def list_all(self) -> str:
        """
        列出所有任务

        Returns:
            格式化的任务列表
        """
        tasks = [json.loads(f.read_text()) for f in sorted(TASKS_DIR.glob("task_*.json"))]
        if not tasks: return "No tasks."
        lines = []
        for t in tasks:
            m = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(t["status"], "[?]")
            owner = f" @{t['owner']}" if t.get("owner") else ""
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            lines.append(f"{m} #{t['id']}: {t['subject']}{owner}{blocked}")
        return "\n".join(lines)

    def claim(self, tid: int, owner: str) -> str:
        """
        认领任务

        将任务状态设置为 in_progress，并设置 owner。

        Args:
            tid: 任务 ID
            owner: 认领者名称

        Returns:
            操作结果信息
        """
        task = self._load(tid)
        task["owner"] = owner
        task["status"] = "in_progress"
        self._save(task)
        return f"Claimed task #{tid} for {owner}"


# =============================================================================
# SECTION: BackgroundManager 后台任务管理 (s08)
#
# 在后台线程中执行长时间运行的命令，避免阻塞主循环。
#
# 工作流程：
# 1. run(command) -> 启动后台线程，返回任务 ID
# 2. 线程执行命令，完成后发送通知到队列
# 3. 主循环每轮调用 drain() 获取完成通知
#
# 通知格式：
#     {"task_id": "abc123", "status": "completed", "result": "..."}
#
# 关键洞察："Agent 可以同时做多件事。"
# =============================================================================

class BackgroundManager:
    """后台任务管理器"""

    def __init__(self):
        """初始化任务字典和通知队列"""
        self.tasks = {}  # task_id -> {status, command, result}
        self.notifications = Queue()  # 完成通知队列

    def run(self, command: str, timeout: int = 120) -> str:
        """
        启动后台任务

        Args:
            command: 要执行的 shell 命令
            timeout: 超时时间（秒）

        Returns:
            启动确认信息，包含任务 ID
        """
        tid = str(uuid.uuid4())[:8]
        self.tasks[tid] = {"status": "running", "command": command, "result": None}
        threading.Thread(target=self._exec, args=(tid, command, timeout), daemon=True).start()
        return f"Background task {tid} started: {command[:80]}"

    def _exec(self, tid: str, command: str, timeout: int):
        """
        后台执行命令（内部方法）

        Args:
            tid: 任务 ID
            command: 要执行的命令
            timeout: 超时时间
        """
        try:
            r = subprocess.run(command, shell=True, cwd=WORKDIR,
                               capture_output=True, text=True, timeout=timeout)
            output = (r.stdout + r.stderr).strip()[:50000]
            self.tasks[tid].update({"status": "completed", "result": output or "(no output)"})
        except Exception as e:
            self.tasks[tid].update({"status": "error", "result": str(e)})
        # 发送完成通知
        self.notifications.put({"task_id": tid, "status": self.tasks[tid]["status"],
                                "result": self.tasks[tid]["result"][:500]})

    def check(self, tid: str = None) -> str:
        """
        检查任务状态

        Args:
            tid: 任务 ID（可选，不提供则列出所有任务）

        Returns:
            任务状态信息
        """
        if tid:
            t = self.tasks.get(tid)
            return f"[{t['status']}] {t.get('result', '(running)')}" if t else f"Unknown: {tid}"
        return "\n".join(f"{k}: [{v['status']}] {v['command'][:60]}" for k, v in self.tasks.items()) or "No bg tasks."

    def drain(self) -> list:
        """
        获取并清空所有完成通知

        在主循环每轮开始时调用，获取已完成任务的通知。

        Returns:
            通知列表
        """
        notifs = []
        while not self.notifications.empty():
            notifs.append(self.notifications.get_nowait())
        return notifs


# =============================================================================
# SECTION: MessageBus 消息总线 (s09)
#
# 基于文件的 JSONL 消息系统，用于队友之间的通信。
#
# 收件箱格式 (.team/inbox/name.jsonl)：
#     {"type": "message", "from": "lead", "content": "...", "timestamp": 1234567890}
#     {"type": "broadcast", "from": "alice", "content": "...", "timestamp": 1234567890}
#
# 消息类型：
# - message: 普通消息
# - broadcast: 广播消息
# - shutdown_request: 关闭请求 (s10)
# - shutdown_response: 关闭响应 (s10)
# - plan_approval_response: 计划审批响应 (s10)
#
# 关键洞察："可以互相交谈的队友。"
# =============================================================================

class MessageBus:
    """消息总线，管理队友间的消息传递"""

    def __init__(self):
        """初始化收件箱目录"""
        INBOX_DIR.mkdir(parents=True, exist_ok=True)

    def send(self, sender: str, to: str, content: str,
             msg_type: str = "message", extra: dict = None) -> str:
        """
        发送消息

        将消息追加到接收者的收件箱文件。

        Args:
            sender: 发送者名称
            to: 接收者名称
            content: 消息内容
            msg_type: 消息类型（默认 "message"）
            extra: 额外的元数据（可选）

        Returns:
            发送确认信息
        """
        msg = {"type": msg_type, "from": sender, "content": content,
               "timestamp": time.time()}
        if extra: msg.update(extra)
        with open(INBOX_DIR / f"{to}.jsonl", "a") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        """
        读取并清空收件箱

        读取后自动清空收件箱（drain 模式）。

        Args:
            name: 收件人名称

        Returns:
            消息列表
        """
        path = INBOX_DIR / f"{name}.jsonl"
        if not path.exists(): return []
        msgs = [json.loads(l) for l in path.read_text().strip().splitlines() if l]
        path.write_text("")  # 清空收件箱
        return msgs

    def broadcast(self, sender: str, content: str, names: list) -> str:
        """
        广播消息给所有队友

        Args:
            sender: 发送者名称
            content: 消息内容
            names: 所有队友名称列表

        Returns:
            广播确认信息
        """
        count = 0
        for n in names:
            if n != sender:
                self.send(sender, n, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"


# =============================================================================
# SECTION: Shutdown & Plan Tracking 关闭和计划追踪 (s10)
#
# 用于优雅关闭队友和审批计划的请求追踪。
#
# 关闭协议流程：
# 1. Lead 发送 shutdown_request，包含 request_id
# 2. Teammate 收到后进入关闭状态
# 3. Lead 可以通过 request_id 追踪关闭状态
#
# 计划审批流程：
# 1. Teammate 提交计划（发送消息）
# 2. Lead 审批后发送 plan_approval_response
# =============================================================================

# 关闭请求追踪：request_id -> {target, status}
shutdown_requests = {}

# 计划审批追踪：request_id -> {from, status}
plan_requests = {}


# =============================================================================
# SECTION: TeammateManager 队友管理 (s09/s11)
#
# 管理持久化的自主代理队友。
#
# 队友生命周期：
#     spawn -> [work -> idle -> work -> ...] -> shutdown
#
# 工作阶段 (WORK PHASE)：
# - 执行任务，使用工具
# - 处理收件箱消息
# - 可以调用 idle 进入空闲阶段
#
# 空闲阶段 (IDLE PHASE)：
# - 轮询收件箱和未认领任务
# - 发现工作后自动恢复到工作阶段
# - 超时后自动关闭 (s11 自主代理)
#
# 自动认领任务 (s11)：
# - 空闲时检查未认领的任务
# - 自动认领并开始工作
# - 压缩后重新注入身份信息
#
# 配置文件 (.team/config.json):
#     {
#         "team_name": "default",
#         "members": [
#             {"name": "alice", "role": "coder", "status": "idle"}
#         ]
#     }
# =============================================================================

class TeammateManager:
    """队友管理器"""

    def __init__(self, bus: MessageBus, task_mgr: TaskManager):
        """
        初始化队友管理器

        Args:
            bus: 消息总线实例
            task_mgr: 任务管理器实例
        """
        TEAM_DIR.mkdir(exist_ok=True)
        self.bus = bus
        self.task_mgr = task_mgr
        self.config_path = TEAM_DIR / "config.json"
        self.config = self._load()
        self.threads = {}  # name -> Thread

    def _load(self) -> dict:
        """加载团队配置"""
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"team_name": "default", "members": []}

    def _save(self):
        """保存团队配置"""
        self.config_path.write_text(json.dumps(self.config, indent=2))

    def _find(self, name: str) -> dict:
        """查找指定名称的队友"""
        for m in self.config["members"]:
            if m["name"] == name: return m
        return None

    def spawn(self, name: str, role: str, prompt: str) -> str:
        """
        启动队友

        如果队友已存在且处于 idle/shutdown 状态，重新激活。
        否则创建新的队友。

        Args:
            name: 队友名称
            role: 角色描述
            prompt: 初始任务提示

        Returns:
            启动确认信息
        """
        member = self._find(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save()
        threading.Thread(target=self._loop, args=(name, role, prompt), daemon=True).start()
        return f"Spawned '{name}' (role: {role})"

    def _set_status(self, name: str, status: str):
        """更新队友状态"""
        member = self._find(name)
        if member:
            member["status"] = status
            self._save()

    def _loop(self, name: str, role: str, prompt: str):
        """
        队友主循环（在独立线程中运行）

        包含两个阶段：
        1. WORK PHASE: 执行任务直到 idle 或完成
        2. IDLE PHASE: 等待新工作或超时关闭

        Args:
            name: 队友名称
            role: 角色描述
            prompt: 初始提示
        """
        team_name = self.config["team_name"]
        sys_prompt = (f"You are '{name}', role: {role}, team: {team_name}, at {WORKDIR}. "
                      f"Use idle when done with current work. You may auto-claim tasks.")
        messages = [{"role": "user", "content": prompt}]

        # 队友可用工具
        tools = [
            {"name": "bash", "description": "Run command.", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
            {"name": "read_file", "description": "Read file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
            {"name": "write_file", "description": "Write file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "edit_file", "description": "Edit file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
            {"name": "send_message", "description": "Send message.", "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}}, "required": ["to", "content"]}},
            {"name": "idle", "description": "Signal no more work.", "input_schema": {"type": "object", "properties": {}}},
            {"name": "claim_task", "description": "Claim task by ID.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
        ]

        while True:
            # ==================== WORK PHASE ====================
            for _ in range(50):  # 最多 50 轮
                # 检查收件箱
                inbox = self.bus.read_inbox(name)
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        self._set_status(name, "shutdown")
                        return
                    messages.append({"role": "user", "content": json.dumps(msg)})

                # LLM 调用
                try:
                    response = client.messages.create(
                        model=MODEL, system=sys_prompt, messages=messages,
                        tools=tools, max_tokens=8000)
                except Exception:
                    self._set_status(name, "shutdown")
                    return

                messages.append({"role": "assistant", "content": response.content})
                if response.stop_reason != "tool_use":
                    break

                # 执行工具
                results = []
                idle_requested = False
                for block in response.content:
                    if block.type == "tool_use":
                        if block.name == "idle":
                            idle_requested = True
                            output = "Entering idle phase."
                        elif block.name == "claim_task":
                            output = self.task_mgr.claim(block.input["task_id"], name)
                        elif block.name == "send_message":
                            output = self.bus.send(name, block.input["to"], block.input["content"])
                        else:
                            dispatch = {"bash": lambda **kw: run_bash(kw["command"]),
                                        "read_file": lambda **kw: run_read(kw["path"]),
                                        "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
                                        "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"])}
                            output = dispatch.get(block.name, lambda **kw: "Unknown")(**block.input)
                        print(f"  [{name}] {block.name}: {str(output)[:120]}")
                        results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})

                messages.append({"role": "user", "content": results})
                if idle_requested:
                    break

            # ==================== IDLE PHASE ====================
            # 轮询收件箱和未认领任务，超时后关闭
            self._set_status(name, "idle")
            resume = False
            for _ in range(IDLE_TIMEOUT // max(POLL_INTERVAL, 1)):
                time.sleep(POLL_INTERVAL)
                # 检查收件箱
                inbox = self.bus.read_inbox(name)
                if inbox:
                    for msg in inbox:
                        if msg.get("type") == "shutdown_request":
                            self._set_status(name, "shutdown")
                            return
                        messages.append({"role": "user", "content": json.dumps(msg)})
                    resume = True
                    break

                # 自动认领未认领的任务 (s11)
                unclaimed = []
                for f in sorted(TASKS_DIR.glob("task_*.json")):
                    t = json.loads(f.read_text())
                    if t.get("status") == "pending" and not t.get("owner") and not t.get("blockedBy"):
                        unclaimed.append(t)
                if unclaimed:
                    task = unclaimed[0]
                    self.task_mgr.claim(task["id"], name)
                    # 身份重新注入（用于压缩后的上下文）
                    if len(messages) <= 3:
                        messages.insert(0, {"role": "user", "content":
                            f"<identity>You are '{name}', role: {role}, team: {team_name}.</identity>"})
                        messages.insert(1, {"role": "assistant", "content": f"I am {name}. Continuing."})
                    messages.append({"role": "user", "content":
                        f"<auto-claimed>Task #{task['id']}: {task['subject']}\n{task.get('description', '')}</auto-claimed>"})
                    messages.append({"role": "assistant", "content": f"Claimed task #{task['id']}. Working on it."})
                    resume = True
                    break

            if not resume:
                self._set_status(name, "shutdown")
                return
            self._set_status(name, "working")

    def list_all(self) -> str:
        """列出所有队友及其状态"""
        if not self.config["members"]: return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def member_names(self) -> list:
        """获取所有队友名称列表"""
        return [m["name"] for m in self.config["members"]]


# =============================================================================
# SECTION: 全局实例
#
# 创建所有管理器的单例实例，供整个应用使用。
# =============================================================================
TODO = TodoManager()  # 待办事项管理器
SKILLS = SkillLoader(SKILLS_DIR)  # 技能加载器
TASK_MGR = TaskManager()  # 文件任务管理器
BG = BackgroundManager()  # 后台任务管理器
BUS = MessageBus()  # 消息总线
TEAM = TeammateManager(BUS, TASK_MGR)  # 队友管理器


# =============================================================================
# SECTION: 系统提示词
#
# 定义 Agent 的行为规范和可用能力。
# =============================================================================
SYSTEM = f"""You are a coding agent at {WORKDIR}. Use tools to solve tasks.
Prefer task_create/task_update/task_list for multi-step work. Use TodoWrite for short checklists.
Use task for subagent delegation. Use load_skill for specialized knowledge.
Skills: {SKILLS.descriptions()}"""


# =============================================================================
# SECTION: Shutdown Protocol 关闭协议 (s10)
#
# 优雅关闭队友的握手协议。
# 发送关闭请求并追踪请求状态。
# =============================================================================

def handle_shutdown_request(teammate: str) -> str:
    """
    发送关闭请求给队友

    Args:
        teammate: 队友名称

    Returns:
        请求确认信息
    """
    req_id = str(uuid.uuid4())[:8]
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    BUS.send("lead", teammate, "Please shut down.", "shutdown_request", {"request_id": req_id})
    return f"Shutdown request {req_id} sent to '{teammate}'"


# =============================================================================
# SECTION: Plan Approval 计划审批 (s10)
#
# 队友提交计划后，Lead 可以批准或拒绝。
# =============================================================================

def handle_plan_review(request_id: str, approve: bool, feedback: str = "") -> str:
    """
    审批队友的计划

    Args:
        request_id: 请求 ID
        approve: 是否批准
        feedback: 反馈信息

    Returns:
        审批结果
    """
    req = plan_requests.get(request_id)
    if not req: return f"Error: Unknown plan request_id '{request_id}'"
    req["status"] = "approved" if approve else "rejected"
    BUS.send("lead", req["from"], feedback, "plan_approval_response",
             {"request_id": request_id, "approve": approve, "feedback": feedback})
    return f"Plan {req['status']} for '{req['from']}'"


# =============================================================================
# SECTION: Tool Handlers 工具处理器 (s02)
#
# 工具名称到处理函数的映射。每个处理器接收关键字参数并返回字符串结果。
# =============================================================================
TOOL_HANDLERS = {
    # === 基础文件和命令工具 ===
    "bash":             lambda **kw: run_bash(kw["command"]),
    "read_file":        lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file":       lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":        lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),

    # === 网络工具 ===
    "web_search":       lambda **kw: run_web_search(kw["query"]),
    "weather":          lambda **kw: run_weather(kw["cities"], kw["date"]),

    # === 待办和子代理 ===
    "TodoWrite":        lambda **kw: TODO.update(kw["items"]),
    "task":             lambda **kw: run_subagent(kw["prompt"], kw.get("agent_type", "Explore")),
    "load_skill":       lambda **kw: SKILLS.load(kw["name"]),

    # === 上下文压缩 ===
    "compress":         lambda **kw: "Compressing...",

    # === 后台任务 ===
    "background_run":   lambda **kw: BG.run(kw["command"], kw.get("timeout", 120)),
    "check_background": lambda **kw: BG.check(kw.get("task_id")),

    # === 文件任务系统 ===
    "task_create":      lambda **kw: TASK_MGR.create(kw["subject"], kw.get("description", "")),
    "task_get":         lambda **kw: TASK_MGR.get(kw["task_id"]),
    "task_update":      lambda **kw: TASK_MGR.update(kw["task_id"], kw.get("status"), kw.get("add_blocked_by"), kw.get("add_blocks")),
    "task_list":        lambda **kw: TASK_MGR.list_all(),

    # === 团队协作 ===
    "spawn_teammate":   lambda **kw: TEAM.spawn(kw["name"], kw["role"], kw["prompt"]),
    "list_teammates":   lambda **kw: TEAM.list_all(),
    "send_message":     lambda **kw: BUS.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
    "read_inbox":       lambda **kw: json.dumps(BUS.read_inbox("lead"), indent=2),
    "broadcast":        lambda **kw: BUS.broadcast("lead", kw["content"], TEAM.member_names()),

    # === 关闭和审批协议 ===
    "shutdown_request": lambda **kw: handle_shutdown_request(kw["teammate"]),
    "plan_approval":    lambda **kw: handle_plan_review(kw["request_id"], kw["approve"], kw.get("feedback", "")),

    # === 其他 ===
    "idle":             lambda **kw: "Lead does not idle.",
    "claim_task":       lambda **kw: TASK_MGR.claim(kw["task_id"], "lead"),
}

# =============================================================================
# SECTION: Tool Definitions 工具定义
#
# 定义所有可用工具的 JSON Schema，供 LLM 调用。
# 这些定义遵循 Anthropic 的工具使用 API 格式。
# =============================================================================
TOOLS = [
    # === 基础文件和命令工具 ===
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},

    # === 网络工具 ===
    {"name": "web_search", "description": "Search the web for real-time information.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string", "description": "Search query"}}, "required": ["query"]}},
    {"name": "weather", "description": "Query weather for multiple cities. Returns JSON array format.",
     "input_schema": {"type": "object", "properties": {"cities": {"type": "array", "items": {"type": "string"}, "description": "List of city names"}, "date": {"type": "string", "description": "Date (e.g. '今天', '明天', '2024-03-20')"}}, "required": ["cities", "date"]}},

    # === 待办和子代理 ===
    {"name": "TodoWrite", "description": "Update task tracking list.",
     "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}, "activeForm": {"type": "string"}}, "required": ["content", "status", "activeForm"]}}}, "required": ["items"]}},
    {"name": "task", "description": "Spawn a subagent for isolated exploration or work.",
     "input_schema": {"type": "object", "properties": {"prompt": {"type": "string"}, "agent_type": {"type": "string", "enum": ["Explore", "general-purpose"]}}, "required": ["prompt"]}},
    {"name": "load_skill", "description": "Load specialized knowledge by name.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},

    # === 上下文压缩 ===
    {"name": "compress", "description": "Manually compress conversation context.",
     "input_schema": {"type": "object", "properties": {}}},

    # === 后台任务 ===
    {"name": "background_run", "description": "Run command in background thread.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]}},
    {"name": "check_background", "description": "Check background task status.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}}},

    # === 文件任务系统 ===
    {"name": "task_create", "description": "Create a persistent file task.",
     "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}}, "required": ["subject"]}},
    {"name": "task_get", "description": "Get task details by ID.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
    {"name": "task_update", "description": "Update task status or dependencies.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "deleted"]}, "add_blocked_by": {"type": "array", "items": {"type": "integer"}}, "add_blocks": {"type": "array", "items": {"type": "integer"}}}, "required": ["task_id"]}},
    {"name": "task_list", "description": "List all tasks.",
     "input_schema": {"type": "object", "properties": {}}},

    # === 团队协作 ===
    {"name": "spawn_teammate", "description": "Spawn a persistent autonomous teammate.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}, "prompt": {"type": "string"}}, "required": ["name", "role", "prompt"]}},
    {"name": "list_teammates", "description": "List all teammates.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "send_message", "description": "Send a message to a teammate.",
     "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}}, "required": ["to", "content"]}},
    {"name": "read_inbox", "description": "Read and drain the lead's inbox.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "broadcast", "description": "Send message to all teammates.",
     "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}},

    # === 关闭和审批协议 ===
    {"name": "shutdown_request", "description": "Request a teammate to shut down.",
     "input_schema": {"type": "object", "properties": {"teammate": {"type": "string"}}, "required": ["teammate"]}},
    {"name": "plan_approval", "description": "Approve or reject a teammate's plan.",
     "input_schema": {"type": "object", "properties": {"request_id": {"type": "string"}, "approve": {"type": "boolean"}, "feedback": {"type": "string"}}, "required": ["request_id", "approve"]}},

    # === 其他 ===
    {"name": "idle", "description": "Enter idle state.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "claim_task", "description": "Claim a task from the board.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
]


# =============================================================================
# SECTION: Agent Loop 代理循环 (s01)
#
# 核心的代理循环：调用 LLM，执行工具，循环直到停止。
#
# 每轮循环包含：
# 1. 微压缩 (s06) - 清理旧的 tool_result
# 2. 自动压缩检查 (s06) - 超过阈值时压缩上下文
# 3. 后台通知处理 (s08) - 获取已完成的后台任务
# 4. 收件箱检查 (s09) - 读取队友消息
# 5. LLM 调用
# 6. 工具执行
# 7. Todo 提醒检查 (s03) - 3 轮未更新时提醒
#
# 关键洞察："整个秘密就是一个模式：while stop_reason == 'tool_use'"
# =============================================================================

def agent_loop(messages: list):
    """
    代理主循环

    持续调用 LLM 并执行工具，直到模型停止调用工具。

    Args:
        messages: 对话消息列表（会被修改）
    """
    rounds_without_todo = 0
    loop_count = 0

    while True:
        loop_count += 1

        # === 日志记录 ===
        try:
            msg_json = json.dumps(messages[-3:], ensure_ascii=False, default=str)
            logger.info(f"[LLM Call #{loop_count}] Input messages: {msg_json}")
        except Exception:
            logger.info(f"[LLM Call #{loop_count}] Input messages: (encoding error)")

        # === s06: 压缩管道 ===
        # 微压缩：清理旧的 tool_result
        microcompact(messages)
        # 自动压缩：超过阈值时压缩
        if estimate_tokens(messages) > TOKEN_THRESHOLD:
            print("[auto-compact triggered]")
            messages[:] = auto_compact(messages)

        # === s08: 后台通知 ===
        notifs = BG.drain()
        if notifs:
            txt = "\n".join(f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs)
            messages.append({"role": "user", "content": f"<background-results>\n{txt}\n</background-results>"})
            messages.append({"role": "assistant", "content": "Noted background results."})

        # === s09: 检查 lead 收件箱 ===
        inbox = BUS.read_inbox("lead")
        if inbox:
            messages.append({"role": "user", "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>"})
            messages.append({"role": "assistant", "content": "Noted inbox messages."})

        # === LLM 调用 ===
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )

        # === 日志记录响应 ===
        logger.info(f"[LLM Call #{loop_count}] Stop reason: {response.stop_reason}")
        try:
            resp_json = json.dumps([b.model_dump() if hasattr(b, 'model_dump') else str(b) for b in response.content], ensure_ascii=False)
            logger.debug(f"[LLM Call #{loop_count}] Response: {resp_json[:2000]}")
        except Exception:
            logger.debug(f"[LLM Call #{loop_count}] Response: (encoding error)")

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return

        # === 工具执行 ===
        results = []
        used_todo = False
        manual_compress = False

        for block in response.content:
            if block.type == "tool_use":
                # 日志记录工具调用
                try:
                    input_json = json.dumps(block.input, ensure_ascii=False)
                    logger.info(f"[Tool Call] {block.name} | Input: {input_json}")
                except Exception:
                    logger.info(f"[Tool Call] {block.name} | Input: (encoding error)")

                # 检测手动压缩请求
                if block.name == "compress":
                    manual_compress = True

                # 执行工具
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"

                # 日志记录工具结果
                try:
                    output_str = str(output)
                    logger.info(f"[Tool Result] {block.name} | Output: {output_str[:500]}")
                except Exception:
                    logger.info(f"[Tool Result] {block.name} | Output: (encoding error)")

                print(f"> {block.name}: {str(output)[:200]}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})

                if block.name == "TodoWrite":
                    used_todo = True

        # === s03: Todo 提醒 ===
        # 如果有待办事项且 3 轮未更新，注入提醒
        rounds_without_todo = 0 if used_todo else rounds_without_todo + 1
        if TODO.has_open_items() and rounds_without_todo >= 3:
            results.insert(0, {"type": "text", "text": "<reminder>Update your todos.</reminder>"})

        messages.append({"role": "user", "content": results})

        # === s06: 手动压缩 ===
        if manual_compress:
            print("[manual compact]")
            messages[:] = auto_compact(messages)


# =============================================================================
# SECTION: REPL 交互式命令行
#
# 提供交互式命令行界面，支持：
# - 普通对话输入
# - /compact 手动压缩
# - /tasks 列出任务
# - /team 列出队友
# - /inbox 读取收件箱
# - q/exit/空行 退出
# =============================================================================

if __name__ == "__main__":
    history = []  # 对话历史

    while True:
        try:
            query = input("\033[36ms_full >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        # 退出命令
        if query.strip().lower() in ("q", "exit", ""):
            break

        # REPL 命令
        if query.strip() == "/compact":
            if history:
                print("[manual compact via /compact]")
                history[:] = auto_compact(history)
            continue
        if query.strip() == "/tasks":
            print(TASK_MGR.list_all())
            continue
        if query.strip() == "/team":
            print(TEAM.list_all())
            continue
        if query.strip() == "/inbox":
            print(json.dumps(BUS.read_inbox("lead"), indent=2))
            continue

        # 正常对话
        history.append({"role": "user", "content": query})
        agent_loop(history)
        print()
