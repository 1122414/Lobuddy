# Lobuddy

🌙 **Lobuddy** - 主动陪伴型桌面 Agent (Proactive Companion Agent)

基于 [nanobot](https://github.com/1122414/nanobot) 与 PySide6 打造的本地桌面伙伴。它既能聊天、理解图片和执行复杂任务，也能在用户授权范围内观察工作节奏、操作电脑，并通过可审计的提案机制逐步沉淀新能力。

## ✨ 特性

- 🌙 **陪伴式桌宠** - 原创月亮猫、可过期状态 Check-in、专注陪伴和低打扰主动关怀
- 🐾 **Codex 宠物联动** - 自动读取 Codex Desktop 内置伙伴，也可浏览 codex-pets.net
  社区或使用本机自定义宠物，完整同步 9 种标准动作
- 👀 **可信状态理解** - 活动观察只描述工作节奏；情绪与陪伴需要只接受用户主动选择，不做伪情绪识别
- 🤖 **复杂任务 Agent** - 基于 nanobot 的任务规划、原子串行调度与工具调用；Task Run 持久化工作阶段、显式依赖、关键路径、步骤耗时、模型用量证据和重试谱系
- 🖱️ **受控 Computer Use** - 计划、观察、授权、执行、校验、失败恢复全链路，敏感动作需要人工确认
- 🖼️ **多模态理解** - 支持图片与主动屏幕选区提问；只共享框选区域，并在任务结束后删除
- 🧬 **可审计能力进化** - 脱敏候选需通过内容哈希绑定的隔离包评测与人工审批，展示权限画像，可禁用和恢复
- 🧠 **可治理关系记忆** - 解释来源与用途，支持逐次召回反馈、确认、校正、停用、恢复、永久遗忘、关系时间线和安全迁移
- 🤝 **有依据的相处节奏** - 汇总主动留下的偏好、限时状态、关怀边界与任务成长证据，不生成关系分数或伪情绪画像
- 🔎 **有依据的记忆召回** - 按当前请求相关性、总预算、作用域与有效期选择记忆；任务栏显示不含正文的调用证据，并可由用户反馈“有帮助 / 不相关 / 内容不对”
- 📈 **成长系统** - 完成任务获得经验，驱动等级、形态、个性与能力解锁；个性成长有版本、可解释、可恢复
- 🛡️ **安全治理** - 路径、命令、URL、工具预算、日志脱敏、密钥加密和高风险动作审批
- ⚡ **可靠运行** - 健康检查、后台维护、无丢任务队列、工作记录、退出/重启安全暂停、显式重试和超时保护

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Conda 环境（推荐）
- OpenAI 兼容的 API Key

### 安装

1. **克隆仓库**（包含 nanobot submodule）

```bash
git clone --recursive https://github.com/1122414/Lobuddy.git
cd Lobuddy
```

2. **创建并激活 Conda 环境**

```bash
conda create -n lobuddy python=3.11
conda activate lobuddy
```

3. **安装依赖**

```bash
# 安装 nanobot（本地 editable 模式）
pip install -e lib/nanobot

# 安装 Lobuddy
pip install -e .
```

4. **配置环境变量**

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 API Key
```

`.env` 文件示例：

```env
# 必需：API Key（支持 OpenAI、OpenRouter 等兼容 OpenAI 协议的提供商）
LLM_API_KEY=sk-your-api-key-here

# 可选：API 基础 URL（默认使用 OpenAI）
LLM_BASE_URL=https://api.openai.com/v1

# 可选：模型名称
LLM_MODEL=gpt-4o-mini

# 可选：宠物名称
PET_NAME=Lobuddy
```

5. **运行**

```bash
# 启动应用
python -m app.main

# 或运行健康检查
lobuddy-health
```

## 📁 项目结构

```
Lobuddy/
├── app/                    # 应用层
│   ├── main.py            # 应用入口
│   ├── bootstrap.py       # 启动引导
│   ├── config.py          # 配置管理
│   └── health.py          # 健康检查
├── core/                   # 核心业务层
│   ├── agent/             # nanobot 适配器
│   ├── models/            # 数据模型
│   ├── tasks/             # 队列、Task Run、时长预测与安全重试
│   ├── game/              # 成长系统
│   ├── companion/         # 主动观察与陪伴策略
│   ├── computer_use/      # 受控电脑操作运行时
│   ├── screen_region/     # 用户主动框选的临时视觉上下文
│   ├── memory/            # 结构化记忆与用户画像
│   ├── relationship/      # 可解释的长期相处节奏
│   ├── skills/            # 技能生命周期与进化提案
│   ├── storage/           # 持久化层
│   └── services/          # 服务层
├── ui/                     # 陪伴桌宠与命令中心 UI
│   ├── pet_window.py
│   ├── task_panel.py
│   └── assets/
├── lib/                    # 第三方依赖
│   └── nanobot/           # git submodule
├── workspace/             # nanobot 工作目录
├── data/                  # 数据存储
├── logs/                  # 日志文件
├── tests/                 # 测试
├── pyproject.toml         # 项目配置
└── README.md
```

## 🎯 当前能力状态

- [x] 工程骨架、nanobot 边界、SQLite Repository 与异步任务编排
- [x] 桌宠、对话命令中心、快捷操作、任务卡、设置中心与能力实验室
- [x] Task Run 原子串行调度、无丢任务安全暂停、阶段依赖图、关键路径、工具级真实耗时、同模型历史 Token 预算、显式重试谱系与工作记录
- [x] Codex 本机宠物发现、codex-pets.net 在线浏览、安全领养、9 状态动作联动与即时切换
- [x] 主动观察、可撤回状态 Check-in、专注陪伴、失败支持与打扰频率治理
- [x] 受控 Computer Use、人工审批、执行追踪、快照与失败恢复
- [x] 多模态图片入口、临时屏幕选区、视觉模型路由与输入安全校验
- [x] 结构化记忆、用户画像、逐次召回反馈、隐私模式、可解释校正、永久遗忘、关系时间线与待确认迁移包
- [x] 用户主动记忆、相处节奏、关怀边界撤销与可恢复的伙伴个性成长版本
- [x] 技能候选提取、脱敏、隔离包评测、权限画像、不可绕过的人工批准、禁用与恢复
- [x] 经验等级、进化、个性与能力解锁
- [x] 运行时维护、健康检查、敏感数据过滤与可靠退出
- [x] 1149 项自动化测试通过

完整能力边界、质量评分和后续升级路线见
[`docs/PROJECT_AUDIT_2026-07-19.md`](docs/PROJECT_AUDIT_2026-07-19.md)。

## 🆕 最近更新

### 子 Agent 多模态图片分析

Lobuddy 现在支持通过独立的子 Agent 对图片进行视觉分析：

- **工具入口**：`analyze_image` - Agent 可在需要时自动调用
- **独立进程**：图片分析在单独的子进程中运行，避免阻塞主程序 UI
- **自动压缩**：当图片超过 5MB 时，会自动通过 Pillow 压缩/降采样，减少 API 调用成本
- **配置项**：通过 `LLM_MULTIMODAL_MODEL` 设置多模态模型（如 `qwen3.5-omni-plus`），为空则禁用该功能
- **测试覆盖**：包含端到端集成测试（`tests/test_image_analysis_integration.py`）与工具层单元测试（`tests/test_analyze_image_tool.py`）

### 应用退出可靠性修复

修复了托盘右键点击 "Exit" 后应用无法正常退出的问题：

- **彻底清理**：退出时取消所有未完成的 asyncio 任务、清空任务队列、停止热键监听线程
- **窗口关闭**：`pet_window` 支持 `force_close()` 绕过拦截，`task_panel` 正常关闭
- **超时保护**：若 3 秒内异步线程未结束，则强制终止；最终 4 秒兜底 `os._exit(0)` 确保进程一定退出
- **回归测试**：新增 `tests/test_shutdown_regression.py` 与 `tests/test_exit_wiring.py` 防止问题复发

### 依赖清理说明

如果你之前通过 `pip install -e .` 安装过 Lobuddy，可能会误装 PyPI 上的同名 `nanobot` 包（与 `lib/nanobot` 子模块无关）。请执行以下命令清理：

```bash
pip uninstall nanobot
pip install -e lib/nanobot
pip install -e .
```

## 🧪 测试

如需运行测试，请先安装开发依赖：

```bash
pip install -e ".[dev]"
```

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_nanobot_adapter.py -v

# 带覆盖率报告
pytest --cov=app --cov=core tests/
```

## 📝 配置说明

所有配置通过环境变量或 `.env` 文件管理。复制 `.env.example` 为 `.env` 并填入实际值即可。

### 核心配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_API_KEY` | LLM API 密钥 | **必需** |
| `LLM_BASE_URL` | API 基础 URL | https://api.openai.com/v1 |
| `LLM_MODEL` | 主 Agent 模型名称 | gpt-4o-mini |
| `LLM_MULTIMODAL_MODEL` | 子 Agent 多模态模型（图片分析） | 空（为空则禁用图片分析） |
| `LLM_MULTIMODAL_BASE_URL` | 子 Agent 专用 API 端点 | 回退到 `LLM_BASE_URL` |
| `LLM_MULTIMODAL_API_KEY` | 子 Agent 专用 API 密钥 | 回退到 `LLM_API_KEY` |
| `SCREEN_REGION_ENABLED` | 允许用户主动框选屏幕区域提问 | true |
| `SCREEN_REGION_TTL_SECONDS` | 未发送选区的最长保留时间（秒） | 300 |
| `TASK_TIMEOUT` | 任务超时时间（秒） | 120 |
| `TASK_RETRY_MAX_ATTEMPTS` | 用户明确重试时，同一工作最多尝试次数 | 3 |
| `TASK_ESTIMATION_HISTORY_SIZE` | 用于预测时长的历史完成记录数 | 20 |
| `SKILL_EVALUATION_ENABLED` | 新提案生成后自动执行隔离包评测 | true |
| `SKILL_EVALUATION_MIN_SCORE` | 技能候选评测最低通过分 | 75 |
| `PET_NAME` | 宠物显示名称 | Lobuddy |
| `DATA_DIR` | 数据存储目录 | ./data |
| `LOGS_DIR` | 日志目录 | ./logs |

### UI 设置窗口

用户可控的关键设置也可通过托盘右键 **设置** 图标打开 UI 设置窗口修改，修改后会自动保存到 `.env` 文件。主要包括：

- **LLM 配置**：API Key、Base URL、模型名称
- **宠物设置**：名称、外观主题、点击反馈、Codex Desktop 内置伙伴、本机自定义宠物
  与 codex-pets.net 社区领养
- **快捷换伙伴**：点击或右键桌宠选择“Codex 伙伴库”；无需重复下载即可直接使用
  本机 Codex 自带伙伴，在线领养完成后也会立即切换，并联动等待、执行、成功和受阻动画
- **我们的相处节奏**：点击桌宠即可查看主动留下的偏好、当前 Check-in、
  关怀静音/稍后边界和任务成长证据；可直达记忆管理或立即撤销当前状态
- **功能开关**：图片分析、临时屏幕选区、每日问候、专注模式
- **工作执行**：任务超时、显式重试上限、时长预测样本和工作记录
- **时钟与对话**：时间格式、气泡时长、时间线显示

## 🔒 隐私与安全

- **本地存储**：所有聊天记录、宠物状态、记忆数据均存储在本地 SQLite 数据库（`data/` 目录），不会上传至任何服务器
- **API Key 加密**：配置中的 API Key 使用 Fernet 对称加密存储，密钥派生自机器标识
- **日志脱敏**：`SensitiveDataFilter` 会自动从日志中 redact 掉 API Key、Token、邮箱等敏感信息
- **命令安全**：`ToolPolicy` 与 `SafetyGuardrails` 双层防护，禁止执行 `rm -rf`、`format`、`mkfs` 等危险命令
- **路径安全**：禁止访问 UNC 路径、ADS 流、符号链接逃逸、驱动器相对路径
- **网络安全**：禁止访问 localhost、私有 IP、非标准端口，防止 DNS rebinding 攻击
- **在线宠物**：只有打开在线社区或主动领养时访问 codex-pets.net；下载内容经过域名、
  路径、大小、图片魔数和图集尺寸校验后才会安装
- **Codex 自带宠物**：只读解析本机 Codex Desktop 的受限 ASAR 索引，复制经过路径、
  大小、图片魔数和图集尺寸校验的兼容缓存；不修改 Codex 安装，也不随 Lobuddy 分发
- **陪伴状态**：只保留用户主动选择的心情、精力、支持方式和过期时间；新状态替换旧状态，
  可随时清除，隐私模式下仅驻留内存；应用活动不会被解释为真实情绪
- **屏幕选区**：只在用户主动框选后创建临时图片；不写入聊天记录或长期记忆，
  在任务结束、移除、过期或退出时删除，且不会因此获得电脑操作权限
- **临时文件安全**：临时配置文件使用 `0o600`（Unix）或 `icacls` ACL（Windows）限制权限

## 🧪 测试与调试

### 功能测试脚本

运行项目自带的功能测试脚本，快速验证核心功能：

```bash
python scripts/test_lobuddy.py
```

该脚本会检查：
1. **代码规范**：ruff（可选）、black（可选）
2. **语法编译**：所有 Python 文件是否能正常编译
3. **安全测试**：ToolPolicy、Guardrails 等安全策略
4. **数据库测试**：迁移系统的兼容性与幂等性
5. **UI 测试**：PySide6 组件导入与存在性检查
6. **健康检查**：配置、依赖、数据库连接状态

### 手动运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试文件
pytest tests/test_tool_policy.py -v
pytest tests/test_migrations.py -v
pytest tests/test_ui_smoke.py -v

# 带覆盖率报告
pytest --cov=app --cov=core tests/

# 健康检查（无需启动 UI）
python -m app.health
```

### 常见问题排查

| 问题 | 解决方案 |
|------|----------|
| `No module named 'ruff'` | ruff 为可选工具，不影响核心功能；或执行 `pip install ruff` |
| `black --check` 失败 | 当前代码未完全格式化；执行 `python -m black .` 自动修复 |
| `pytest` 收集错误 | 检查是否已安装 nanobot：`pip install -e lib/nanobot` |
| Health check 失败 | 检查 `.env` 中 `LLM_API_KEY` 和 `LLM_BASE_URL` 是否配置正确 |
| UI 测试失败 | 确保 PySide6 已安装：`pip install PySide6` |

## 🤝 贡献

欢迎提交 Issue 和 PR！

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE)

---

🐱 **Lobuddy** - 你的智能桌宠搭子
