#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
应用初始化模块

负责初始化所有系统组件并管理全局应用状态。
"""

from typing import Any, Dict, List, Tuple, Optional

# 核心导入
from .core import get_config, setup_logging, init_clients

# 管理器导入
from .managers import TodoManager, TaskManager, BackgroundManager, TeammateManager

# 消息传递导入
from .messaging import MessageBus

# 技能导入
from .skills import SkillLoader

# 工具导入
from .tools import build_tool_registry
from .tools.basic import make_basic_tools, run_bash, run_read, run_write, run_edit

# 子代理导入
from .subagent import run_subagent


class AppState:
    """
    应用状态容器。

    存储所有全局应用组件，提供统一的访问接口。
    """

    def __init__(self):
        """初始化空状态。"""
        self.config: Optional[Dict] = None
        self.logger: Optional[Any] = None
        self.client: Optional[Any] = None
        self.zhipu_client: Optional[Any] = None
        self.todo_mgr: Optional[TodoManager] = None
        self.task_mgr: Optional[TaskManager] = None
        self.bg_mgr: Optional[BackgroundManager] = None
        self.bus: Optional[MessageBus] = None
        self.team: Optional[TeammateManager] = None
        self.skills: Optional[SkillLoader] = None
        self.tools: Optional[List[Dict]] = None
        self.tool_handlers: Optional[Dict[str, callable]] = None

    @property
    def workdir(self) -> Any:
        """获取工作目录。"""
        return self.config["workdir"] if self.config else None

    @property
    def model(self) -> Any:
        """获取模型名称。"""
        return self.config["model_id"] if self.config else None

    @property
    def token_threshold(self) -> Any:
        """获取 token 阈值。"""
        return self.config["token_threshold"] if self.config else None


# 全局应用状态实例
_state: Optional[AppState] = None


def get_state() -> AppState:
    """
    获取全局应用状态实例。

    Returns:
        AppState 实例

    Raises:
        RuntimeError: 如果应用尚未初始化
    """
    if _state is None:
        raise RuntimeError("应用尚未初始化。请先调用 initialize()。")
    return _state


def initialize() -> AppState:
    """
    初始化所有系统组件。

    此函数设置：
    1. 配置
    2. 日志
    3. API 客户端
    4. 管理器（Todo, Task, Background, Teammate）
    5. 消息总线
    6. 技能加载器
    7. 工具注册表

    Returns:
        AppState 实例
    """
    global _state

    if _state is not None:
        return _state

    state = AppState()

    # 1. 配置
    state.config = get_config()
    _validate_config(state.config)

    # 2. 日志（不输出到控制台，只记录到文件）
    state.logger = setup_logging(console_output=False)

    # 3. API 客户端
    state.client, state.zhipu_client = init_clients(
        state.config["anthropic_base_url"],
        state.config["anthropic_api_key"]
    )

    # 4. 管理器
    state.todo_mgr = TodoManager()
    state.task_mgr = TaskManager(state.config["tasks_dir"])
    state.bg_mgr = BackgroundManager(state.workdir)

    # 5. 消息总线
    state.bus = MessageBus(state.config["inbox_dir"])

    # 6. 技能加载器
    state.skills = SkillLoader(state.config["skills_dir"])

    # 7. 队友管理器（复杂，需要多个依赖）
    basic_tools = make_basic_tools(state.workdir)
    state.team = TeammateManager(
        bus=state.bus,
        task_mgr=state.task_mgr,
        team_dir=state.config["team_dir"],
        workdir=state.workdir,
        model=state.model,
        client=state.client,
        poll_interval=state.config["poll_interval"],
        idle_timeout=state.config["idle_timeout"],
        run_bash=run_bash,
        run_read=run_read,
        run_write=run_write,
        run_edit=run_edit,
    )

    # 8. 工具注册表
    state.tools, state.tool_handlers = build_tool_registry(
        workdir=state.workdir,
        zhipu_client=state.zhipu_client,
        todo_mgr=state.todo_mgr,
        task_mgr=state.task_mgr,
        bg_mgr=state.bg_mgr,
        bus=state.bus,
        team_mgr=state.team,
        skills_loader=state.skills,
        run_subagent=run_subagent,
        model=state.model,
        client=state.client,
        transcript_dir=state.config["transcript_dir"],
    )

    _state = state
    return state


def _validate_config(config: Dict[str, Any]) -> None:
    """
    验证必需的配置值。

    Args:
        config: 配置字典

    Raises:
        ValueError: 如果缺少必需的配置
    """
    if not config.get("model_id"):
        raise ValueError("MODEL_ID is required. Set it in .env file or environment.")
    if not config.get("anthropic_api_key"):
        raise ValueError("ANTHROPIC_API_KEY is required. Set it in .env file or environment.")


# =============================================================================
# 向后兼容：提供全局变量访问（用于向后兼容旧代码）
# =============================================================================
# 注意：这些仅用于向后兼容。新代码应使用 get_state()。

config = None
logger = None
client = None
zhipu_client = None
TODO = None
TASK_MGR = None
BG = None
BUS = None
TEAM = None
SKILLS = None
TOOLS = None
TOOL_HANDLERS = None
WORKDIR = None
MODEL = None
TOKEN_THRESHOLD = None


def _sync_globals() -> None:
    """将状态同步到全局变量（向后兼容）。"""
    global config, logger, client, zhipu_client
    global TODO, TASK_MGR, BG, BUS, TEAM, SKILLS
    global TOOLS, TOOL_HANDLERS, WORKDIR, MODEL, TOKEN_THRESHOLD

    if _state is None:
        return

    config = _state.config
    logger = _state.logger
    client = _state.client
    zhipu_client = _state.zhipu_client
    TODO = _state.todo_mgr
    TASK_MGR = _state.task_mgr
    BG = _state.bg_mgr
    BUS = _state.bus
    TEAM = _state.team
    SKILLS = _state.skills
    TOOLS = _state.tools
    TOOL_HANDLERS = _state.tool_handlers
    WORKDIR = _state.workdir
    MODEL = _state.model
    TOKEN_THRESHOLD = _state.token_threshold


# 重写 initialize 以同步全局变量
_original_initialize = initialize


def initialize() -> AppState:  # type: ignore
    """初始化应用并同步全局变量。"""
    result = _original_initialize()
    _sync_globals()
    return result
