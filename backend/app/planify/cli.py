#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Planify CLI - 单用户模式入口

单用户模式：当前工作目录直接作为会话目录，无 .sessions/ 子目录。
适合个人开发、本地使用场景。

使用方法:
    python cli.py
"""

import json
import logging
import os
import sys

from pathlib import Path

# 编码模块必须在其他任何导入之前导入
from core import setup_encoding, apply_safe_stdio

# ============================================================================
# ANSI 颜色代码
# ============================================================================
class Colors:
    """终端输出颜色"""
    USER = '\033[36m'      # 青色 - 用户输入
    TOOL_CALL = '\033[33m' # 黄色 - 工具调用
    TOOL_RESULT = '\033[32m'  # 绿色 - 工具返回结果
    ASSISTANT = '\033[94m'    # 浅蓝色 - LLM 回答
    RESET = '\033[0m'     # 重置颜色
    BOLD = '\033[1m'      # 粗体

# 应用编码设置
setup_encoding()
apply_safe_stdio()

# 重新配置日志（CLI 模式输出到控制台）
logging.basicConfig(
    level=logging.WARNING,  # 只显示 WARNING 及以上级别的日志
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[]
)

# 确保父目录和当前目录在导入路径中
# 父目录用于支持 `from planify.xxx import yyy`
sys.path.insert(0, str(Path(__file__).parent.parent))
# 当前目录用于支持 `from xxx import yyy`
sys.path.insert(0, str(Path(__file__).parent))

# 应用导入
from core import get_config, setup_logging, SessionConfig, Session, generate_session_id
from core.client import init_clients
from managers import TodoManager, TaskManager, BackgroundManager, TeammateManager
from messaging import MessageBus
from skills import SkillLoader
from tools import build_tool_registry
from tools.basic import make_basic_tools, run_bash, run_read, run_write, run_edit
from agent import run_agent_loop
from context import auto_compact


def setup_single_user_session():
    """设置单用户会话"""
    # 获取当前工作目录（用户 cd 到的目录）
    workdir = Path.cwd()
    print(f"\n{'=' * 50}")
    print(f"工作目录: {workdir}")
    print(f"{'=' * 50}\n")

    # 加载配置（不加载 .env，避免干扰环境变量）
    config = get_config(load_env=False)

    # 直接从 .env 文件读取配置
    env_path = workdir / ".env"
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=str(env_path), override=True)
        # 重新获取配置以包含加载的环境变量
        config = get_config(load_env=False)

    # 获取 ZhipuAI API 密钥
    zhipu_api_key = os.getenv("ZHIPUAI_API_KEY")
    if not zhipu_api_key:
        print("注意: 未配置 ZHIPUAI_API_KEY，web_search 工具将不可用")
        print("      在 .env 中添加: ZHIPUAI_API_KEY=your_key")
        zhipu_client = None
    else:
        from zhipuai import ZhipuAI
        try:
            zhipu_client = ZhipuAI(api_key=zhipu_api_key)
        except Exception as e:
            print(f"警告: 无法初始化 ZhipuAI 客户端: {e}")
            print("web_search 工具可能不可用")
            zhipu_client = None

    # 单用户模式：直接使用当前目录，创建所需子目录
    team_dir = workdir / ".team"
    tasks_dir = workdir / ".tasks"
    transcript_dir = workdir / ".transcripts"
    inbox_dir = team_dir / "inbox"
    skills_dir = workdir / "skills"
    logs_dir = workdir / "logs"

    # 创建目录
    team_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir.mkdir(parents=True, exist_ok=True)
    inbox_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # 初始化日志
    logger = setup_logging(
        log_dir=logs_dir,
        console_output=True,  # CLI 模式输出到控制台
        console_level=logging.WARNING,  # 控制台只显示 WARNING 及以上
    )
    logger.info("=" * 50 + " CLI Mode Started " + "=" * 50)

    # 初始化 Anthropic 客户端
    from anthropic import Anthropic
    client = Anthropic(base_url=config.get("anthropic_base_url"))

    # 单独初始化 ZhipuAI 客户端（使用 ZHIPUAI_API_KEY 环境变量）
    from zhipuai import ZhipuAI
    zhipu_api_key = os.getenv("ZHIPUAI_API_KEY")
    try:
        zhipu_client = ZhipuAI(api_key=zhipu_api_key)
    except Exception as e:
        print(f"警告: 无法初始化 ZhipuAI 客户端: {e}")
        print("web_search 工具可能不可用")
        # 创建一个假客户端以避免后续错误
        zhipu_client = None

    # 初始化管理器
    todo_mgr = TodoManager()
    task_mgr = TaskManager(tasks_dir)
    bg_mgr = BackgroundManager(workdir)
    bus = MessageBus(inbox_dir)
    skills = SkillLoader(skills_dir)

    # 初始化队友管理器
    basic_tools = make_basic_tools(workdir)
    team = TeammateManager(
        bus=bus,
        task_mgr=task_mgr,
        team_dir=team_dir,
        workdir=workdir,
        model=config.get("model_id"),
        client=client,
        poll_interval=config.get("poll_interval", 5),
        idle_timeout=config.get("idle_timeout", 60),
        run_bash=run_bash,
        run_read=run_read,
        run_write=run_write,
        run_edit=run_edit,
    )

    # 构建工具注册表
    from subagent.runner import run_subagent
    tools, tool_handlers = build_tool_registry(
        workdir=workdir,
        zhipu_client=zhipu_client,
        todo_mgr=todo_mgr,
        task_mgr=task_mgr,
        bg_mgr=bg_mgr,
        bus=bus,
        team_mgr=team,
        skills_loader=skills,
        run_subagent=run_subagent,
        model=config.get("model_id"),
        client=client,
        transcript_dir=transcript_dir,
        session=None,  # 单用户模式不需要 Session 对象
    )

    # 创建单用户 SessionConfig（用于 Session 类）
    session_config = SessionConfig(
        user_id="default",
        session_id="default",
        workdir=workdir,
        model_id=config.get("model_id"),
        anthropic_api_key=config.get("anthropic_api_key"),
        anthropic_base_url=config.get("anthropic_base_url"),
        token_threshold=config.get("token_threshold", 100000),
        poll_interval=config.get("poll_interval", 5),
        idle_timeout=config.get("idle_timeout", 60),
    )

    # 创建会话
    session = Session(config=session_config)
    session.client = client
    session.zhipu_client = zhipu_client
    session.todo_mgr = todo_mgr
    session.task_mgr = task_mgr
    session.bg_mgr = bg_mgr
    session.bus = bus
    session.team = team
    session.skills = skills
    session.logger = logger
    session.tools = tools
    session.tool_handlers = tool_handlers

    return session, logger


def main():
    """主函数"""
    # 设置单用户会话
    session, logger = setup_single_user_session()

    # 显示欢迎信息
    print(f"\n{'=' * 50}")
    print("Planify CLI - 单用户模式")
    print(f"{'=' * 50}")
    print("\n可用命令:")
    print("  /compact         - 手动压缩")
    print("  /tasks           - 列出任务")
    print("  /team            - 列出队友")
    print("  /inbox           - 读取收件箱")
    print("  /exit            - 退出")
    print(f"{'=' * 50}\n")

    # REPL 主循环
    history = []

    try:
        while True:
            try:
                query = input("planify >> ")
            except (EOFError, KeyboardInterrupt):
                print("\n退出...")
                break

            query = query.strip()

            # 退出命令
            if query == "/exit":
                break

            # /compact - 手动压缩
            if query == "/compact":
                if history:
                    history[:] = auto_compact(
                        history, session.client, session.model,
                        session.config.transcript_dir
                    )
                    logger.info("手动压缩完成")
                    print("压缩完成")
                else:
                    print("无消息历史可压缩")
                continue

            # /tasks - 列出任务
            if query == "/tasks":
                print(session.task_mgr.list_all())
                continue

            # /team - 列出队友
            if query == "/team":
                print(session.team.list_all())
                continue

            # /inbox - 读取收件箱
            if query == "/inbox":
                inbox = session.bus.read_inbox("lead")
                print(json.dumps(inbox, indent=2, ensure_ascii=False))
                continue

            # 正常对话
            # 显示用户输入
            print(f"\n{Colors.USER}{Colors.BOLD}You:{Colors.RESET} {Colors.USER}{query}{Colors.RESET}\n")

            history.append({"role": "user", "content": query})
            session.append_message({"role": "user", "content": query})

            def on_tool_call(name: str, args: dict) -> None:
                args_str = json.dumps(args, ensure_ascii=False, indent=2)
                # 在 JSON 格式化后，将转义的换行符替换为真实换行，让代码更易读
                args_str = args_str.replace('\\n', '\n')
                lines = args_str.split('\n')
                if len(lines) > 10:
                    args_str = '\n'.join(lines[:10]) + '\n  ...'
                print(f"{Colors.TOOL_CALL}{Colors.BOLD}Tool:{Colors.RESET} {Colors.TOOL_CALL}{name}({args_str}){Colors.RESET}\n")

            def on_tool_result(name: str, result: str) -> None:
                result_str = result
                lines = result_str.split('\n')
                if len(lines) > 10:
                    result_str = '\n'.join(lines[:10]) + '\n  ...'
                print(f"{Colors.TOOL_RESULT}{result_str}{Colors.RESET}\n")

            run_agent_loop(
                messages=history,
                client=session.client,
                model=session.model,
                tools=session.tools,
                tool_handlers=session.tool_handlers,
                todo_manager=session.todo_mgr,
                bg_manager=session.bg_mgr,
                bus=session.bus,
                skills_loader=session.skills,
                config=session.config.__dict__,
                logger=session.logger,
                session=session,
                tool_callback=on_tool_call,
                tool_result_callback=on_tool_result,
            )

            # 打印最终回答（只打印自然语言，跳过 tool_use）
            if history and len(history) >= 2:
                last_msg = history[-1]
                if last_msg.get("role") == "assistant":
                    content = last_msg.get("content")
                    if isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if hasattr(block, "text") and block.text:
                                text_parts.append(block.text)
                        if text_parts:
                            full_text = ''.join(text_parts)
                            lines = full_text.split('\n')
                            if len(lines) > 10:
                                full_text = '\n'.join(lines[:10]) + '\n  ...'
                            print(f"{Colors.ASSISTANT}{Colors.BOLD}Assistant:{Colors.RESET}")
                            print(f"{Colors.ASSISTANT}{full_text}{Colors.RESET}")
                    elif isinstance(content, str) and content:
                        lines = content.split('\n')
                        if len(lines) > 10:
                            content = '\n'.join(lines[:10]) + '\n  ...'
                        print(f"{Colors.ASSISTANT}{Colors.BOLD}Assistant:{Colors.RESET}")
                        print(f"{Colors.ASSISTANT}{content}{Colors.RESET}")
            print()

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

    logger.info("=" * 50 + " Session Ended " + "=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
