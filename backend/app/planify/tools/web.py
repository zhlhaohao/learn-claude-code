"""网络搜索和天气工具

使用 ZhipuAI 的内置 web_search 工具获取实时网络信息。
"""

import sys
from typing import List, Union, Dict, Tuple
from zhipuai import ZhipuAI


def run_web_search(query: str, zhipu_client: ZhipuAI) -> str:
    """
    使用 ZhipuAI 的内置 web_search 工具搜索网络信息

    通过 Zhipu GLM-4-Flash 模型的 web_search 工具获取实时网络信息。

    Args:
        query: 搜索查询字符串
        zhipu_client: ZhipuAI 客户端实例

    Returns:
        搜索结果内容
    """
    try:
        response = zhipu_client.chat.completions.create(
            model="glm-4-flash",
            messages=[{"role": "user", "content": query}],
            tools=[
                {
                    "type": "web_search",
                    "web_search": {
                        "enable": "True",
                        "search_engine": "search_pro",
                        "search_result": "True",
                        "count": "5",
                        "search_recency_filter": "noLimit",
                        "content_size": "high",
                    },
                }
            ],
        )
        content = response.choices[0].message.content
        # 在 Windows 上确保 UTF-8 编码
        if sys.platform == 'win32':
            # 如果内容是字节，解码为 UTF-8
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='replace')
            # 如果内容是字符串，规范化编码
            else:
                content = content.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
        return content
    except Exception as e:
        return f"Error: {e}"


def run_weather(cities: Union[str, List[str]], date: str, zhipu_client: ZhipuAI) -> str:
    """
    查询多个城市的天气

    使用 ZhipuAI 的 web_search 工具查询天气，返回结构化的 JSON 格式。

    Args:
        cities: 城市名称（字符串或列表）
        date: 日期（例如：'今天'、'明天'、'2024-03-20'）
        zhipu_client: ZhipuAI 客户端实例

    Returns:
        JSON 数组格式的天气信息
    """
    # 统一处理 cities 参数
    if isinstance(cities, str):
        cities = [cities]
    city_str = "、".join(cities)
    query = f"{city_str}{date}天气"

    try:
        response = zhipu_client.chat.completions.create(
            model="glm-4-flash",
            messages=[
                {
                    "role": "user",
                    "content": f"""搜索"{query}"，然后仅返回以下JSON数组格式，不要任何其他文字：

要求：
1. 必须包含完整的日期信息（如 "2024-03-24" 而不是 "今天"）
2. 如果是预报天气，使用 forecast_date 字段表示预报日期
3. 日期必须是标准的 YYYY-MM-DD 格式

返回格式：
[{{"city": "城市名", "date": "2024-03-24", "weather": "天气状况", "temp_high": "最高温度", "temp_low": "最低温度", "humidity": "湿度", "wind": "风向风力"}}]
"""
                }
            ],
            tools=[
                {
                    "type": "web_search",
                    "web_search": {
                        "enable": "True",
                        "search_engine": "search_pro",
                        "search_result": "True",
                        "count": "5",
                        "search_recency_filter": "oneDay",
                        "content_size": "high",
                    },
                }
            ],
        )
        content = response.choices[0].message.content
        # 在 Windows 上确保 UTF-8 编码
        if sys.platform == 'win32':
            # 如果内容是字节，解码为 UTF-8
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='replace')
            # 如果内容是字符串，规范化编码
            else:
                content = content.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
        return content
    except Exception as e:
        return f'{{"error": "{e}"}}'


def make_web_tools(zhipu_client: ZhipuAI) -> Tuple[list, dict]:
    """
    创建网络工具定义和处理器字典

    Args:
        zhipu_client: ZhipuAI 客户端实例

    Returns:
        (工具定义列表, 处理器字典) 的元组
    """
    tools = [
        {
            "name": "web_search",
            "description": "搜索网络信息",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询内容"
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "weather",
            "description": "查询城市天气信息",
            "input_schema": {
                "type": "object",
                "properties": {
                    "cities": {
                        "type": "string",
                        "description": "城市名称，多个城市用、分隔"
                    },
                    "date": {
                        "type": "string",
                        "description": "日期，如今天、明天"
                    }
                },
                "required": ["cities", "date"]
            }
        },
    ]

    handlers = {
        "web_search": lambda **kw: run_web_search(kw["query"], zhipu_client),
        "weather": lambda **kw: run_weather(kw["cities"], kw["date"], zhipu_client),
    }

    return tools, handlers
