# Lobuddy

以浊蒂桌宠相伴的桌面个人助手。新版使用 Electron + React、Python/SQLite 和 DSH，提供连续语音、关系记忆、持续委托、提醒、项目资料和可查证的方法学习。

首轮交付目标为 macOS Apple Silicon（macOS 14+）。Windows/Linux、语音真人完整验收和公开签名发布状态分别记录，不以可构建代表全部验收完成。

## 使用与开发

本地安装包包含 Python 和 DSH，不依赖开发目录；模型凭据通过应用设置存入 Keychain。语音识别模型需在设置中主动下载，当前 Fish 音色保持用户选择。

- [10.19 使用、备份与回退说明](docs/2026-10-19_personal_agent_guide.md)
- [升级计划与验收状态](plan_/10.19/2026-10-19_lobuddy_personal_agent_upgrade_plan.md)

源码开发（Python 3.12、Node 24）：

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dsh,voice]'
npm ci --prefix bridge/dsh
npm run build --prefix bridge/dsh
npm ci --prefix desktop
npm run build --prefix desktop
.venv/bin/python -m app.desktop
# 生成 macOS arm64 本地应用（已验收构建基础：uv standalone CPython 3.12.13）
npm run package --prefix desktop
```

完整旧版回归使用 `requirements-dev-macos.lock`，保留 Qt/nanobot 兼容测试依赖。旧版入口 `python -m app.main` / `lobuddy-legacy` 只用于匹配旧库的兼容与回退；新版默认 `lobuddy` 启动 Electron。开发 `.env` 不打进安装包；API Key 不应写入源码或提交。

## 历史 Qt 版本参考

以下目录和部分能力描述来自旧版实现；新版业务通过 `app/service.py`、`core/service/` 与 `desktop/` 连接，实际有效能力以新版界面和验收报告为准。

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
│   ├── tasks/             # 任务管理
│   ├── game/              # 成长系统
│   ├── storage/           # 持久化层
│   └── services/          # 服务层
├── ui/                     # UI 层（Stage 3 实现）
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

## 🎯 开发阶段

当前：**Stage 8** 🔄 容错、日志、打磨（进行中）

所有 8 个 Stage 基础设施已实现，当前专注于打磨和优化。

### 已完成功能

- [x] **Stage 1**: 工程骨架与 nanobot 集成
- [x] **Stage 2**: 数据模型与持久化（SQLite + Repository 模式）
- [x] **Stage 3**: 桌宠 UI（PySide6 无边框窗口/系统托盘/全局快捷键）
- [x] **Stage 4**: 任务编排与状态流转（串行队列/超时控制/历史压缩）
- [-] **Stage 5**: 成长系统（经验/等级/进化/能力解锁/个性引擎）— 功能完成，成长反馈 UI 待完善（升级/进化动画）
- [-] **Stage 6**: 事件总线（轻量异步 EventBus）— EventBus 实现，UI 层仍主要用 Qt Signal
- [-] **Stage 7**: 设置系统（配置窗口/SQLite 持久化）— 基础实现完成，UI 待完善
- [-] **Stage 8**: 容错、日志、打磨（退出可靠性/code-simplifier 重构）

### 计划外已实现功能

- [x] 聊天历史系统（多会话/消息持久化）
- [x] 多模态图片分析（独立子进程 + Pillow 压缩）
- [x] 个性进化系统（五维属性自动调整）
- [x] 能力解锁系统（7 种可解锁能力）
- [x] 安全加固（Guardrails/API Key 加密/日志脱敏）
- [x] 224 测试覆盖

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

所有配置通过环境变量或 `.env` 文件管理：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_API_KEY` | LLM API 密钥 | **必需** |
| `LLM_BASE_URL` | API 基础 URL | https://api.openai.com/v1 |
| `LLM_MODEL` | 主 Agent 模型名称 | gpt-4o-mini |
| `LLM_MULTIMODAL_MODEL` | 子 Agent 多模态模型（图片分析） | 空（为空则禁用图片分析） |
| `LLM_MULTIMODAL_BASE_URL` | 子 Agent 专用 API 端点 | 回退到 `LLM_BASE_URL` |
| `LLM_MULTIMODAL_API_KEY` | 子 Agent 专用 API 密钥 | 回退到 `LLM_API_KEY` |
| `TASK_TIMEOUT` | 任务超时时间（秒） | 120 |
| `PET_NAME` | 宠物显示名称 | Lobuddy |
| `DATA_DIR` | 数据存储目录 | ./data |
| `LOGS_DIR` | 日志目录 | ./logs |

## 🤝 贡献

欢迎提交 Issue 和 PR！

## 📄 许可证

项目元数据声明为 MIT，见 [pyproject.toml](pyproject.toml)。仓库目前没有独立 LICENSE 文件。

---

🐱 **Lobuddy** - 你的智能桌宠搭子
