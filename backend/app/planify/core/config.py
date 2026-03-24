"""配置管理

提供集中配置，支持环境变量。

优先级（最高在前）：
1. 环境变量（override=True 时）
2. .env.local（dotenv 自动优先加载）
3. .env

注意：.env.local 用于本地开发配置，不应提交到版本控制。
"""

import os
from pathlib import Path
from typing import Dict, Any

from dotenv import load_dotenv


def get_config() -> Dict[str, Any]:
    """
    加载并返回应用配置。

    配置优先级（最高在前）：
    1. 环境变量
    2. .env 文件中的值
    3. 默认值

    Returns:
        包含所有设置的配置字典
    """
    # 加载 .env 文件，覆盖已存在的环境变量
    load_dotenv(override=True)

    # 处理自定义 API 端点 - 移除默认的 auth token 以避免冲突
    if os.getenv("ANTHROPIC_BASE_URL"):
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

    # 基本路径
    workdir = Path.cwd()

    # 目录路径
    team_dir = workdir / ".team"
    inbox_dir = team_dir / "inbox"
    tasks_dir = workdir / ".tasks"
    skills_dir = workdir / "skills"
    transcript_dir = workdir / ".transcripts"

    # 阈值和超时设置
    token_threshold = 100000  # 超过此阈值时触发自动压缩
    poll_interval = 5  # 空闲轮询间隔（秒）
    idle_timeout = 60  # 空闲超时时间（秒）

    # 有效的消息类型集合（s09/s10）
    valid_msg_types = {
        "message",               # 普通消息
        "broadcast",             # 广播消息
        "shutdown_request",      # 关闭请求
        "shutdown_response",     # 关闭响应
        "plan_approval_response" # 计划审批响应
    }

    return {
        # API 配置
        "model_id": os.environ.get("MODEL_ID"),
        "anthropic_base_url": os.getenv("ANTHROPIC_BASE_URL"),
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY"),

        # 路径配置
        "workdir": workdir,
        "team_dir": team_dir,
        "inbox_dir": inbox_dir,
        "tasks_dir": tasks_dir,
        "skills_dir": skills_dir,
        "transcript_dir": transcript_dir,

        # 阈值和超时配置
        "token_threshold": token_threshold,
        "poll_interval": poll_interval,
        "idle_timeout": idle_timeout,

        # 消息类型
        "valid_msg_types": valid_msg_types,
    }


def validate_config(config: Dict[str, Any]) -> bool:
    """
    验证必需的配置值。

    Args:
        config: 配置字典

    Returns:
        配置有效时返回 True

    Raises:
        ValueError: 如果缺少必需的配置
    """
    if not config.get("model_id"):
        raise ValueError("MODEL_ID 是必需的。请在 .env 文件或环境变量中设置。")
    return True
