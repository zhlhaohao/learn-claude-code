"""MessageBus - 队友间消息传递 (s09)

基于文件的 JSONL 消息系统，用于队友之间的通信。

收件箱格式 (.team/inbox/name.jsonl)：
    {"type": "message", "from": "lead", "content": "...", "timestamp": 1234567890}
    {"type": "broadcast", "from": "alice", "content": "...", "timestamp": 1234567890}

消息类型：
- message: 普通消息
- broadcast: 广播消息
- shutdown_request: 关闭请求 (s10)
- shutdown_response: 关闭响应 (s10)
- plan_approval_response: 计划审批响应 (s10)

关键洞察："可以互相交谈的队友。"
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional


class MessageBus:
    """
    消息总线，管理队友间的消息传递
    """

    def __init__(self, inbox_dir: Path):
        """
        初始化收件箱目录

        Args:
            inbox_dir: 消息收件箱目录
        """
        inbox_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir = inbox_dir

    def send(
        self,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        extra: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        发送消息

        将消息追加到接收者的收件箱文件。

        Args:
            sender: 发送者名称
            to: 接收者名称
            content: 消息内容
            msg_type: 消息类型（默认 "message"）
            extra: 额外的元数据（可选）

        Returns:
            发送确认信息
        """
        msg = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time()
        }
        if extra:
            msg.update(extra)
        with open(self.inbox_dir / f"{to}.jsonl", "a") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> List[Dict[str, Any]]:
        """
        读取并清空收件箱

        读取后自动清空收件箱。

        Args:
            name: 收件人名称

        Returns:
            消息列表
        """
        path = self.inbox_dir / f"{name}.jsonl"
        if not path.exists():
            return []
        msgs = [json.loads(l) for l in path.read_text().strip().splitlines() if l]
        path.write_text("")  # 清空收件箱
        return msgs

    def broadcast(self, sender: str, content: str, names: List[str]) -> str:
        """
        广播消息给所有队友

        Args:
            sender: 发送者名称
            content: 消息内容
            names: 所有队友名称列表

        Returns:
            广播确认信息
        """
        count = 0
        for n in names:
            if n != sender:
                self.send(sender, n, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"
