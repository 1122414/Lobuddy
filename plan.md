# Lobuddy 开发计划

## 项目概述

**Lobuddy** - AI 桌面宠物助手，基于 nanobot 打造的智能桌宠。

## 当前状态

**已完成：Stage 1** ✅ 工程骨架与 nanobot 集成

---

## Stage 1: 工程骨架与 nanobot 集成 ✅

**目标**：建立项目结构，验证 nanobot 可调通
**状态**：已完成

### 交付物
- [x] Git Submodule 配置（nanobot fork）
- [x] 项目目录结构（app/, core/, ui/, tests/, lib/）
- [x] pyproject.toml 依赖配置
- [x] .gitignore
- [x] 配置管理（app/config.py + .env.example）
- [x] NanobotAdapter 封装（core/agent/nanobot_adapter.py）
- [x] 启动引导模块（app/bootstrap.py）
- [x] 应用入口（app/main.py, app/health.py）
- [x] 冒烟测试（tests/test_nanobot_adapter.py）
- [x] README.md

### 已知问题
1. **需要手动安装 nanobot**：`pip install -e lib/nanobot`
2. Windows 终端不支持 emoji（已替换为 ASCII 字符）

### 运行验证
```bash
# 安装依赖
pip install -e lib/nanobot
pip install -e .

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY

# 运行健康检查
python -m app.health
```

---

## Stage 2: 数据模型与持久化

**目标**：定义核心模型，实现数据持久化
**预计用时**：2-3 天
**依赖**：Stage 1 完成

### 任务清单

#### 2.1 定义核心数据模型
**文件**：`core/models/pet.py`, `core/models/task.py`, `core/models/enums.py`

**PetState 模型**：
- id: str
- name: str
- level: int (1-10)
- exp: int
- evolution_stage: int (1-3)
- mood: str
- skin: str
- updated_at: datetime

**TaskRecord 模型**：
- id: str
- input_text: str
- task_type: str
- status: str (created/queued/running/success/failed/cancelled)
- difficulty: str (simple/medium/complex)
- reward_exp: int
- created_at: datetime
- started_at: datetime | None
- finished_at: datetime | None

**TaskResult 模型**：
- task_id: str
- success: bool
- raw_result: str
- summary: str
- error_message: str | None

#### 2.2 实现 SQLite 初始化与表结构
**文件**：`core/storage/db.py`

- 数据库文件：`data/lobuddy.db`
- 表：pet_state, task, task_result
- 自动迁移/初始化

#### 2.3 实现 Repository 层
**文件**：
- `core/storage/pet_repo.py`
- `core/storage/task_repo.py`
- `core/storage/settings_repo.py`

**功能**：
- 初始化默认宠物
- CRUD 操作
- 查询最近任务历史

### 验收标准
- [ ] 应用首次运行自动创建数据库
- [ ] 关闭重启后数据可恢复
- [ ] 能正确保存和读取宠物及任务状态

---

## Stage 3: 桌宠基础 UI

**目标**：宠物能显示在桌面，支持基础交互
**预计用时**：4-5 天
**依赖**：Stage 2 完成

### 任务清单

#### 3.1 实现桌宠主窗口
**文件**：`ui/pet_window.py`

**功能**：
- 无边框窗口（Qt.FramelessWindowHint）
- 置顶显示（Qt.WindowStaysOnTopHint）
- 可拖拽移动
- 点击响应
- 系统托盘常驻
- 全局快捷键唤醒（Ctrl+Shift+L）

#### 3.2 实现宠物状态展示
**文件**：`ui/pet_window.py` 状态切换逻辑

**状态**：
- idle: 待机动画/图片
- running: 执行中动画
- success: 成功反馈
- error: 错误反馈

**资源**：先用静态 PNG，后续可替换为 GIF

#### 3.3 实现任务输入面板
**文件**：`ui/task_panel.py`

**组件**：
- 文本输入框（多行）
- 发送按钮
- 关闭按钮
- 最小样式

#### 3.4 实现结果弹层
**文件**：`ui/result_popup.py`

**功能**：
- 显示摘要文本
- 显示成功/失败状态
- 自动关闭（5秒）或手动关闭

### 验收标准
- [ ] 桌宠窗口可显示，可拖拽
- [ ] 点击桌宠打开输入面板
- [ ] 提交任务后进入 running 状态
- [ ] 任务完成后显示结果弹层
- [ ] 系统托盘常驻
- [ ] 快捷键唤醒可用

---

## Stage 4: 任务编排与执行流

**目标**：打通任务从创建到完成的完整链路
**预计用时**：3-4 天
**依赖**：Stage 3 完成

### 任务清单

#### 4.1 实现 TaskManager
**文件**：`core/tasks/task_manager.py`

**职责**：
- 创建任务，分配 task_id
- 保存到数据库
- 调用 NanobotAdapter
- 更新任务状态
- 触发事件

#### 4.2 实现串行任务队列
**文件**：`core/tasks/task_queue.py`

**功能**：
- 同时只允许一个任务运行
- 后续任务进入队列
- 自动执行下一个

#### 4.3 实现任务状态机
**文件**：`core/tasks/task_manager.py` 状态流转逻辑

**状态**：created → queued → running → success/failed/cancelled

**要求**：
- 状态变更必须落库
- 非法状态流转拦截

#### 4.4 实现结果摘要器
**文件**：`core/tasks/result_summarizer.py`

**功能**：
- 控制摘要长度（默认 200 字符）
- 保留原始结果存档

### 验收标准
- [ ] UI 输入到 nanobot 执行形成完整链路
- [ ] 连续提交多个任务不会冲突
- [ ] 任务状态正确流转
- [ ] UI 根据状态准确展示

---

## Stage 5: 成长系统

**目标**：完成任务后宠物可成长，有视觉反馈
**预计用时**：3-4 天
**依赖**：Stage 4 完成

### 任务清单

#### 5.1 实现经验奖励服务
**文件**：`core/game/exp_service.py`, `core/game/reward_service.py`

**规则**：
- 简单任务：+5 EXP
- 中等任务：+15 EXP
- 复杂任务：+30 EXP
- 失败任务：+0 EXP

#### 5.2 实现等级系统
**文件**：`core/game/level_service.py`

**等级阈值表**（1-10级）：
```
Lv1: 0
Lv2: 50
Lv3: 120
Lv4: 220
Lv5: 350
Lv6: 520
Lv7: 720
Lv8: 950
Lv9: 1220
Lv10: 1550
```

#### 5.3 实现三阶段进化
**文件**：`core/game/evolution_service.py`

**阶段**：
- Stage 1：Lv1-Lv3（幼年形态）
- Stage 2：Lv4-Lv7（成长形态）
- Stage 3：Lv8-Lv10（完全形态）

#### 5.4 成长反馈 UI
**文件**：`ui/growth_feedback.py`

**反馈类型**：
- +EXP 浮动提示
- Level Up 升级动画
- Evolution 进化特效

### 验收标准
- [ ] 成功任务增加经验
- [ ] EXP 达到阈值自动升级
- [ ] 等级变化切换宠物形态
- [ ] 升级和进化有视觉反馈

---

## Stage 6: 事件总线与状态联动

**目标**：降低模块耦合，自动触发 UI 更新
**预计用时**：2-3 天
**依赖**：Stage 5 完成

### 任务清单

#### 6.1 实现轻量事件总线
**文件**：`core/services/event_bus.py`

**事件类型**：
- task_created
- task_started
- task_completed
- task_failed
- pet_exp_gained
- pet_level_up
- pet_evolved

#### 6.2 联动 UI 与事件
**文件**：修改 `ui/pet_window.py`, `ui/result_popup.py`

**订阅事件**：
- task_started → 切换 running 状态
- task_completed → 显示结果弹层 + 触发成长
- pet_level_up → 显示升级提示

### 验收标准
- [ ] 任务层和 UI 层不直接强耦合
- [ ] 成长逻辑通过事件触发
- [ ] 任务、升级、进化反馈自动触发

---

## Stage 7: 设置系统

**目标**：支持基础配置，提升用户体验
**预计用时**：2-3 天
**依赖**：Stage 6 完成

### 任务清单

#### 7.1 实现设置模型与服务
**文件**：`core/models/settings.py`, `core/services/settings_service.py`

**可配置项**：
- 宠物名称
- 任务超时时间
- 结果弹层显示时长
- 是否显示详细日志
- workspace 路径
- LLM API Key/Base URL/Model

#### 7.2 实现设置窗口
**文件**：`ui/settings_window.py`

**功能**：
- 表单展示当前配置
- 修改并保存
- 重启后配置保持

### 验收标准
- [ ] 设置窗口可正常打开
- [ ] 配置修改后能生效
- [ ] 重启后配置保持

---

## Stage 8: 容错、日志、打磨

**目标**：提升稳定性，完善首次引导
**预计用时**：2-3 天
**依赖**：Stage 7 完成

### 任务清单

#### 8.1 完善错误处理
**文件**：各模块异常处理增强

**覆盖场景**：
- nanobot 初始化失败
- 执行超时
- 空输入
- 数据库写入失败
- UI 状态异常

#### 8.2 完善日志能力
**文件**：`app/bootstrap.py` 日志配置

**记录内容**：
- 应用启动
- 健康检查
- 任务创建/开始/完成/失败
- 升级/进化

#### 8.3 首次引导与演示优化
**功能**：
- 首次运行自动创建默认宠物（Lv1, Stage 1）
- 演示任务按钮（"帮我写一段 Python 代码"）
- README 运行说明完善

### 验收标准
- [ ] 常见异常不会直接崩溃
- [ ] 用户能知道错误原因
- [ ] 日志足够定位常见问题
- [ ] 新用户能快速跑起来

---

## 推荐 PR 划分

| PR | 内容 | 对应 Stage |
|----|------|-----------|
| PR 1 | 工程初始化 + 启动入口 + 依赖配置 | Stage 1 ✅ |
| PR 2 | 数据模型 + SQLite + Repository | Stage 2 |
| PR 3 | 桌宠主窗口 + 系统托盘 + 快捷键 | Stage 3 |
| PR 4 | 任务面板 + 结果弹层 | Stage 3 |
| PR 5 | TaskManager + 串行队列 + 状态机 | Stage 4 |
| PR 6 | 结果摘要器 | Stage 4 |
| PR 7 | 经验/等级/进化系统 | Stage 5 |
| PR 8 | 成长反馈 UI | Stage 5 |
| PR 9 | 事件总线 | Stage 6 |
| PR 10 | UI 事件联动 | Stage 6 |
| PR 11 | 设置页 | Stage 7 |
| PR 12 | 容错 + 日志 + 首次引导 | Stage 8 |

---

## 技术栈

- **Python**: 3.11+
- **GUI**: PySide6
- **数据**: Pydantic + SQLite
- **日志**: Loguru
- **底座**: nanobot (git submodule)

---

## 目录结构

```
Lobuddy/
├── app/                    # 应用层
│   ├── main.py            # 应用入口
│   ├── bootstrap.py       # 启动引导
│   ├── config.py          # 配置管理
│   └── health.py          # 健康检查
├── core/                   # 核心业务层
│   ├── models/            # 数据模型
│   ├── agent/             # nanobot 适配器
│   ├── tasks/             # 任务管理
│   ├── game/              # 成长系统
│   ├── storage/           # 持久化层
│   └── services/          # 服务层
├── ui/                     # UI 层
│   ├── pet_window.py      # 桌宠主窗口
│   ├── task_panel.py      # 任务输入面板
│   ├── result_popup.py    # 结果弹层
│   ├── settings_window.py # 设置窗口
│   ├── growth_feedback.py # 成长反馈
│   └── assets/            # 资源文件
├── lib/                    # 第三方依赖
│   └── nanobot/           # git submodule
├── workspace/             # nanobot 工作目录
├── data/                  # 数据存储
├── logs/                  # 日志文件
├── tests/                 # 测试
├── pyproject.toml         # 项目配置
└── README.md
```

---

## 环境配置

### .env 文件模板

```env
# 必需：API Key（支持 OpenAI、OpenRouter 等）
LLM_API_KEY=sk-your-api-key-here

# 可选：API 基础 URL
LLM_BASE_URL=https://api.openai.com/v1

# 可选：模型名称
LLM_MODEL=gpt-4o-mini

# 可选：宠物名称
PET_NAME=Lobuddy

# 可选：任务超时（秒）
TASK_TIMEOUT=120

# 可选：结果弹层显示时长（秒）
RESULT_POPUP_DURATION=5

# 可选：日志级别
LOG_LEVEL=INFO
```

---

## 开发规范

1. **配置管理**：所有配置通过 `.env` + Pydantic Settings
2. **数据库访问**：必须通过 Repository 层，禁止直接 SQL
3. **nanobot 调用**：必须通过 NanobotAdapter，禁止直接调用 nanobot 内部 API
4. **状态管理**：使用事件总线，避免模块间直接耦合
5. **UI 更新**：通过事件订阅，禁止从任务层直接操作 UI

---

*计划版本：v1.0*
*最后更新：2026-04-05*
