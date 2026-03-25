"""配置管理

提供集中配置，支持环境变量和用户配置参数。

配置优先级（最高在前）：
1. user_config 参数传入
2. 环境变量
3. .env.local（dotenv 自动优先加载）
4. .env
5. 默认值

注意：.env.local 用于本地开发配置，不应提交到版本控制。
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv


def get_config(
    workdir: Optional[Path] = None,
    user_config: Optional[Dict[str, Any]] = None,
    load_env: bool = True
) -> Dict[str, Any]:
    """
    加载并返回应用配置。

    配置优先级（最高在前）：
    1. user_config 参数
    2. 环境变量
    3. .env 文件中的值
    4. 默认值

    Args:
        workdir: 工作目录（默认为当前目录）
        user_config: 用户配置字典，覆盖其他来源
        load_env: 是否加载 .env 文件（默认 True）

    Returns:
        包含所有设置的配置字典
    """
    if workdir is None:
        workdir = Path.cwd()

    # 加载 .env 文件（仅在 load_env=True 时）
    if load_env:
        load_dotenv(override=True)

    # 处理自定义 API 端点 - 移除默认的 auth token 以避免冲突
    if os.getenv("ANTHROPIC_BASE_URL"):
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

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

    # 基础配置
    config = {
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

    # 应用 user_config 覆盖
    if user_config:
        config.update(user_config)

    return config


def get_user_config_dict(
    model_id: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
    anthropic_base_url: Optional[str] = None,
    token_threshold: Optional[int] = None,
    poll_interval: Optional[int] = None,
    idle_timeout: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    构建用户配置字典。

    Args:
        model_id: 模型 ID
        anthropic_api_key: Anthropic API 密钥
        anthropic_base_url: 自定义 API 端点
        token_threshold: token 压缩阈值
        poll_interval: 轮询间隔
        idle_timeout: 空闲超时
        **kwargs: 其他配置项

    Returns:
        用户配置字典
    """
    config = {}

    if model_id is not None:
        config["model_id"] = model_id
    if anthropic_api_key is not None:
        config["anthropic_api_key"] = anthropic_api_key
    if anthropic_base_url is not None:
        config["anthropic_base_url"] = anthropic_base_url
    if token_threshold is not None:
        config["token_threshold"] = token_threshold
    if poll_interval is not None:
        config["poll_interval"] = poll_interval
    if idle_timeout is not None:
        config["idle_timeout"] = idle_timeout

    config.update(kwargs)
    return config


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
        raise ValueError("MODEL_ID is required. Set it in .env file or environment.")
    if not config.get("anthropic_api_key"):
        raise ValueError("ANTHROPIC_API_KEY is required. Set it in .env file or environment.")
    return True
