#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SessionContext 模块单元测试

测试 SessionContext 线程本地会话上下文功能。
"""

import sys
from pathlib import Path
import tempfile
import threading

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from planify.core.session import Session, SessionConfig
from planify.core.context import SessionContext, with_session


class TestSessionContext:
    """SessionContext 测试"""

    def setup_method(self):
        """每个测试后清除上下文"""
        SessionContext.clear()

    def test_set_and_get_session(self):
        """测试设置和获取会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            config = SessionConfig(
                user_id="alice",
                session_id="sess_001",
                workdir=workdir,
                model_id="claude-sonnet-4-6",
                anthropic_api_key="sk-test"
            )
            session = Session(config=config)

            SessionContext.set_session(session)
            retrieved = SessionContext.get_session()

            assert retrieved is session

    def test_get_session_without_set(self):
        """测试未设置时获取会话"""
        retrieved = SessionContext.get_session()
        assert retrieved is None

    def test_get_required_session(self):
        """测试获取必需会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            config = SessionConfig(
                user_id="alice",
                session_id="sess_001",
                workdir=workdir,
                model_id="claude-sonnet-4-6",
                anthropic_api_key="sk-test"
            )
            session = Session(config=config)

            SessionContext.set_session(session)
            retrieved = SessionContext.get_required_session()

            assert retrieved is session

    def test_get_required_session_without_set(self):
        """测试未设置时获取必需会话"""
        with pytest.raises(RuntimeError, match="No session set"):
            SessionContext.get_required_session()

    def test_clear(self):
        """测试清除上下文"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            config = SessionConfig(
                user_id="alice",
                session_id="sess_001",
                workdir=workdir,
                model_id="claude-sonnet-4-6",
                anthropic_api_key="sk-test"
            )
            session = Session(config=config)

            SessionContext.set_session(session)
            SessionContext.clear()

            assert SessionContext.get_session() is None

    def test_has_session(self):
        """测试检查是否有会话"""
        assert SessionContext.has_session() is False

        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            config = SessionConfig(
                user_id="alice",
                session_id="sess_001",
                workdir=workdir,
                model_id="claude-sonnet-4-6",
                anthropic_api_key="sk-test"
            )
            session = Session(config=config)

            SessionContext.set_session(session)
            assert SessionContext.has_session() is True


class TestSessionContextThreads:
    """SessionContext 线程隔离测试"""

    def setup_method(self):
        """每个测试后清除上下文"""
        SessionContext.clear()

    def test_thread_isolation(self):
        """测试线程隔离"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)

            # 创建两个会话
            config1 = SessionConfig(
                user_id="alice",
                session_id="sess_001",
                workdir=workdir,
                model_id="claude-sonnet-4-6",
                anthropic_api_key="sk-test"
            )
            session1 = Session(config=config1)

            config2 = SessionConfig(
                user_id="bob",
                session_id="sess_002",
                workdir=workdir,
                model_id="claude-sonnet-4-6",
                anthropic_api_key="sk-test"
            )
            session2 = Session(config=config2)

            # 线程1使用session1
            result1 = []

            def thread1():
                SessionContext.set_session(session1)
                s = SessionContext.get_required_session()
                result1.append(s.user_id)

            # 线程2使用session2
            result2 = []

            def thread2():
                SessionContext.set_session(session2)
                s = SessionContext.get_required_session()
                result2.append(s.user_id)

            t1 = threading.Thread(target=thread1)
            t2 = threading.Thread(target=thread2)

            t1.start()
            t2.start()
            t1.join()
            t2.join()

            assert result1 == ["alice"]
            assert result2 == ["bob"]

    def test_context_manager(self):
        """测试上下文管理器"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)

            config = SessionConfig(
                user_id="alice",
                session_id="sess_001",
                workdir=workdir,
                model_id="claude-sonnet-4-6",
                anthropic_api_key="sk-test"
            )
            session = Session(config=config)

            with SessionContext(session) as s:
                assert s is session
                assert SessionContext.get_session() is session

            assert SessionContext.get_session() is None


class TestWithSession:
    """with_session 装饰器测试"""

    def setup_method(self):
        """每个测试后清除上下文"""
        SessionContext.clear()

    def test_decorator(self):
        """测试装饰器"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)

            config = SessionConfig(
                user_id="alice",
                session_id="sess_001",
                workdir=workdir,
                model_id="claude-sonnet-4-6",
                anthropic_api_key="sk-test"
            )
            session = Session(config=config)

            result = []

            @with_session(session)
            def some_function():
                s = SessionContext.get_required_session()
                result.append(s.user_id)

            some_function()
            assert result == ["alice"]

    def test_decorator_preserves_existing_context(self):
        """测试装饰器保留现有上下文"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)

            config1 = SessionConfig(
                user_id="alice",
                session_id="sess_001",
                workdir=workdir,
                model_id="claude-sonnet-4-6",
                anthropic_api_key="sk-test"
            )
            session1 = Session(config=config1)

            config2 = SessionConfig(
                user_id="bob",
                session_id="sess_002",
                workdir=workdir,
                model_id="claude-sonnet-4-6",
                anthropic_api_key="sk-test"
            )
            session2 = Session(config=config2)

            # 设置初始上下文
            SessionContext.set_session(session1)

            @with_session(session2)
            def some_function():
                s = SessionContext.get_required_session()
                return s.user_id

            result = some_function()

            # 函数内应该是 session2
            assert result == "bob"

            # 函数外应该恢复到 session1
            assert SessionContext.get_session().user_id == "alice"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
