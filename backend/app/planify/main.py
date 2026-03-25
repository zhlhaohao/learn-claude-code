#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Planify - REPL 交互式命令行（多用户多会话架构）

提供交互式命令行界面，与代理系统进行对话。
支持多用户多会话管理。

支持的命令：
- 正常对话输入
- /user <id> - 切换用户
- /session <id> - 切换会话
- /new-session [id] - 创建新会话
- /sessions - 列出当前用户的所有会话
- /compact - 手动压缩
- /tasks - 列出任务
- /team - 列出队友
- /inbox - 读取收件箱
- /exit - 退出
"""

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
from .bootstrap import (
    initialize,
    get_manager,
    create_session,
    get_session,
    close_session,
    list_user_sessions,
    init_legacy_session,
)
from .agent import run_agent_loop
from .context import auto_compact


# ============================================================================
# REPL 状态管理
# ============================================================================

class REPLState:
    """REPL 状态管理"""

    def __init__(self):
        self.current_user_id: str = "default"
        self.current_session_id: str = "default"
        self.history: list = []

    @property
    def key(self) -> str:
        """返回当前会话键"""
        return f"{self.current_user_id}:{self.current_session_id}"


# ============================================================================
# REPL 命令处理器
# ============================================================================

class REPLCommands:
    """REPL 命令处理器"""

    def __init__(self, state: REPLState):
        self.state = state

    def handle_user(self, args: list) -> str:
        """切换用户"""
        if not args:
            manager = get_manager()
            sessions = manager.list_all_sessions()
            users = set(s.user_id for s in sessions)
            return f"当前用户: {self.state.current_user_id}\n所有用户: {', '.join(sorted(users)) or '(无)'}"

        user_id = args[0]
        self.state.current_user_id = user_id

        # 尝试获取该用户的第一个会话
        sessions = list_user_sessions(user_id)
        if sessions:
            self.state.current_session_id = sessions[0].session_id
            return f"切换到用户: {user_id}, 会话: {self.state.current_session_id}"
        else:
            return f"切换到用户: {user_id} (无会话，使用 /new-session 创建)"

    def handle_session(self, args: list) -> str:
        """切换会话"""
        if not args:
            sessions = list_user_sessions(self.state.current_user_id)
            if not sessions:
                return f"用户 {self.state.current_user_id} 无会话"
            lines = [f"当前会话: {self.state.current_session_id}", f"用户 {self.state.current_user_id} 的会话:"]
            for s in sessions:
                lines.append(f"  - {s.session_id} ({s.status})")
            return "\n".join(lines)

        session_id = args[0]
        session = get_session(self.state.current_user_id, session_id)
        if session:
            self.state.current_session_id = session_id
            self.state.history = session.get_messages()
            return f"切换到会话: {session_id}"
        else:
            return f"错误: 会话 {session_id} 不存在"

    def handle_new_session(self, args: list) -> str:
        """创建新会话"""
        session_id = args[0] if args else None

        # 获取用户配置（这里从环境变量获取，实际应用中应从数据库等获取）
        from .core import get_config
        app_config = get_config()

        user_config = {
            "model_id": app_config.get("model_id"),
            "anthropic_api_key": app_config.get("anthropic_api_key"),
            "anthropic_base_url": app_config.get("anthropic_base_url"),
            "token_threshold": app_config.get("token_threshold", 100000),
            "poll_interval": app_config.get("poll_interval", 5),
            "idle_timeout": app_config.get("idle_timeout", 60),
        }

        session = create_session(self.state.current_user_id, user_config, session_id)
        self.state.current_session_id = session.session_id
        self.state.history = []

        return f"创建新会话: {session.session_id}"

    def handle_sessions(self, args: list) -> str:
        """列出当前用户的所有会话"""
        sessions = list_user_sessions(self.state.current_user_id)
        if not sessions:
            return f"用户 {self.state.current_user_id} 无会话"
        lines = [f"用户 {self.state.current_user_id} 的会话:"]
        for s in sessions:
            current = " (当前)" if s.session_id == self.state.current_session_id else ""
            lines.append(f"  - {s.session_id}{current} ({s.status})")
        return "\n".join(lines)

    def handle_compact(self, args: list, session) -> str:
        """手动压缩"""
        if not session:
            return "错误: 无活跃会话"

        if not self.state.history:
            return "无消息历史可压缩"

        compacted = auto_compact(
            self.state.history, session.client, session.model, session.config.transcript_dir
        )
        session.replace_messages_in_place(compacted)
        return f"压缩完成: {len(self.state.history)} 条消息"

    def handle_tasks(self, args: list, session) -> str:
        """列出任务"""
        if not session:
            return "错误: 无活跃会话"
        return session.task_mgr.list_all()

    def handle_team(self, args: list, session) -> str:
        """列出队友"""
        if not session:
            return "错误: 无活跃会话"
        return session.team.list_all()

    def handle_inbox(self, args: list, session) -> str:
        """读取收件箱"""
        if not session:
            return "错误: 无活跃会话"
        inbox = session.bus.read_inbox("lead")
        return json.dumps(inbox, indent=2, ensure_ascii=False)

    def handle_close_session(self, args: list) -> str:
        """关闭当前会话"""
        success = close_session(self.state.current_user_id, self.state.current_session_id)
        if success:
            result = f"已关闭会话: {self.state.current_session_id}"
            self.state.current_session_id = "default"
            self.state.history = []
            return result
        else:
            return f"错误: 无法关闭会话 {self.state.current_session_id}"


# ============================================================================
# REPL 主循环
# ============================================================================

def repl() -> None:
    """
    运行交互式命令行界面 (REPL)。
    """
    # 初始化状态
    state = REPLState()
    commands = REPLCommands(state)

    # 显示欢迎信息
    print("=" * 50)
    print("Planify REPL - 多用户多会话架构")
    print("=" * 50)
    print("可用命令:")
    print("  /user [id]        - 切换用户")
    print("  /session [id]     - 切换会话")
    print("  /new-session [id]  - 创建新会话")
    print("  /sessions         - 列出会话")
    print("  /compact         - 手动压缩")
    print("  /tasks           - 列出任务")
    print("  /team            - 列出队友")
    print("  /inbox           - 读取收件箱")
    print("  /close-session   - 关闭当前会话")
    print("  /exit            - 退出")
    print("=" * 50)

    while True:
        try:
            prompt = f"\033[36m{state.key}\033[0m >> "
            query = input(prompt)
        except (EOFError, KeyboardInterrupt):
            break

        query = query.strip()

        # 退出命令
        if query == "/exit":
            break

        # 解析命令
        parts = query.split(maxsplit=1)
        cmd = parts[0] if parts else ""
        args = parts[1].split() if len(parts) > 1 else []

        # 获取当前会话
        session = get_session(state.current_user_id, state.current_session_id)

        # 处理命令
        result = None
        if cmd == "/user":
            result = commands.handle_user(args)
        elif cmd == "/session":
            result = commands.handle_session(args)
        elif cmd == "/new-session":
            result = commands.handle_new_session(args)
        elif cmd == "/sessions":
            result = commands.handle_sessions(args)
        elif cmd == "/compact":
            result = commands.handle_compact(args, session)
        elif cmd == "/tasks":
            result = commands.handle_tasks(args, session)
        elif cmd == "/team":
            result = commands.handle_team(args, session)
        elif cmd == "/inbox":
            result = commands.handle_inbox(args, session)
        elif cmd == "/close-session":
            result = commands.handle_close_session(args)
        elif cmd.startswith("/"):
            print(f"未知命令: {cmd}")
            continue

        # 显示命令结果
        if result:
            print(result)
            continue

        # 正常对话
        if not session:
            # 尝试创建默认会话
            try:
                session = init_legacy_session(state.current_user_id, state.current_session_id)
                print(f"自动创建会话: {state.current_session_id}")
            except Exception as e:
                print(f"无法创建会话: {e}")
                continue

        state.history.append({"role": "user", "content": query})
        session.append_message({"role": "user", "content": query})

        run_agent_loop(
            messages=state.history,
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
        )

        # 同步消息历史
        session.set_messages(state.history)

        # 打印最终回答
        if state.history and len(state.history) >= 2:
            last_msg = state.history[-1]
            if last_msg.get("role") == "assistant":
                content = last_msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if hasattr(block, "text"):
                            print(block.text)
                else:
                    print(content)
        print()


# ============================================================================
# 主入口
# ============================================================================

if __name__ == "__main__":
    try:
        # 初始化应用
        manager = initialize()

        # 显示管理器信息
        print(f"SessionManager 初始化完成: {manager}")

        # 运行 REPL
        repl()

    except KeyboardInterrupt:
        print("\nInterrupted. Exiting...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        raise
