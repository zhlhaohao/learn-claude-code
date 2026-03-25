#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Session 模块 - 会话状态容器和配置

支持多用户多会话架构，提供线程安全的会话隔离。
"""

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from anthropic import Anthropic


@dataclass
class SessionConfig:
    """
    会话配置

    包含会话的所有配置参数和隔离目录路径。
    """
    user_id: str
    session_id: str
    workdir: Path
    model_id: str
    anthropic_api_key: str
    anthropic_base_url: Optional[str] = None
    token_threshold: int = 100000
    poll_interval: int = 5
    idle_timeout: int = 60

    # 隔离目录路径
    @property
    def team_dir(self) -> Path:
        """获取团队配置目录"""
        return self.workdir / f".sessions/{self.user_id}/.team"

    @property
    def tasks_dir(self) -> Path:
        """获取任务目录"""
        return self.workdir / f".sessions/{self.user_id}/.tasks"

    @property
    def transcript_dir(self) -> Path:
        """获取对话记录目录（每个会话独立）"""
        return self.workdir / f".sessions/{self.user_id}/.transcripts/{self.session_id}"

    @property
    def inbox_dir(self) -> Path:
        """获取收件箱目录"""
        return self.team_dir / "inbox"

    @property
    def skills_dir(self) -> Path:
        """获取技能目录（共享）"""
        return self.workdir / "skills"

    @property
    def logs_dir(self) -> Path:
        """获取日志目录"""
        return self.workdir / "logs"


@dataclass
class Session:
    """
    会话状态容器

    封装所有会话相关的状态和组件，提供线程安全的消息历史管理。
    """

    config: SessionConfig

    # 核心组件
    client: Optional[Anthropic] = None
    zhipu_client: Optional[Any] = None
    todo_mgr: Optional[Any] = None
    task_mgr: Optional[Any] = None
    bg_mgr: Optional[Any] = None
    bus: Optional[Any] = None
    team: Optional[Any] = None
    skills: Optional[Any] = None
    logger: Optional[Any] = None

    # 工具
    tools: List[Dict] = field(default_factory=list)
    tool_handlers: Dict[str, Any] = field(default_factory=dict)

    # 线程安全的消息历史
    _messages_lock: threading.RLock = field(default_factory=threading.RLock)
    _messages: List[Dict] = field(default_factory=list)

    # 会话状态
    status: str = "active"
    created_at: float = field(default_factory=lambda: __import__("time").time())

    def append_message(self, message: Dict[str, Any]) -> None:
        """
        线程安全地追加消息到历史。

        Args:
            message: 消息字典
        """
        with self._messages_lock:
            self._messages.append(message)

    def get_messages(self) -> List[Dict[str, Any]]:
        """
        线程安全地获取消息历史（返回副本）。

        Returns:
            消息历史列表的副本
        """
        with self._messages_lock:
            return self._messages.copy()

    def set_messages(self, messages: List[Dict[str, Any]]) -> None:
        """
        线程安全地设置消息历史。

        Args:
            messages: 新的消息历史列表
        """
        with self._messages_lock:
            self._messages = list(messages)

    def replace_messages_in_place(self, messages: List[Dict[str, Any]]) -> None:
        """
        线程安全地就地替换消息历史（原地修改引用）。

        用于压缩后替换整个历史列表。

        Args:
            messages: 新的消息历史列表
        """
        with self._messages_lock:
            self._messages[:] = messages

    @property
    def model(self) -> str:
        """获取模型 ID"""
        return self.config.model_id

    @property
    def token_threshold(self) -> int:
        """获取 token 阈值"""
        return self.config.token_threshold

    @property
    def poll_interval(self) -> int:
        """获取轮询间隔"""
        return self.config.poll_interval

    @property
    def idle_timeout(self) -> int:
        """获取空闲超时"""
        return self.config.idle_timeout

    @property
    def user_id(self) -> str:
        """获取用户 ID"""
        return self.config.user_id

    @property
    def session_id(self) -> str:
        """获取会话 ID"""
        return self.config.session_id

    def ensure_dirs(self) -> None:
        """
        确保所有必需的目录存在。
        """
        self.config.team_dir.mkdir(parents=True, exist_ok=True)
        self.config.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.config.transcript_dir.mkdir(parents=True, exist_ok=True)
        self.config.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.config.skills_dir.mkdir(parents=True, exist_ok=True)
        self.config.logs_dir.mkdir(parents=True, exist_ok=True)

    def __str__(self) -> str:
        """返回会话描述字符串"""
        return f"Session(user={self.user_id}, session={self.session_id}, status={self.status})"


def generate_session_id() -> str:
    """
    生成唯一的会话 ID。

    Returns:
        格式为 sess_<8位UUID> 的字符串
    """
    return f"sess_{uuid.uuid4().hex[:8]}"
