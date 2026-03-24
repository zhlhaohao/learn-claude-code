#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重构的代理系统 - 主入口

这是 agents/s_full.py 的模块化版本。
原始文件保持不变。

完整的代理系统包含所有机制：
- s01 - 代理循环（核心 while 循环）
- s02 - 工具使用（工具定义和分发）
- s03 - TodoWrite（任务进度跟踪）
- s04 - 子代理（临时委派代理）
- s05 - 技能（从文件获取专业知识）
- s06 - 上下文压缩（微压缩 + 自动压缩）
- s07 - 文件任务（持久化任务系统）
- s08 - 后台任务（异步命令执行）
- s09 - 代理团队（持久化队友 + 消息总线）
- s10 - 团队协议（关闭握手 + 计划审批）
- s11 - 自主代理（空闲时自动认领任务）
"""

import io
import json
import os
import sys

from pathlib import Path

# ============================================================
# 重要：在任何导入之前设置 UTF-8 编码
# ============================================================
if sys.version_info >= (3, 7):
    # 使用 UTF-8 编码包裹 stdout/stderr 以修复 Windows GBK 问题
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding='utf-8',
        errors='replace',
        newline=None,
        line_buffering=True
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer,
        encoding='utf-8',
        errors='replace',
        newline=None,
        line_buffering=True
    )

# 在 Windows 上启用 UTF-8 模式（Python 3.7+）
if sys.version_info >= (3, 7) and sys.platform == 'win32':
    os.environ['PYTHONUTF8'] = '1'

# 现在可以安全导入 logging
import logging

# 重新配置日志以使用 UTF-8 stdout（在我们的 TextIOWrapper 之后）
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[]  # Don't add handlers yet, will be set up by setup_logging()
)

# =============================================================================
# 编码设置 - 修复 Windows UTF-8 显示问题
# =============================================================================
def setup_encoding():
    """
    设置 UTF-8 编码以实现跨平台兼容性。

    在 Windows 上，将控制台代码页设置为 UTF-8（代码页 65001）。
    在类 Unix 系统上，确保设置了 UTF-8 环境变量。
    """
    # 设置 UTF-8 环境变量
    os.environ['PYTHONIOENCODING'] = 'utf-8'

    # 在 Windows 上，将控制台代码页设置为 UTF-8
    if sys.platform == 'win32':
        try:
            import ctypes
            # 将控制台代码页设置为 UTF-8（代码页 65001）
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            kernel32.SetConsoleCP(65001)
            kernel32.SetConsoleOutputCP(65001)
        except Exception:
            # 如果 ctypes 失败，回退到 chcp
            try:
                os.system('chcp 65001 > nul 2>&1')
            except Exception:
                pass

    # 重新配置 stdout/stderr 以使用 UTF-8（Python 3.7+）
    if sys.version_info >= (3, 7):
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stdin, 'reconfigure'):
            sys.stdin.reconfigure(encoding='utf-8', errors='replace')

# 应用编码设置
setup_encoding()

# UTF-8 输出的安全打印函数
_builtin_print = print  # 保存内置 print
_builtin_input = input  # 保存内置 input

def safe_print(*args, **kwargs):
    """
    安全处理 UTF-8 编码的打印函数。

    此函数尝试使用 UTF-8 编码打印，
    必要时回退到安全字符替换。
    """
    try:
        _builtin_print(*args, **kwargs)
    except UnicodeEncodeError:
        # 回退：使用 errors='replace' 编码并解码回来
        safe_args = []
        for arg in args:
            if isinstance(arg, str):
                safe_args.append(arg.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8'))
            else:
                safe_args.append(arg)
        _builtin_print(*safe_args, **kwargs)

def safe_input(prompt=""):
    """
    安全处理 UTF-8 编码的输入函数。

    此函数尝试使用 UTF-8 编码读取输入。
    在使用 GBK 终端的 Windows 上，将输入转换为 UTF-8。
    """
    try:
        result = _builtin_input(prompt)
        # 在使用 GBK 终端的 Windows 上，将 GBK 转换为 UTF-8
        if sys.platform == 'win32' and sys.stdin.encoding.lower().startswith(('gbk', 'gb2312')):
            try:
                result = result.encode(sys.stdin.encoding, errors='replace').decode('utf-8', errors='replace')
            except Exception:
                pass  # 如果转换失败，保留原始值
        return result
    except UnicodeDecodeError:
        # 回退：处理编码问题
        _builtin_print(prompt, end='', file=sys.stderr, flush=True)
        result = sys.stdin.read().rstrip('\n')
        return result

# 用安全版本覆盖 print 和 input
print = safe_print
input = safe_input

# 确保父目录在导入路径中
sys.path.insert(0, str(Path(__file__).parent))

# 核心导入
from .core import get_config, setup_logging, init_clients

# 管理器导入
from .managers import TodoManager, TaskManager, BackgroundManager, TeammateManager

# 消息传递导入
from .messaging import MessageBus

# 技能导入
from .skills import SkillLoader

# 工具导入
from .tools import build_tool_registry

# 上下文导入
from .context import estimate_tokens, microcompact, auto_compact

# 子代理导入
from .subagent import run_subagent

# 工具导入（用于直接访问）
from .tools.basic import make_basic_tools, run_bash, run_read, run_write, run_edit


# =============================================================================
# 全局实例（通过依赖注入）
# =============================================================================
config = None
logger = None
client = None
zhipu_client = None
TODO = None
TASK_MGR = None
BG = None
BUS = None
TEAM = None
SKILLS = None
TOOLS = None
TOOL_HANDLERS = None

# 配置快捷方式
WORKDIR = None
MODEL = None
TOKEN_THRESHOLD = None


# =============================================================================
# 初始化所有组件
# =============================================================================
def initialize():
    """
    初始化所有系统组件。

    此函数设置：
    1. 配置
    2. 日志
    3. API 客户端
    4. 管理器（Todo, Task, Background, Teammate）
    5. 消息总线
    6. 技能加载器
    7. 工具注册表
    """
    global config, logger, client, zhipu_client
    global TODO, TASK_MGR, BG, BUS, TEAM, SKILLS
    global TOOLS, TOOL_HANDLERS, WORKDIR, MODEL, TOKEN_THRESHOLD

    # 1. 配置
    config = get_config()
    validate_config(config)

    # 配置快捷方式
    WORKDIR = config["workdir"]
    MODEL = config["model_id"]
    TOKEN_THRESHOLD = config["token_threshold"]

    # 2. 日志（不输出到控制台，只记录到文件）
    logger = setup_logging(console_output=False)

    # 3. API 客户端
    client, zhipu_client = init_clients(
        config["anthropic_base_url"],
        config["anthropic_api_key"]
    )

    # 4. 管理器
    TODO = TodoManager()
    TASK_MGR = TaskManager(config["tasks_dir"])
    BG = BackgroundManager(WORKDIR)

    # 5. 消息总线
    BUS = MessageBus(config["inbox_dir"])

    # 6. 技能加载器
    SKILLS = SkillLoader(config["skills_dir"])

    # 7. 队友管理器（复杂，需要多个依赖）
    basic_tools = make_basic_tools(WORKDIR)
    TEAM = TeammateManager(
        bus=BUS,
        task_mgr=TASK_MGR,
        team_dir=config["team_dir"],
        workdir=WORKDIR,
        model=MODEL,
        client=client,
        poll_interval=config["poll_interval"],
        idle_timeout=config["idle_timeout"],
        run_bash=run_bash,
        run_read=run_read,
        run_write=run_write,
        run_edit=run_edit,
    )

    # 8. 工具注册表
    TOOLS, TOOL_HANDLERS = build_tool_registry(
        workdir=WORKDIR,
        zhipu_client=zhipu_client,
        todo_mgr=TODO,
        task_mgr=TASK_MGR,
        bg_mgr=BG,
        bus=BUS,
        team_mgr=TEAM,
        skills_loader=SKILLS,
        run_subagent=run_subagent,
        model=MODEL,
        client=client,
        transcript_dir=config["transcript_dir"],
    )


def validate_config(config: dict):
    """
    验证必需的配置值。

    Args:
        config: 配置字典

    Raises:
        ValueError: 如果缺少必需的配置
    """
    if not config.get("model_id"):
        raise ValueError("MODEL_ID is required. Set it in .env file or environment.")
    if not config.get("anthropic_api_key"):
        raise ValueError("ANTHROPIC_API_KEY is required. Set it in .env file or environment.")


# =============================================================================
# 系统提示词
# =============================================================================
SYSTEM = ""  # 初始化期间设置


def _get_system_prompt() -> str:
    """获取包含技能描述的系统提示词。"""
    if SKILLS is None:
        return ""
    return f"""You are a coding agent at {WORKDIR}. Use tools to solve tasks.
Prefer task_create/task_update/task_list for multi-step work. Use TodoWrite for short checklists.
Use task for subagent delegation. Use load_skill for specialized knowledge.
Skills: {SKILLS.descriptions()}"""


# =============================================================================
# 代理循环 (s01)
# =============================================================================
def agent_loop(messages: list):
    """
    代理主循环。

    持续调用 LLM 并执行工具，直到模型停止调用工具。

    每次循环迭代包含：
    1. 微压缩 (s06) - 清理旧的 tool_result
    2. 自动压缩检查 (s06) - 超过阈值时压缩上下文
    3. 后台通知处理 (s08) - 获取已完成的后台任务
    4. 收件箱检查 (s09) - 读取队友消息
    5. LLM 调用
    6. 工具执行
    7. Todo 提醒检查 (s03) - 3 轮未更新后提醒

    关键洞察："整个秘密就是一个模式：while stop_reason == 'tool_use'"
    """
    global SYSTEM
    if SYSTEM == "":
        SYSTEM = _get_system_prompt()

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
            messages[:] = auto_compact(
                messages, client, MODEL, config["transcript_dir"]
            )

        # === s08: 后台通知 ===
        notifs = BG.drain()
        if notifs:
            txt = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['result']}"
                for n in notifs
            )
            messages.append({
                "role": "user",
                "content": f"<background-results>\n{txt}\n</background-results>"
            })
            messages.append({
                "role": "assistant",
                "content": "Noted background results."
            })

        # === s09: 检查 lead 收件箱 ===
        inbox = BUS.read_inbox("lead")
        if inbox:
            messages.append({
                "role": "user",
                "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>"
            })
            messages.append({
                "role": "assistant",
                "content": "Noted inbox messages."
            })

        # === LLM 调用 ===
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )

        # === 记录响应 ===
        logger.info(f"[LLM Call #{loop_count}] Stop reason: {response.stop_reason}")
        try:
            resp_json = json.dumps(
                [b.model_dump() if hasattr(b, 'model_dump') else str(b) for b in response.content],
                ensure_ascii=False
            )
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
                # 记录工具调用
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

                # 记录工具结果
                try:
                    output_str = str(output)
                    logger.info(f"[Tool Result] {block.name} | Output: {output_str[:500]}")
                except Exception:
                    logger.info(f"[Tool Result] {block.name} | Output: (encoding error)")

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output)
                })

                if block.name == "TodoWrite":
                    used_todo = True

        # === s03: Todo 提醒 ===
        # 如果有开放的 todos，3 轮未更新后提醒
        rounds_without_todo = 0 if used_todo else rounds_without_todo + 1
        if TODO.has_open_items() and rounds_without_todo >= 3:
            results.insert(0, {"type": "text", "text": "<reminder>Update your todos.</reminder>"})

        messages.append({"role": "user", "content": results})

        # === s06: 手动压缩 ===
        if manual_compress:
            messages[:] = auto_compact(
                messages, client, MODEL, config["transcript_dir"]
            )


# =============================================================================
# REPL（交互式命令行）
# =============================================================================
def repl():
    """
    运行交互式命令行界面。

    支持：
    - 正常对话输入
    - /compact - 手动压缩
    - /tasks - 列出任务
    - /team - 列出队友
    - /inbox - 读取收件箱
    - q/exit/空行 - 退出
    """
    history = []

    while True:
        try:
            query = input("\033[36mplanify >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        # 退出命令
        if query.strip().lower() in ("q", "exit", ""):
            break

        # REPL 命令
        if query.strip() == "/compact":
            if history:
                history[:] = auto_compact(
                    history, client, MODEL, config["transcript_dir"]
                )
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
