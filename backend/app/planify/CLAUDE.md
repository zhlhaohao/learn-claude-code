# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Planify 是一个基于 Claude API 的多代理 LLM 系统，提供交互式 REPL 命令行界面。系统采用模块化架构，包含主代理循环、子代理委派、持久化任务管理、队友协作、技能加载和上下文压缩等核心功能。

**多用户多会话架构**：系统现已支持多用户并发访问，每个用户可以有多个独立会话，会话间数据和状态完全隔离，适合作为 Web 应用后端。

## 运行命令

### 单用户 CLI（推荐）

使用单用户 CLI 脚本，在任何工作目录中启动 Planify：

```bash
# cd 到你的工作目录
cd /path/to/your/project

# 执行 CLI 脚本（Bash）
bash /path/to/planify/bin/planify

# 或直接运行 Python 入口
python /path/to/planify/cli.py
```

单用户模式下，当前工作目录直接作为会话数据目录（不需要 `.sessions/` 子目录），适合个人使用。

### 多用户 REPL

```bash
python -m backend.app.planify.main
# 或
python backend/app/planify/main.py
```

### REPL 命令
**多用户多会话命令：**
- `/user [id]` - 切换用户
- `/session [id]` - 切换会话
- `/new-session [id]` - 创建新会话
- `/sessions` - 列出当前用户的所有会话
- `/close-session` - 关闭当前会话

**原有命令：**
- `/compact` - 手动压缩对话上下文
- `/tasks` - 列出所有任务
- `/team` - 列出所有队友及其状态
- `/inbox` - 读取 lead 收件箱中的消息
- `/exit` - 退出 REPL

## 环境配置

复制 `.env.example` 到 `.env` 并配置必需的环境变量：

```bash
# 必需：模型 ID
MODEL_ID=your-model-id

# 可选：自定义 API 端点
# ANTHROPIC_BASE_URL=https://api.anthropic.com

# 可选：API 密钥
# ANTHROPIC_API_KEY=your-api-key
```

配置优先级：user_config 参数 > 环境变量 > .env.local > .env > 默认值

## 项目架构

### 核心模块

```
planify/
├── main.py              # REPL 入口，交互式命令行
├── bootstrap.py         # SessionManager 初始化，应用状态管理
├── agent/runner.py      # 核心代理循环 (s01)
├── subagent/runner.py   # 临时子代理运行器 (s04)
├── context/compact.py   # 上下文压缩机制 (s06)
├── messaging/message_bus.py  # 消息传递系统 (s09)
├── managers/            # 各种管理器（线程安全）
│   ├── todo_manager.py   # 内存待办列表 (s03)
│   ├── task_manager.py   # 持久化任务管理 (s07)
│   ├── background_manager.py  # 后台任务管理 (s08)
│   └── teammate_manager.py  # 队友管理 (s09/s11)
├── tools/registry.py    # 工具注册中心（支持 Session）
├── skills/skill_loader.py  # 技能加载器 (s05)
├── tests/               # 单元测试
│   ├── test_session.py
│   ├── test_session_manager.py
│   ├── test_context.py
│   └── run_tests.py
└── core/
    ├── session.py          # Session 和 SessionConfig 类
    ├── session_manager.py  # SessionManager 单例
    ├── context.py         # SessionContext 线程本地上下文
    ├── config.py          # 配置管理（支持 user_config）
    ├── encoding.py        # UTF-8 编码设置
    └── logging_config.py  # 日志配置（含会话信息）
```

### 多用户多会话架构

**核心组件：**

1. **SessionConfig** - 会话配置类
   - 包含 user_id, session_id, workdir, model_id 等
   - 提供隔离目录路径属性：team_dir, tasks_dir, transcript_dir

2. **Session** - 会话状态容器
   - 封装所有会话相关组件（client, managers, tools 等）
   - 线程安全的消息历史管理（_messages_lock）
   - 支持 append_message(), get_messages(), replace_messages_in_place()

3. **SessionManager** - 会话管理器（单例）
   - create_session(user_id, user_config, session_id) - 创建会话
   - get_session(user_id, session_id) - 获取会话
   - close_session(user_id, session_id) - 关闭会话
   - list_user_sessions(user_id) - 列出用户会话
   - initialize_session_components(session) - 初始化会话组件

4. **SessionContext** - 线程本地会话上下文
   - set_session(session) - 设置当前线程会话
   - get_session() - 获取当前线程会话
   - get_required_session() - 获取必需会话（不存在则抛异常）
   - clear() - 清除当前会话
   - with_session(session) - 上下文管理器

### 关键架构概念

**代理循环 (agent/runner.py)**：系统的核心是 `while stop_reason == 'tool_use'` 循环。每次迭代执行：微压缩 → 检查上下文阈值 → 处理后台通知 → 检查收件箱 → LLM 调用 → 工具执行。

**子代理 vs 队友**：
- **子代理 (subagent)**：临时执行特定任务后返回摘要并销毁。`Explore` 类型只读（bash, read），`general-purpose` 类型可读写。
- **队友 (teammate)**：持久化的独立代理，在独立线程中运行，有工作阶段和空闲阶段，通过消息总线通信。

**会话隔离**：
- 每个用户有自己的数据目录：`.sessions/{user_id}/`
- 每个会话有独立的对话记录：`.sessions/{user_id}/.transcripts/{session_id}/`
- 消息总线、任务管理、队友配置都按会话隔离
- 使用线程锁保证并发安全

**TodoManager vs TaskManager**：
- **TodoManager**：内存中的短期待办列表，用于当前会话跟踪。
- **TaskManager**：文件持久化的长期任务系统，支持依赖关系（blockedBy/blocks），存储在 `.sessions/{user_id}/.tasks/` 目录。

**上下文压缩 (context/compact.py)**：
- **微压缩**：每次循环自动清理旧的 tool_result，只保留最近 3 个。
- **自动压缩**：当估算 token 数超过阈值（默认 100000）时，使用 LLM 生成摘要，保存完整对话到 `.sessions/{user_id}/.transcripts/{session_id}/` 目录。

**消息总线 (messaging/message_bus.py)**：基于 JSONL 文件的消息传递系统。收件箱位于 `.sessions/{user_id}/.team/inbox/` 目录。支持的消息类型：`message`、`broadcast`、`shutdown_request`、`shutdown_response`、`plan_approval_response`。使用文件锁保证原子操作。

**技能系统 (skills/skill_loader.py)**：从 `skills/` 目录加载专业技能。技能文件格式为 `skills/my_skill/SKILL.md`，包含 YAML 前言（name, description）和 Markdown 正文。技能目录为全局共享。

### 工具系统

所有工具通过 `tools/registry.py` 中的 `build_tool_registry(session: Session)` 统一注册。主要工具分类：

1. **基础工具**：bash, read_file, write_file, edit_file
2. **网络工具**：web_search（使用 ZhipuAI）、weather
3. **任务工具**：TodoWrite, task（子代理委派）、load_skill
4. **文件任务系统**：TaskCreate, TaskGet, TaskUpdate, TaskList
5. **团队协作工具**：spawn_teammate, shutdown_teammate, send_message, broadcast
6. **协议工具**：request_approval, respond_approval
7. **后台任务**：background_run, check_background
8. **压缩工具**：compress

### 工作目录结构

运行时创建的目录：
```
.sessions/              # 多用户会话数据目录
├── alice/              # 用户 alice 的所有会话数据
│   ├── .team/          # 团队配置和收件箱
│   │   ├── config.json
│   │   └── inbox/
│   ├── .tasks/         # 任务文件存储
│   │   ├── task_001.json
│   │   └── task_002.json
│   └── .transcripts/   # 对话记录
│       ├── sess_001/
│       └── sess_002/
└── bob/               # 用户 bob 的数据
    └── ...

skills/                 # 技能文件（全局共享）
logs/                   # 日志文件
```

### 应用状态管理

`bootstrap.py` 提供多用户会话管理接口：

- `initialize(base_workdir)` - 初始化 SessionManager
- `create_session(user_id, user_config, session_id)` - 创建会话
- `get_session(user_id, session_id)` - 获取会话
- `close_session(user_id, session_id)` - 关闭会话
- `list_user_sessions(user_id)` - 列出用户会话
- `list_all_sessions()` - 列出所有会话

详细使用示例请参考：[examples.md](./examples.md)

### 线程安全

所有管理器都已添加线程安全保护：
- **BackgroundManager**：`_tasks_lock` 保护 tasks 字典
- **MessageBus**：文件级锁保证 read_inbox 原子操作
- **TeammateManager**：`_config_lock` 保护配置读写
- **Session**：`_messages_lock` 保护消息历史

## 使用示例

详细代码示例请参考：[examples.md](./examples.md)

- [Session 基础使用](./examples.md#session-基础使用)
- [FastAPI 集成](./examples.md#fastapi-集成)

## 编码规范

- **不可变性**：始终创建新对象，避免就地修改现有对象（配置类除外）
- **UTF-8 编码**：由于中文支持需求，`core/encoding.py` 中的 `setup_encoding()` 和 `apply_safe_stdio()` 必须在任何其他导入之前执行
- **错误处理**：在系统边界（用户输入、API 响应、文件内容）进行验证
- **文件组织**：小文件优先，高内聚低耦合，每个模块专注于单一职责
- **线程安全**：多线程环境中的共享数据必须使用锁保护
