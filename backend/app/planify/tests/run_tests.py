#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单测试运行器

运行基础功能测试，验证多用户多会话架构。
"""

import sys
from pathlib import Path
import tempfile
import threading

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.session import Session, SessionConfig, generate_session_id
from core.session_manager import SessionManager
from core.context import SessionContext


def print_test(test_name):
    """打印测试名称"""
    print(f"\n{'=' * 50}")
    print(f"测试: {test_name}")
    print('=' * 50)


def assert_equal(actual, expected, message=""):
    """简单断言"""
    if actual != expected:
        raise AssertionError(f"{message}\n  期望: {expected}\n  实际: {actual}")


def assert_true(condition, message=""):
    """简单断言"""
    if not condition:
        raise AssertionError(f"{message}\n  条件为假")


def test_session_config():
    """测试 SessionConfig"""
    print_test("SessionConfig")

    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        config = SessionConfig(
            user_id="alice",
            session_id="sess_001",
            workdir=workdir,
            model_id="claude-sonnet-4-6",
            anthropic_api_key="sk-test"
        )

        assert_equal(config.user_id, "alice", "user_id 不匹配")
        assert_equal(config.session_id, "sess_001", "session_id 不匹配")
        assert_equal(config.model_id, "claude-sonnet-4-6", "model_id 不匹配")

        print("  用户 ID: alice")
        print("  会话 ID: sess_001")
        print("  模型 ID: claude-sonnet-4-6")
        print("  团队目录:", config.team_dir)
        print("  任务目录:", config.tasks_dir)
        print("  转录目录:", config.transcript_dir)
        print("  收件箱目录:", config.inbox_dir)

    print("✓ SessionConfig 测试通过")


def test_session():
    """测试 Session"""
    print_test("Session")

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

        assert_equal(session.status, "active", "状态应为 active")
        assert_equal(session.user_id, "alice", "user_id 不匹配")

        # 测试消息操作
        session.append_message({"role": "user", "content": "hello"})
        session.append_message({"role": "assistant", "content": "hi"})

        messages = session.get_messages()
        assert_equal(len(messages), 2, "消息数量应为 2")
        assert_equal(messages[0]["content"], "hello", "第一条消息不匹配")

        print(f"  状态: {session.status}")
        print(f"  用户: {session.user_id}")
        print(f"  消息数: {len(messages)}")

    print("✓ Session 测试通过")


def test_session_manager():
    """测试 SessionManager"""
    print_test("SessionManager")

    # 重置单例
    SessionManager.reset()

    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        manager = SessionManager.get_instance(workdir)

        user_config = {
            "model_id": "claude-sonnet-4-6",
            "anthropic_api_key": "sk-test"
        }

        # 创建会话
        session1 = manager.create_session("alice", user_config, session_id="sess_001")
        session2 = manager.create_session("bob", user_config, session_id="sess_001")

        # 测试获取
        retrieved = manager.get_session("alice", "sess_001")
        assert_true(retrieved is session1, "应返回相同会话")

        # 测试列出
        alice_sessions = manager.list_user_sessions("alice")
        assert_equal(len(alice_sessions), 1, "应有 1 个 alice 会话")

        all_sessions = manager.list_all_sessions()
        assert_equal(len(all_sessions), 2, "应有 2 个总会话")

        # 测试关闭
        success = manager.close_session("alice", "sess_001")
        assert_true(success, "应成功关闭")

        closed = manager.get_session("alice", "sess_001")
        assert_true(closed is None, "会话应已被删除")

        print(f"  总会话数: {len(all_sessions)}")
        print(f"  Alice 会话数: {len(alice_sessions)}")
        print(f"  Bob 会话数: {len(manager.list_user_sessions('bob'))}")

    print("✓ SessionManager 测试通过")


def test_session_context():
    """测试 SessionContext"""
    print_test("SessionContext")

    SessionContext.clear()

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

        # 测试设置和获取
        SessionContext.set_session(session)
        retrieved = SessionContext.get_session()
        assert_true(retrieved is session, "应返回相同会话")

        # 测试清除
        SessionContext.clear()
        assert_true(SessionContext.get_session() is None, "应返回 None")

        print("  设置会话: ✓")
        print("  获取会话: ✓")
        print("  清除上下文: ✓")

    print("✓ SessionContext 测试通过")


def test_thread_safety():
    """测试线程安全"""
    print_test("线程安全")

    SessionManager.reset()

    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        manager = SessionManager.get_instance(workdir)

        user_config = {
            "model_id": "claude-sonnet-4-6",
            "anthropic_api_key": "sk-test"
        }

        # 创建一个会话
        session = manager.create_session("alice", user_config, session_id="sess_concurrent")

        errors = []
        thread_count = 10
        messages_per_thread = 50

        def append_messages(n):
            try:
                for i in range(n):
                    session.append_message({"role": "user", "content": f"msg_{i}"})
            except Exception as e:
                errors.append(e)

        # 启动多个线程
        threads = [
            threading.Thread(target=append_messages, args=(messages_per_thread,))
            for _ in range(thread_count)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 验证结果
        assert_true(len(errors) == 0, f"追加消息时出错: {errors}")
        message_count = len(session.get_messages())
        expected = thread_count * messages_per_thread

        assert_equal(message_count, expected,
                   f"消息数量应为 {expected}, 实际为 {message_count}")

        print(f"  线程数: {thread_count}")
        print(f"  每线程消息数: {messages_per_thread}")
        print(f"  总消息数: {message_count}")

    print("✓ 线程安全测试通过")


def test_session_isolation():
    """测试会话隔离"""
    print_test("会话隔离")

    SessionManager.reset()

    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        manager = SessionManager.get_instance(workdir)

        user_config = {
            "model_id": "claude-sonnet-4-6",
            "anthropic_api_key": "sk-test"
        }

        # 创建两个会话
        session1 = manager.create_session("alice", user_config, session_id="sess_001")
        session2 = manager.create_session("bob", user_config, session_id="sess_001")

        # 分别添加消息
        session1.append_message({"role": "user", "content": "alice message"})
        session2.append_message({"role": "user", "content": "bob message"})

        # 验证隔离
        msg1 = session1.get_messages()[0]["content"]
        msg2 = session2.get_messages()[0]["content"]

        assert_equal(msg1, "alice message", "Alice 消息不匹配")
        assert_equal(msg2, "bob message", "Bob 消息不匹配")

        # 验证目录隔离
        assert_equal(session1.config.transcript_dir.parent.parent.name, "alice",
                   "Alice 转录目录应为 .sessions/alice")
        assert_equal(session2.config.transcript_dir.parent.parent.name, "bob",
                   "Bob 转录目录应为 .sessions/bob")

        print(f"  Alice 消息: {msg1}")
        print(f"  Bob 消息: {msg2}")
        print(f"  Alice 转录目录: {session1.config.transcript_dir.parent.name}")
        print(f"  Bob 转录目录: {session2.config.transcript_dir.parent.name}")

    print("✓ 会话隔离测试通过")


def main():
    """运行所有测试"""
    print("\n" + "=" * 50)
    print("Planify 多用户多会话架构测试")
    print("=" * 50)

    tests = [
        test_session_config,
        test_session,
        test_session_manager,
        test_session_context,
        test_thread_safety,
        test_session_isolation,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test.__name__, e))
            print(f"\n✗ {test.__name__} 测试失败")
            print(f"  错误: {e}")

    # 汇总
    print("\n" + "=" * 50)
    print("测试汇总")
    print("=" * 50)
    print(f"  通过: {passed}/{len(tests)}")
    print(f"  失败: {failed}/{len(tests)}")

    if errors:
        print("\n失败详情:")
        for name, error in errors:
            print(f"  - {name}: {error}")

    if failed == 0:
        print("\n✓ 所有测试通过！")
        return 0
    else:
        print(f"\n✗ {failed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
