#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
应用初始化模块（多用户多会话架构）

负责初始化 SessionManager 并提供会话管理接口。
不再使用全局单例模式，支持多用户并发访问。
"""

from pathlib import Path
from typing import Optional

from .core import SessionManager
from .subagent.runner import run_subagent


# SessionManager 单例（通过 get_instance() 访问）
_manager: Optional[SessionManager] = None


def get_manager() -> SessionManager:
    """
    获取 SessionManager 单例实例。

    Returns:
        SessionManager 实例

    Raises:
        RuntimeError: 如果应用尚未初始化
    """
    global _manager
    if _manager is None:
        raise RuntimeError("应用尚未初始化。请先调用 initialize()。")
    return _manager


def initialize(base_workdir: Optional[Path] = None) -> SessionManager:
    """
    初始化应用并返回 SessionManager 单例。

    此函数创建 SessionManager 单例，用于管理所有用户会话。

    Args:
        base_workdir: 基础工作目录（默认为当前目录）

    Returns:
        SessionManager 实例
    """
    global _manager

    if _manager is not None:
        return _manager

    if base_workdir is None:
        base_workdir = Path.cwd()

    _manager = SessionManager(base_workdir)
    return _manager


def reset():
    """
    重置应用状态（主要用于测试）。

    清除 SessionManager 单例，允许重新初始化。
    """
    global _manager
    _manager = None
    SessionManager.reset()


# ============================================================================
# 便捷函数：直接操作会话
# ============================================================================

def create_session(
    user_id: str,
    user_config: dict,
    session_id: Optional[str] = None,
    **overrides
):
    """
    创建新会话并初始化所有组件。

    Args:
        user_id: 用户 ID
        user_config: 用户配置字典
        session_id: 会话 ID（可选，不提供则自动生成）
        **overrides: 覆盖配置的额外参数

    Returns:
        已初始化的 Session 实例
    """
    manager = get_manager()
    session = manager.create_session(user_id, user_config, session_id, **overrides)
    manager.initialize_session_components(session)

    # 设置子代理处理器（使用会话隔离的工作目录）
    from ..tools import registry
    session.tool_handlers["task"] = lambda **kw: registry._handle_task(
        kw["prompt"],
        kw.get("agent_type", "Explore"),
        session.config.session_workdir,
        session.client,
        session.model,
        session.tool_handlers,
        session
    )

    return session


def get_session(user_id: str, session_id: str):
    """
    获取指定会话。

    Args:
        user_id: 用户 ID
        session_id: 会话 ID

    Returns:
        Session 实例，如果不存在则返回 None
    """
    manager = get_manager()
    return manager.get_session(user_id, session_id)


def close_session(user_id: str, session_id: str) -> bool:
    """
    关闭并移除会话。

    Args:
        user_id: 用户 ID
        session_id: 会话 ID

    Returns:
        是否成功关闭
    """
    manager = get_manager()
    return manager.close_session(user_id, session_id)


def list_user_sessions(user_id: str):
    """
    列出用户的所有会话。

    Args:
        user_id: 用户 ID

    Returns:
        该用户的所有活跃会话列表
    """
    manager = get_manager()
    return manager.list_user_sessions(user_id)


def list_all_sessions():
    """
    列出所有会话。

    Returns:
        所有活跃会话列表
    """
    manager = get_manager()
    return manager.list_all_sessions()


# ============================================================================
# 向后兼容：旧的 API 接口（单用户模式）
# ============================================================================

# 这些全局变量仅用于向后兼容，不推荐在新代码中使用
config = None
logger = None
client = None
zhipu_client = None
todo_mgr = None
task_mgr = None
bg_mgr = None
bus = None
team = None
skills = None
tools = None
tool_handlers = None
workdir = None
model = None
token_threshold = None


def init_legacy_session(user_id: str = "default", session_id: str = "default"):
    """
    初始化旧版单用户模式的会话（向后兼容）。

    此函数创建一个会话并将其状态同步到全局变量。

    Args:
        user_id: 用户 ID
        session_id: 会话 ID
    """
    global config, logger, client, zhipu_client
    global todo_mgr, task_mgr, bg_mgr, bus, team, skills
    global tools, tool_handlers, workdir, model, token_threshold

    # 创建会话
    from .core import get_config, get_user_config_dict
    app_config = get_config()
    session = create_session(
        user_id,
        user_config=get_user_config_dict(
            model_id=app_config.get("model_id"),
            anthropic_api_key=app_config.get("anthropic_api_key"),
            anthropic_base_url=app_config.get("anthropic_base_url"),
            token_threshold=app_config.get("token_threshold"),
            poll_interval=app_config.get("poll_interval"),
            idle_timeout=app_config.get("idle_timeout"),
        ),
        session_id=session_id
    )

    # 同步到全局变量
    config = session.config
    logger = session.logger
    client = session.client
    zhipu_client = session.zhipu_client
    todo_mgr = session.todo_mgr
    task_mgr = session.task_mgr
    bg_mgr = session.bg_mgr
    bus = session.bus
    team = session.team
    skills = session.skills
    tools = session.tools
    tool_handlers = session.tool_handlers
    workdir = session.config.workdir
    model = session.model
    token_threshold = session.token_threshold

    return session
