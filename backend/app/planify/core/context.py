#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SessionContext - 线程本地会话上下文

使用 thread.local 实现线程本地存储，
每个线程可以访问不同的会话实例。
支持跨函数调用时的会话上下文传递。
"""

import threading
from typing import Optional

from .session import Session


class SessionContext:
    """
    线程本地会话上下文

    使用 threading.local 存储当前线程的会话实例，
    实现线程安全的会话隔离。
    """

    _thread_local = threading.local()

    @classmethod
    def set_session(cls, session: Session) -> None:
        """
        设置当前线程的会话。

        Args:
            session: Session 实例
        """
        cls._thread_local.current = session

    @classmethod
    def get_session(cls) -> Optional[Session]:
        """
        获取当前线程的会话。

        Returns:
            Session 实例，如果未设置则返回 None
        """
        return getattr(cls._thread_local, "current", None)

    @classmethod
    def get_required_session(cls) -> Session:
        """
        获取当前线程的会话（必需）。

        Returns:
            Session 实例

        Raises:
            RuntimeError: 如果未设置会话
        """
        session = cls.get_session()
        if session is None:
            raise RuntimeError("No session set in current thread. Call SessionContext.set_session() first.")
        return session

    @classmethod
    def clear(cls) -> None:
        """清除当前线程的会话"""
        if hasattr(cls._thread_local, "current"):
            delattr(cls._thread_local, "current")

    @classmethod
    def has_session(cls) -> bool:
        """
        检查当前线程是否设置了会话。

        Returns:
            如果设置了会话返回 True，否则返回 False
        """
        return hasattr(cls._thread_local, "current")

    @classmethod
    def __enter__(cls, session: Session) -> Session:
        """
        上下文管理器入口。

        Args:
            session: Session 实例

        Returns:
            Session 实例
        """
        cls.set_session(session)
        return session

    @classmethod
    def __exit__(cls, exc_type, exc_val, exc_tb) -> None:
        """上下文管理器出口"""
        cls.clear()


def with_session(session: Session):
    """
    上下文管理器装饰器工厂。

    用法:
        @with_session(my_session)
        def some_function():
            s = SessionContext.get_required_session()
            # ...

    Args:
        session: Session 实例

    Returns:
        装饰器函数
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            old_session = SessionContext.get_session()
            SessionContext.set_session(session)
            try:
                return func(*args, **kwargs)
            finally:
                if old_session is None:
                    SessionContext.clear()
                else:
                    SessionContext.set_session(old_session)
        return wrapper
    return decorator
