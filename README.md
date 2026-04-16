# Lobuddy

🐱 **Lobuddy** - AI 桌面宠物助手 (AI Desktop Pet Assistant)

基于 [nanobot](https://github.com/1122414/nanobot) 打造的智能桌宠，让 AI 助手以可爱的宠物形态常驻桌面。

## ✨ 特性

- 🐈 **桌宠形态** - 可爱的虚拟宠物常驻桌面
- 🤖 **AI 助手** - 基于 nanobot 的强大任务执行能力
- 📋 **任务管理** - 输入任务，自动执行并反馈
- 📈 **成长系统** - 完成任务获得经验，升级进化
- 💾 **本地持久化** - 所有数据本地存储
- 🖼️ **多模态图片分析** - 子 Agent 支持视觉理解，超大图片自动压缩后分析
- 🖥️ **跨平台** - Windows / macOS / Linux 支持
- ⚡ **可靠退出** - 托盘右键 Exit 可彻底关闭应用，带超时保护机制

## 🚀 快速开始

### 环境要求

- Python 3.10+
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

已完成功能：

- [x] 项目目录结构
- [x] Git Submodule 配置
- [x] 配置管理（.env + Pydantic）
- [x] NanobotAdapter 封装
- [x] 启动引导模块
- [x] 基础测试
- [x] 子 Agent 多模态图片分析（独立进程 + 自动压缩）
- [x] 应用退出可靠性修复（托盘 Exit / asyncio 清理 / 热键线程回收）

 upcoming stages：

- **Stage 2**: 数据模型与持久化（SQLite）
- **Stage 3**: 桌宠 UI（PySide6）
- **Stage 4**: 任务编排与状态流转
- **Stage 5**: 成长系统（经验/等级/进化）
- **Stage 6**: 事件总线
- **Stage 7**: 设置系统
- **Stage 8**: 容错、日志、打磨

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

## 🧪 测试

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

MIT License - 详见 [LICENSE](LICENSE)

---

🐱 **Lobuddy** - 你的智能桌宠搭子
