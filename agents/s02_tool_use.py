#!/usr/bin/env python3
# Harness: tool dispatch -- expanding what the model can reach.
"""
s02_tool_use.py - Tools

The agent loop from s01 didn't change. We just added tools to the array
and a dispatch map to route calls.

    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch    |
    |  prompt  |      |       |      | {                |
    +----------+      +---+---+      |   bash: run_bash |
                          ^          |   read: run_read |
                          |          |   write: run_wr  |
                          +----------+   edit: run_edit |
                          tool_result| }                |
                                     +------------------+

Key insight: "The loop didn't change at all. I just added tools."
"""

import os
import subprocess
import logging
import json
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from zhipuai import ZhipuAI
from dotenv import load_dotenv

load_dotenv(override=True)

# 配置调试日志
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"debug_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)
logger.info("=" * 50 + " Session Started " + "=" * 50)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
zhipu_client = ZhipuAI(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = os.environ["MODEL_ID"]

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks. Act, don't explain."


def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(
            command,
            shell=True,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int = None) -> str:
    try:
        text = safe_path(path).read_text()
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def run_web_search(query: str) -> str:
    """使用智谱AI的内置web_search工具搜索网络信息"""
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
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {e}"


def run_weather(cities: list, date: str) -> str:
    """查询多个城市天气，返回纯净的JSON格式"""
    city_str = "、".join(cities) if isinstance(cities, list) else cities
    query = f"{city_str}{date}天气"

    try:
        response = zhipu_client.chat.completions.create(
            model="glm-4-flash",
            messages=[{
                "role": "user",
                "content": f"""搜索"{query}"，然后仅返回以下JSON数组格式，不要任何其他文字：
[{{"city": "城市名", "date": "日期", "weather": "天气状况", "temp_high": "最高温度", "temp_low": "最低温度", "humidity": "湿度", "wind": "风向风力"}}]"""
            }],
            tools=[{
                "type": "web_search",
                "web_search": {
                    "enable": "True",
                    "search_engine": "search_pro",
                    "search_result": "True",
                    "count": "5",
                    "search_recency_filter": "oneDay",
                    "content_size": "high",
                },
            }],
        )
        return response.choices[0].message.content
    except Exception as e:
        return f'{{"error": "{e}"}}'


# -- The dispatch map: {tool_name: handler} --
TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "web_search": lambda **kw: run_web_search(kw["query"]),
    "weather": lambda **kw: run_weather(kw["cities"], kw["date"]),
}

TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read file contents.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace exact text in file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the web for real-time information.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        },
    },
    {
        "name": "weather",
        "description": "Query weather for multiple cities. Returns JSON array format.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of city names"
                },
                "date": {"type": "string", "description": "Date (e.g. '今天', '明天', '2024-03-20')"}
            },
            "required": ["cities", "date"],
        },
    },
]


def agent_loop(messages: list):
    loop_count = 0
    while True:
        loop_count += 1
        logger.info(f"[LLM Call #{loop_count}] Input messages: {json.dumps(messages[-3:], ensure_ascii=False, default=str)}")

        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )

        logger.info(f"[LLM Call #{loop_count}] Stop reason: {response.stop_reason}")
        logger.debug(f"[LLM Call #{loop_count}] Response: {json.dumps([b.model_dump() if hasattr(b, 'model_dump') else str(b) for b in response.content], ensure_ascii=False)[:2000]}")

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                logger.info(f"[Tool Call] {block.name} | Input: {json.dumps(block.input, ensure_ascii=False)}")

                handler = TOOL_HANDLERS.get(block.name)
                output = (
                    handler(**block.input) if handler else f"Unknown tool: {block.name}"
                )

                logger.info(f"[Tool Result] {block.name} | Output: {output[:500]}")

                print(f"> {block.name}: {output[:200]}")
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": output}
                )
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms02 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()
