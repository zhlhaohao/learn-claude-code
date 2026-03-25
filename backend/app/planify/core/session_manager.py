#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SessionManager - 会话管理器

管理所有活跃会话，提供会话创建、查询和关闭功能。
支持多用户多会话架构。
"""

import threading
from pathlib import Path
from typing import Dict, List, Optional

from .client import init_clients
from .logging_config import setup_logging
from .session import Session, SessionConfig, generate_session_id


class SessionManager:
    """
    会话管理器

    使用单例模式，管理所有活跃会话。
    提供线程安全的会话操作。
    """

    _instance: Optional["SessionManager"] = None
    _lock = threading.Lock()

    def __init__(self, base_workdir: Path):
        """
        初始化会话管理器。

        Args:
            base_workdir: 基础工作目录
        """
        self.base_workdir = base_workdir
        self._sessions_lock = threading.RLock()
        self._sessions: Dict[str, Session] = {}  # {user_id:session_id -> Session}

    @classmethod
    def get_instance(cls, base_workdir: Optional[Path] = None) -> "SessionManager":
        """
        获取 SessionManager 单例实例。

        Args:
            base_workdir: 基础工作目录（仅在首次创建时需要）

        Returns:
            SessionManager 实例
        """
        with cls._lock:
            if cls._instance is None:
                if base_workdir is None:
                    base_workdir = Path.cwd()
                cls._instance = cls(base_workdir)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """重置单例（主要用于测试）"""
        with cls._lock:
            cls._instance = None

    def _make_key(self, user_id: str, session_id: str) -> str:
        """生成会话键"""
        return f"{user_id}:{session_id}"

    def create_session(
        self,
        user_id: str,
        user_config: Dict,
        session_id: Optional[str] = None,
        **overrides
    ) -> Session:
        """
        创建新会话。

        Args:
            user_id: 用户 ID
            user_config: 用户配置字典，包含 model_id, anthropic_api_key 等
            session_id: 会话 ID（可选，不提供则自动生成）
            **overrides: 覆盖配置的额外参数

        Returns:
            新创建的 Session 实例
        """
        if session_id is None:
            session_id = generate_session_id()

        key = self._make_key(user_id, session_id)

        with self._sessions_lock:
            if key in self._sessions:
                raise ValueError(f"Session {session_id} for user {user_id} already exists")

            # 合并配置：overrides > user_config > 默认值
            config = SessionConfig(
                user_id=user_id,
                session_id=session_id,
                workdir=self.base_workdir,
                model_id=overrides.get("model_id", user_config.get("model_id")),
                anthropic_api_key=overrides.get("anthropic_api_key", user_config.get("anthropic_api_key")),
                anthropic_base_url=overrides.get("anthropic_base_url", user_config.get("anthropic_base_url")),
                token_threshold=overrides.get("token_threshold", user_config.get("token_threshold", 100000)),
                poll_interval=overrides.get("poll_interval", user_config.get("poll_interval", 5)),
                idle_timeout=overrides.get("idle_timeout", user_config.get("idle_timeout", 60)),
            )

            session = Session(config=config)
            self._sessions[key] = session
            return session

    def get_session(self, user_id: str, session_id: str) -> Optional[Session]:
        """
        获取指定会话。

        Args:
            user_id: 用户 ID
            session_id: 会话 ID

        Returns:
            Session 实例，如果不存在则返回 None
        """
        key = self._make_key(user_id, session_id)
        with self._sessions_lock:
            return self._sessions.get(key)

    def close_session(self, user_id: str, session_id: str) -> bool:
        """
        关闭并移除会话。

        Args:
            user_id: 用户 ID
            session_id: 会话 ID

        Returns:
            是否成功关闭
        """
        key = self._make_key(user_id, session_id)
        with self._sessions_lock:
            if key in self._sessions:
                session = self._sessions[key]
                session.status = "closed"
                del self._sessions[key]
                return True
            return False

    def list_user_sessions(self, user_id: str) -> List[Session]:
        """
        列出用户的所有会话。

        Args:
            user_id: 用户 ID

        Returns:
            该用户的所有活跃会话列表
        """
        prefix = f"{user_id}:"
        with self._sessions_lock:
            return [
                self._sessions[key]
                for key in self._sessions
                if key.startswith(prefix)
            ]

    def list_all_sessions(self) -> List[Session]:
        """
        列出所有会话。

        Returns:
            所有活跃会话列表
        """
        with self._sessions_lock:
            return list(self._sessions.values())

    def initialize_session_components(self, session: Session) -> None:
        """
        初始化会话的所有组件。

        Args:
            session: 要初始化的 Session 实例
        """
        # 确保目录存在
        session.ensure_dirs()

        # 初始化日志
        session.logger = setup_logging(
            log_dir=session.config.logs_dir,
            console_output=False
        )

        # 初始化 API 客户端
        session.client, session.zhipu_client = init_clients(
            session.config.anthropic_base_url,
            session.config.anthropic_api_key
        )

        # 导入管理器（延迟导入避免循环依赖）
        from ..managers import TodoManager, TaskManager, BackgroundManager, TeammateManager
        from ..messaging import MessageBus
        from ..skills import SkillLoader
        from ..tools import build_tool_registry, make_basic_tools
        from ..tools.basic import run_bash, run_read, run_write, run_edit

        # 初始化管理器
        session.todo_mgr = TodoManager()
        session.task_mgr = TaskManager(session.config.tasks_dir)
        session.bg_mgr = BackgroundManager(session.config.workdir)
        session.bus = MessageBus(session.config.inbox_dir)
        session.skills = SkillLoader(session.config.skills_dir)

        # 初始化队友管理器
        basic_tools = make_basic_tools(session.config.workdir)
        session.team = TeammateManager(
            bus=session.bus,
            task_mgr=session.task_mgr,
            team_dir=session.config.team_dir,
            workdir=session.config.workdir,
            model=session.model,
            client=session.client,
            poll_interval=session.poll_interval,
            idle_timeout=session.idle_timeout,
            run_bash=run_bash,
            run_read=run_read,
            run_write=run_write,
            run_edit=run_edit,
        )

        # 构建工具注册表
        session.tools, session.tool_handlers = build_tool_registry(
            workdir=session.config.workdir,
            zhipu_client=session.zhipu_client,
            todo_mgr=session.todo_mgr,
            task_mgr=session.task_mgr,
            bg_mgr=session.bg_mgr,
            bus=session.bus,
            team_mgr=session.team,
            skills_loader=session.skills,
            run_subagent=None,  # 稍后设置
            model=session.model,
            client=session.client,
            transcript_dir=session.config.transcript_dir,
            session=session,
        )

    def __len__(self) -> int:
        """返回活跃会话数量"""
        with self._sessions_lock:
            return len(self._sessions)

    def __repr__(self) -> str:
        """返回管理器表示"""
        with self._sessions_lock:
            return f"SessionManager(sessions={len(self._sessions)}, base_workdir={self.base_workdir})"
