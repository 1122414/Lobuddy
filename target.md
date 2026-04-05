# Lobuddy MVP 开发任务清单

## 项目背景

项目名：Lobuddy
仓库：https://github.com/1122414/Lobuddy
底座：最新可用 nanobot
目标：实现一个 桌面宠物助手 MVP，具备以下最小闭环：

1. 桌面显示宠物
2. 用户可输入文本任务
3. 任务交给 nanobot 执行
4. 显示执行状态与结果摘要
5. 成功任务增加经验
6. 支持等级提升与三阶段进化
7. 所有状态本地持久化

---

# 全局开发约束

## 必须遵守

- 所有 nanobot 调用必须经过 NanobotAdapter
- 不要深度修改 nanobot 内部实现，优先外层封装
- MVP 阶段任务执行采用串行队列
- 所有关键状态必须可持久化
- 所有用户可见动作必须有 UI 反馈
- 每个阶段完成后项目必须可运行

## MVP 不做

- 语音输入/语音播报
- 多宠物
- 多端同步
- 云账号系统
- 桌面 GUI 自动化
- 浏览器自动驾驶
- 商城/装扮系统
- 多渠道接入
- 复杂长期记忆改造

---

# 建议目录结构

```text
Lobuddy/
├─ app/
│  ├─ main.py
│  ├─ bootstrap.py
│  └─ config.py
├─ ui/
│  ├─ pet_window.py
│  ├─ task_panel.py
│  ├─ result_popup.py
│  ├─ settings_window.py
│  └─ assets/
├─ core/
│  ├─ models/
│  │  ├─ pet.py
│  │  ├─ task.py
│  │  └─ enums.py
│  ├─ agent/
│  │  ├─ nanobot_adapter.py
│  │  ├─ hooks.py
│  │  └─ session_manager.py
│  ├─ tasks/
│  │  ├─ task_manager.py
│  │  ├─ task_queue.py
│  │  ├─ task_runner.py
│  │  └─ result_summarizer.py
│  ├─ game/
│  │  ├─ exp_service.py
│  │  ├─ level_service.py
│  │  ├─ evolution_service.py
│  │  └─ reward_service.py
│  ├─ storage/
│  │  ├─ db.py
│  │  ├─ pet_repo.py
│  │  ├─ task_repo.py
│  │  └─ settings_repo.py
│  └─ services/
│     ├─ app_state.py
│     ├─ event_bus.py
│     └─ settings_service.py
├─ workspace/
├─ data/
├─ logs/
├─ tests/
└─ README.md
```

---

# Milestone 0：工程初始化

## Task 0.1：初始化项目骨架

### 目标

建立可运行的项目目录和入口。

### 实现要求

- 创建基础目录结构
- 创建 app/main.py
- 创建 app/bootstrap.py
- 建立日志目录和数据目录
- 建立最小 README

### 交付物

- 基础项目目录
- 应用入口文件
- 初始 README

### 验收标准

- python app/main.py 能启动
- 无导入错误
- logs/ 和 data/ 可自动创建

---

## Task 0.2：配置依赖与环境管理

### 目标

保证项目可安装、可运行、可复现。

### 实现要求

- 配置 pyproject.toml 或 requirements
- 安装并配置：
  - PySide6
  - pydantic
  - sqlite3 或 SQLAlchemy
  - nanobot 相关依赖
- 补充 .gitignore

### 交付物

- 依赖配置文件
- .gitignore

### 验收标准

- 新环境可安装项目依赖
- 启动不报缺失包错误

---

# Milestone 1：接入 nanobot

## Task 1.1：实现 NanobotAdapter

### 目标

封装 Lobuddy 对 nanobot 的唯一访问入口。

### 实现要求

创建 core/agent/nanobot_adapter.py，提供至少以下接口：

- health_check()
- run_task(prompt: str, session_key: str) -> AgentResult
- build_session_key(task_id: str) -> str

建议定义统一结果对象：

- success
- raw_output
- summary
- error_message
- started_at
- finished_at

### 交付物

- NanobotAdapter
- AgentResult 数据结构

### 验收标准

- 可从 Lobuddy 内调用 nanobot
- 成功和失败都返回结构化结果
- UI 层不直接依赖 nanobot 内部 API

---

## Task 1.2：启动时健康检查

### 目标

启动应用时验证 nanobot 可用。

### 实现要求

检查：

- nanobot 能初始化
- workspace 路径存在
- 配置文件可读取
- 必要运行目录存在

### 交付物

- 健康检查逻辑
- 启动日志输出

### 验收标准

- 启动时可以看到健康检查结果
- 出错时给出明确错误信息

---

## Task 1.3：最小任务调用验证

### 目标

打通最小 prompt -> result 链路。

### 实现要求

实现一个最小调试脚本或调试入口：

- 输入一段文本 prompt
- 调用 nanobot
- 输出原始结果和摘要结果

### 交付物

- 调试入口
- 调试日志

### 验收标准

- 真实任务可返回文本结果
- 失败时不崩溃

---

# Milestone 2：核心数据模型与持久化

## Task 2.1：定义核心数据模型

### 目标

统一项目内部状态对象。

### 实现要求

至少定义：

- PetState
- TaskRecord
- TaskResult
- AppSettings

推荐字段：

#### PetState

- id
- name
- level
- exp
- evolution_stage
- mood
- skin
- updated_at

#### TaskRecord

- id
- input_text
- task_type
- status
- difficulty
- reward_exp
- created_at
- finished_at

#### TaskResult

- task_id
- success
- raw_result
- summary
- error_message

### 交付物

- core/models/ 下的数据模型文件

### 验收标准

- 项目内部不再使用随意 dict 传状态
- 模型字段统一、清晰

---

## Task 2.2：实现 SQLite 初始化与表结构

### 目标

支持本地持久化。

### 实现要求

建立最少 3 张表：

- pet_state
- task
- task_result

首次运行时自动初始化数据库。

### 交付物

- core/storage/db.py
- 数据库初始化脚本

### 验收标准

- 应用首次运行自动创建数据库
- 表结构正确生成

---

## Task 2.3：实现 Repository 层

### 目标

隔离数据库访问逻辑。

### 实现要求

创建：

- pet_repo.py
- task_repo.py
- settings_repo.py

至少支持：

- 初始化默认宠物
- 读取宠物状态
- 更新宠物状态
- 插入任务
- 更新任务状态
- 保存任务结果
- 查询最近任务历史

### 交付物

- repository 封装

### 验收标准

- 关闭重启后数据可恢复
- 能正确保存和读取任务及宠物状态

---

# Milestone 3：桌宠基础 UI

## Task 3.1：实现桌宠主窗口

### 目标

桌宠常驻桌面并具备基础交互。

### 实现要求

创建 ui/pet_window.py，支持：

- 无边框
- 置顶
- 可拖拽
- 点击响应
- 初始宠物形象显示

### 交付物

- 桌宠主窗口

### 验收标准

- 桌宠窗口可显示
- 可拖拽移动
- 不影响基本桌面使用

---

## Task 3.2：实现宠物状态展示

### 目标

桌宠在不同任务状态下有不同表现。

### 实现要求

至少支持四态：

- idle
- running
- success
- error

可先使用静态图片/GIF/简单标签替代复杂动画。

### 交付物

- 状态切换逻辑
- 基础资源占位

### 验收标准

- 提交任务后能进入 running
- 成功后能进入 success
- 失败后能进入 error

---

## Task 3.3：实现任务输入面板

### 目标

用户可以给桌宠输入任务。

### 实现要求

创建 ui/task_panel.py，支持：

- 文本输入框
- 发送按钮
- 关闭按钮
- 最小样式即可

### 交付物

- 任务输入面板

### 验收标准

- 点击桌宠可打开输入面板
- 输入文本后可提交任务

---

## Task 3.4：实现结果弹层

### 目标

展示任务完成摘要。

### 实现要求

创建 ui/result_popup.py，支持：

- 显示摘要文本
- 显示成功/失败状态
- 可自动关闭或手动关闭

### 交付物

- 结果弹层组件

### 验收标准

- 任务结束后能看到摘要
- 失败时也有明确提示

---

# Milestone 4：任务编排与执行流

## Task 4.1：实现 TaskManager

### 目标

统一管理任务生命周期。

### 实现要求

创建 core/tasks/task_manager.py，负责：

- 创建任务
- 分配 task_id
- 保存数据库
- 调用 NanobotAdapter
- 更新任务状态
- 保存结果
- 触发事件

### 交付物

- TaskManager

### 验收标准

- 从 UI 输入到任务执行形成统一调用链
- 不允许 UI 直接管理任务状态

---

## Task 4.2：实现串行任务队列

### 目标

MVP 阶段保证执行稳定。

### 实现要求

创建 task_queue.py：

- 同时只允许一个任务运行
- 后续任务进入队列
- 当前任务完成后自动执行下一个

### 交付物

- 串行任务队列

### 验收标准

- 连续提交多个任务不会冲突
- 任务顺序正确

---

## Task 4.3：实现任务状态机

### 目标

统一任务状态流转。

### 状态定义

- created
- queued
- running
- success
- failed
- cancelled

### 实现要求

- 状态变更必须落库
- 非法状态流转要拦截

### 交付物

- 状态机逻辑

### 验收标准

- 每个任务都有明确状态
- UI 能根据状态准确展示

---

## Task 4.4：实现结果摘要器

### 目标

把 agent 输出转换成可展示的简洁结果。

### 实现要求

创建 result_summarizer.py：

- 控制摘要长度
- 避免直接把超长原始结果展示给用户
- 保留原始结果以便后续查看

### 交付物

- 结果摘要器

### 验收标准

- 用户看到的结果简洁可读
- 原始结果仍可存档

---

# Milestone 5：成长系统

## Task 5.1：实现经验奖励服务

### 目标

完成任务后增加经验。

### 实现要求

创建 reward_service.py，先使用固定规则：

- 简单任务：+5
- 中等任务：+15
- 复杂任务：+30

任务难度先允许简单规则判断或默认值。

### 交付物

- 奖励服务

### 验收标准

- 成功任务能增加经验
- 失败任务不加经验

---

## Task 5.2：实现等级系统

### 目标

经验可推动等级变化。

### 实现要求

创建 level_service.py：

- 先支持 1-10 级
- 写死经验阈值表
- 支持升级判断

### 交付物

- 等级服务
- 等级阈值表

### 验收标准

- EXP 达到阈值后自动升级
- 等级变化写入数据库

---

## Task 5.3：实现三阶段进化

### 目标

桌宠形态随等级变化。

### 实现要求

创建 evolution_service.py：

- Stage 1：Lv1-Lv3
- Stage 2：Lv4-Lv7
- Stage 3：Lv8-Lv10

进化时切换资源标识或状态，不要求复杂动画。

### 交付物

- 进化服务
- 形态映射表

### 验收标准

- 等级达到指定区间后形态变化
- 重启后形态保持正确

---

## Task 5.4：成长反馈 UI

### 目标

成长过程对用户可见。

### 实现要求

支持以下 UI 提示：

- +EXP
- Level Up
- Evolution

### 交付物

- 简单成长提示 UI

### 验收标准

- 完成任务后能感知成长变化
- 升级和进化有明确视觉反馈

---

# Milestone 6：事件总线与状态联动

## Task 6.1：实现轻量事件总线

### 目标

降低模块耦合。

### 实现要求

创建 event_bus.py，支持至少以下事件：

- task_created
- task_started
- task_completed
- task_failed
- pet_exp_gained
- pet_level_up
- pet_evolved

### 交付物

- 事件总线

### 验收标准

- 任务层和 UI 层不直接强耦合
- 成长逻辑可通过事件触发

---

## Task 6.2：联动 UI 与事件

### 目标

让界面跟随状态自动变化。

### 实现要求

让 UI 订阅相关事件并触发：

- 状态切换
- 结果弹层
- 成长提示

### 交付物

- UI 与事件联动逻辑

### 验收标准

- 任务、升级、进化反馈自动触发
- 不需要手动串联大量 UI 调用

---

# Milestone 7：设置与运行配置

## Task 7.1：实现设置模型与服务

### 目标

让 MVP 具备基本配置能力。

### 实现要求

支持至少以下配置：

- 宠物名称
- 任务超时
- 结果弹层时长
- 是否显示详细日志
- workspace 路径
- nanobot 配置路径

### 交付物

- settings_service.py
- 设置模型

### 验收标准

- 设置可读写
- 修改后重启仍保留

---

## Task 7.2：实现设置窗口

### 目标

给用户最小可配置界面。

### 实现要求

创建 ui/settings_window.py：

- 可查看当前配置
- 可修改并保存基础配置

### 交付物

- 设置窗口

### 验收标准

- 基本配置可在 UI 中修改
- 配置修改后能生效

---

# Milestone 8：容错、日志、打磨

## Task 8.1：完善错误处理

### 目标

提升演示稳定性。

### 需要覆盖的错误

- nanobot 初始化失败
- 执行超时
- 空输入
- 数据库写失败
- 无法保存设置
- UI 状态异常

### 交付物

- 错误处理逻辑
- 统一错误提示

### 验收标准

- 常见异常不会直接崩溃
- 用户能知道错误原因

---

## Task 8.2：完善日志能力

### 目标

保证可调试、可观测。

### 实现要求

记录以下日志：

- 应用启动
- nanobot 健康检查
- 任务创建
- 任务开始
- 任务完成
- 任务失败
- 升级
- 进化

### 交付物

- 文件日志
- 可选调试输出

### 验收标准

- 本地日志足够定位常见问题

---

## Task 8.3：首次引导与演示优化

### 目标

让 MVP 更适合展示。

### 实现要求

- 首次运行自动创建默认宠物
- 可选加入一个演示任务按钮
- README 补充运行说明
- 明确资源路径和运行方式

### 交付物

- 首次启动逻辑
- README 运行说明

### 验收标准

- 新用户拉起项目后能快速跑起来
- 有最基本的演示可用性

---

# 推荐 PR 划分

## PR 1

工程初始化 + 启动入口 + 依赖配置

## PR 2

NanobotAdapter + 健康检查 + 最小调用链

## PR 3

数据模型 + SQLite + Repository

## PR 4

桌宠主窗口 + 输入面板 + 结果弹层

## PR 5

TaskManager + 串行队列 + 状态机 + 摘要器

## PR 6

经验/等级/进化系统

## PR 7

事件总线 + UI 联动

## PR 8

设置页 + 容错 + 日志

## PR 9

README 完善 + 首次引导 + MVP polish

---

# 每个 Task 的 issue 模板

这个模板也可以直接给 opencode 用。

```md
## 任务标题

[简明描述本任务]

## 目标

[说明这个任务为什么要做]

## 范围

- [要做的点 1]
- [要做的点 2]
- [要做的点 3]

## 不在本任务内

- [明确不做的内容]

## 实现要求

- [技术要求 1]
- [技术要求 2]
- [技术要求 3]

## 交付物

- [文件/模块 1]
- [文件/模块 2]

## 验收标准

- [可验证标准 1]
- [可验证标准 2]
- [可验证标准 3]

## 依赖

- [依赖的前置任务]

## 备注

- [补充说明]
```

---

# 最终完成判定

当以下全部成立时，MVP 视为完成：

- Lobuddy 可正常启动
- 桌宠可在桌面显示、拖动、响应点击
- 用户可输入文本任务
- nanobot 能返回真实任务结果
- 任务状态在 UI 中可见
- 成功任务会增加经验
- 等级会提升
- 形态会在三阶段之间切换
- 数据会本地持久化
- 常见错误场景有提示
- README 能指导本地运行
