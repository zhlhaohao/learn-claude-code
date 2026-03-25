#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SessionManager 模块单元测试

测试 SessionManager 类的基本功能和并发安全性。
"""

import sys
from pathlib import Path
import tempfile
import threading
import time

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from planify.core.session import Session, SessionConfig
from planify.core.session_manager import SessionManager


class TestSessionManager:
    """SessionManager 测试"""

    def setup_method(self):
        """每个测试前重置单例"""
        SessionManager.reset()

    def test_singleton(self):
        """测试单例模式"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)

            manager1 = SessionManager.get_instance(workdir)
            manager2 = SessionManager.get_instance()

            assert manager1 is manager2
            assert manager1.base_workdir == workdir

    def test_create_session(self):
        """测试创建会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manager = SessionManager.get_instance(workdir)

            user_config = {
                "model_id": "claude-sonnet-4-6",
                "anthropic_api_key": "sk-test"
            }

            session = manager.create_session("alice", user_config)

            assert session is not None
            assert session.user_id == "alice"
            assert session.status == "active"

    def test_get_session(self):
        """测试获取会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manager = SessionManager.get_instance(workdir)

            user_config = {
                "model_id": "claude-sonnet-4-6",
                "anthropic_api_key": "sk-test"
            }

            created = manager.create_session("alice", user_config, session_id="sess_001")
            retrieved = manager.get_session("alice", "sess_001")

            assert created is retrieved

    def test_get_nonexistent_session(self):
        """测试获取不存在的会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manager = SessionManager.get_instance(workdir)

            session = manager.get_session("alice", "nonexistent")
            assert session is None

    def test_close_session(self):
        """测试关闭会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manager = SessionManager.get_instance(workdir)

            user_config = {
                "model_id": "claude-sonnet-4-6",
                "anthropic_api_key": "sk-test"
            }

            manager.create_session("alice", user_config, session_id="sess_001")
            success = manager.close_session("alice", "sess_001")

            assert success is True
            assert manager.get_session("alice", "sess_001") is None

    def test_close_nonexistent_session(self):
        """测试关闭不存在的会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manager = SessionManager.get_instance(workdir)

            success = manager.close_session("alice", "nonexistent")
            assert success is False

    def test_list_user_sessions(self):
        """测试列出用户会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manager = SessionManager.get_instance(workdir)

            user_config = {
                "model_id": "claude-sonnet-4-6",
                "anthropic_api_key": "sk-test"
            }

            manager.create_session("alice", user_config, session_id="sess_001")
            manager.create_session("alice", user_config, session_id="sess_002")
            manager.create_session("bob", user_config, session_id="sess_001")

            alice_sessions = manager.list_user_sessions("alice")
            assert len(alice_sessions) == 2

            bob_sessions = manager.list_user_sessions("bob")
            assert len(bob_sessions) == 1

    def test_list_all_sessions(self):
        """测试列出所有会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manager = SessionManager.get_instance(workdir)

            user_config = {
                "model_id": "claude-sonnet-4-6",
                "anthropic_api_key": "sk-test"
            }

            manager.create_session("alice", user_config)
            manager.create_session("bob", user_config)

            all_sessions = manager.list_all_sessions()
            assert len(all_sessions) == 2

    def test_duplicate_session(self):
        """测试重复创建会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manager = SessionManager.get_instance(workdir)

            user_config = {
                "model_id": "claude-sonnet-4-6",
                "anthropic_api_key": "sk-test"
            }

            manager.create_session("alice", user_config, session_id="sess_001")

            with pytest.raises(ValueError, match="already exists"):
                manager.create_session("alice", user_config, session_id="sess_001")

    def test_config_overrides(self):
        """测试配置覆盖"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manager = SessionManager.get_instance(workdir)

            user_config = {
                "model_id": "claude-sonnet-4-6",
                "anthropic_api_key": "sk-test",
                "token_threshold": 50000
            }

            session = manager.create_session(
                "alice",
                user_config,
                token_threshold=100000  # 覆盖
            )

            assert session.token_threshold == 100000  # 覆盖值优先

    def test_len(self):
        """测试会话数量"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manager = SessionManager.get_instance(workdir)

            assert len(manager) == 0

            user_config = {
                "model_id": "claude-sonnet-4-6",
                "anthropic_api_key": "sk-test"
            }

            manager.create_session("alice", user_config)
            assert len(manager) == 1

            manager.create_session("bob", user_config)
            assert len(manager) == 2


class TestSessionManagerConcurrency:
    """SessionManager 并发测试"""

    def setup_method(self):
        """每个测试前重置单例"""
        SessionManager.reset()

    def test_concurrent_session_creation(self):
        """测试并发创建会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manager = SessionManager.get_instance(workdir)

            user_config = {
                "model_id": "claude-sonnet-4-6",
                "anthropic_api_key": "sk-test"
            }

            errors = []
            session_ids = []

            def create_session(i):
                try:
                    session_id = f"sess_{i:03d}"
                    session = manager.create_session(f"user_{i % 3}", user_config, session_id)
                    session_ids.append(session.session_id)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=create_session, args=(i,)) for i in range(50)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"创建会话时出错: {errors}"
            assert len(session_ids) == 50
            assert len(set(session_ids)) == 50  # 所有会话 ID 唯一

    def test_concurrent_session_access(self):
        """测试并发访问会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manager = SessionManager.get_instance(workdir)

            user_config = {
                "model_id": "claude-sonnet-4-6",
                "anthropic_api_key": "sk-test"
            }

            # 创建会话
            session = manager.create_session("alice", user_config, session_id="sess_concurrent")

            errors = []

            def append_messages(n):
                try:
                    for i in range(n):
                        session.append_message({"role": "user", "content": f"msg_{i}"})
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=append_messages, args=(100,)) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"追加消息时出错: {errors}"
            assert len(session.get_messages()) == 1000  # 10线程 × 100消息


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
