"""API 客户端初始化

创建并返回 Anthropic 和 ZhipuAI 的已配置 API 客户端。
"""

from typing import Tuple

from anthropic import Anthropic
from zhipuai import ZhipuAI


def init_clients(base_url: str, api_key: str) -> Tuple[Anthropic, ZhipuAI]:
    """
    初始化 API 客户端。

    Args:
        base_url: 自定义 API 端点 URL（可选）
        api_key: 用于身份验证的 API 密钥

    Returns:
        (Anthropic 客户端, ZhipuAI 客户端) 元组
    """
    client = Anthropic(base_url=base_url)
    zhipu_client = ZhipuAI(api_key=api_key)

    return client, zhipu_client
