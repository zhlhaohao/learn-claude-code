"""日志配置

提供安全的文件日志记录，支持编码错误处理和会话 ID。
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class SafeFileHandler(logging.FileHandler):
    """
    安全的文件日志处理器

    继承自 logging.FileHandler，添加编码错误处理。
    当遇到无法编码的字符时，自动替换为 UTF-8 安全字符。
    """

    def emit(self, record):
        """发出日志记录，包含编码错误处理。"""
        try:
            super().emit(record)
        except (UnicodeDecodeError, UnicodeEncodeError):
            # 通过移除问题字符来处理编码错误
            record.msg = record.msg.encode('utf-8', errors='replace').decode('utf-8')
            super().emit(record)


class SessionAwareFormatter(logging.Formatter):
    """
    会话感知的日志格式化器

    自动检测当前会话上下文并在日志中包含 user_id 和 session_id。
    """

    def __init__(self, *args, include_session: bool = True, **kwargs):
        """
        初始化格式化器。

        Args:
            include_session: 是否包含会话信息
            **kwargs: Formatter 的其他参数
        """
        super().__init__(*args, **kwargs)
        self.include_session = include_session

    def format(self, record):
        """
        格式化日志记录。

        Args:
            record: 日志记录

        Returns:
            格式化后的字符串
        """
        # 添加会话信息到记录
        if self.include_session:
            try:
                from .context import SessionContext
                session = SessionContext.get_session()
                if session:
                    record.user_id = session.user_id
                    record.session_id = session.session_id
                else:
                    record.user_id = "-"
                    record.session_id = "-"
            except (ImportError, RuntimeError):
                record.user_id = "-"
                record.session_id = "-"
        else:
            record.user_id = "-"
            record.session_id = "-"

        return super().format(record)


def setup_logging(
    log_dir: Optional[Path] = None,
    log_level: int = logging.DEBUG,
    console_output: bool = False,
    include_session: bool = True,
) -> logging.Logger:
    """
    设置应用日志记录。

    Args:
        log_dir: 日志文件目录（默认为脚本目录下的 logs/）
        log_level: 日志级别（默认为 DEBUG）
        console_output: 是否输出到控制台（默认为 False）
        include_session: 是否在日志中包含会话信息（默认为 True）

    Returns:
        配置好的日志记录器实例
    """
    if log_dir is None:
        log_dir = Path(__file__).parent.parent / "logs"

    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"debug_{datetime.now().strftime('%Y%m%d')}.log"

    # 格式化器 - 包含会话信息
    fmt_with_session = '%(asctime)s | %(levelname)s | %(user_id)s:%(session_id)s | %(message)s'
    fmt_without_session = '%(asctime)s | %(levelname)s | %(message)s'

    formatter = SessionAwareFormatter(
        fmt_with_session if include_session else fmt_without_session,
        include_session=include_session
    )

    # 创建处理器列表（默认只有文件日志）
    handlers = []
    file_handler = SafeFileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    handlers.append(file_handler)

    # 仅在显式要求时添加控制台处理器
    if console_output and hasattr(sys, 'stdout'):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)  # 控制台只显示 INFO 级别以上
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)

    logging.basicConfig(
        level=log_level,
        handlers=handlers
    )

    logger = logging.getLogger(__name__)
    logger.info("=" * 50 + " Session Started " + "=" * 50)

    return logger


def get_logger_for_session(user_id: str, session_id: str, name: Optional[str] = None) -> logging.Logger:
    """
    获取带有会话信息的日志记录器。

    Args:
        user_id: 用户 ID
        session_id: 会话 ID
        name: 日志记录器名称（可选）

    Returns:
        日志记录器实例
    """
    if name is None:
        name = __name__

    logger = logging.getLogger(name)

    # 添加过滤器，为每条记录附加会话信息
    class SessionFilter(logging.Filter):
        def __init__(self, user_id, session_id):
            super().__init__()
            self.user_id = user_id
            self.session_id = session_id

        def filter(self, record):
            record.user_id = self.user_id
            record.session_id = self.session_id
            return True

    session_filter = SessionFilter(user_id, session_id)
    logger.addFilter(session_filter)

    return logger
