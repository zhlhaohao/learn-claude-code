#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Session 模块单元测试

测试 Session 和 SessionConfig 类的基本功能。
"""

import sys
from pathlib import Path
import tempfile
import shutil

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from planify.core.session import Session, SessionConfig, generate_session_id


class TestSessionConfig:
    """SessionConfig 测试"""

    def test_create_config(self):
        """测试创建配置"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            config = SessionConfig(
                user_id="alice",
                session_id="sess_001",
                workdir=workdir,
                model_id="claude-sonnet-4-6",
                anthropic_api_key="sk-test"
            )

            assert config.user_id == "alice"
            assert config.session_id == "sess_001"
            assert config.workdir == workdir
            assert config.model_id == "claude-sonnet-4-6"
            assert config.anthropic_api_key == "sk-test"

    def test_directory_paths(self):
        """测试目录路径"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            config = SessionConfig(
                user_id="alice",
                session_id="sess_001",
                workdir=workdir,
                model_id="claude-sonnet-4-6",
                anthropic_api_key="sk-test"
            )

            expected_team = workdir / ".sessions/alice/.team"
            expected_tasks = workdir / ".sessions/alice/.tasks"
            expected_transcript = workdir / ".sessions/alice/.transcripts/sess_001"
            expected_inbox = expected_team / "inbox"
            expected_skills = workdir / "skills"
            expected_logs = workdir / "logs"

            assert config.team_dir == expected_team
            assert config.tasks_dir == expected_tasks
            assert config.transcript_dir == expected_transcript
            assert config.inbox_dir == expected_inbox
            assert config.skills_dir == expected_skills
            assert config.logs_dir == expected_logs


class TestSession:
    """Session 测试"""

    def test_create_session(self):
        """测试创建会话"""
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

            assert session.config is config
            assert session.status == "active"
            assert session.user_id == "alice"
            assert session.session_id == "sess_001"
            assert session.model == "claude-sonnet-4-6"

    def test_message_operations(self):
        """测试消息操作"""
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

            # 测试追加消息
            session.append_message({"role": "user", "content": "hello"})
            session.append_message({"role": "assistant", "content": "hi"})

            # 测试获取消息
            messages = session.get_messages()
            assert len(messages) == 2
            assert messages[0]["content"] == "hello"
            assert messages[1]["content"] == "hi"

            # 测试获取返回副本
            messages[0]["content"] = "modified"
            messages2 = session.get_messages()
            assert messages2[0]["content"] == "hello"  # 原始未被修改

    def test_set_messages(self):
        """测试设置消息"""
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

            new_messages = [{"role": "user", "content": "new"}]
            session.set_messages(new_messages)

            messages = session.get_messages()
            assert len(messages) == 1
            assert messages[0]["content"] == "new"

    def test_replace_messages_in_place(self):
        """测试原地替换消息"""
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

            # 原始消息
            original = [{"role": "user", "content": "original"}]
            session.set_messages(original)

            # 获取引用
            messages = session.get_messages()

            # 原地替换
            new_messages = [{"role": "user", "content": "new"}]
            session.replace_messages_in_place(new_messages)

            # 验证替换成功
            assert len(session.get_messages()) == 1
            assert session.get_messages()[0]["content"] == "new"

    def test_ensure_dirs(self):
        """测试创建目录"""
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

            session.ensure_dirs()

            assert config.team_dir.exists()
            assert config.tasks_dir.exists()
            assert config.transcript_dir.exists()
            assert config.inbox_dir.exists()
            assert config.skills_dir.exists()
            assert config.logs_dir.exists()


class TestGenerateSessionId:
    """generate_session_id 测试"""

    def test_format(self):
        """测试 ID 格式"""
        for _ in range(10):
            session_id = generate_session_id()
            assert session_id.startswith("sess_")
            assert len(session_id) == len("sess_") + 8  # sess_ + 8位hex
            assert session_id[5:].isalnum()

    def test_uniqueness(self):
        """测试唯一性"""
        ids = set()
        for _ in range(100):
            session_id = generate_session_id()
            assert session_id not in ids
            ids.add(session_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
