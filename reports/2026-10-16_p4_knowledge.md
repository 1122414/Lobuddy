# P4 长期记忆与技能迁移验收

日期：2026-10-16。P4 验收通过；本阶段只使用合成库，真实旧库备份、搬迁和凭据升级仍属于 P5。

## 实现

`KnowledgeService` 注入同一个 SQLite Database，复用 MemoryService / MemoryWriteGateway / MemorySelector、ConversationSummarizer、SessionSearchService、SkillManager / SkillSelector / SkillCandidateExtractor。身份信号提取移至无引擎依赖模块，旧 nanobot 方法保留兼容转发。新服务不导入 Qt 或 nanobot。

DSH 每轮通过 scoped `systemPrompt.variable` + `section` 读取当前记忆与启用技能正文，不把画像复制为用户消息，也不采用会持久化旧快照的 `systemPrompt.context`。管理操作刷新正在执行会话的系统上下文，下一次模型步骤使用新内容；已经发出的模型请求不能被追溯修改。原始聊天历史仍保留，删除长期记忆不等于删除用户历史消息。手动纠正后保留旧摘要以供查看，但不再注入早于纠正的摘要，后续摘要仅使用纠正后的消息。

新增管理接口与前端生成类型：记忆列表/保存/删除，技能列表/详情/保存/启停/归档/候选审核，历史关键词搜索与摘要查看。Electron 继续只暴露业务白名单。模型可使用受治理的历史搜索与记忆提议工具；记忆提议必须通过 HITL，拒绝或取消无写入，来源关联实际会话与消息。所有新增长期记忆、摘要写入经过 MemoryWriteGateway，低置信度提议保存为待确认记录。工具结果继续限额，文件工具不能绕过网关改写知识投影。

技能正文增补为 SQLite 字段，安全读取现有 SKILL.md 后惰性回填，不重建技能 ID。禁用删除投影但保留正文；禁用时编辑不会悄悄重新启用；重新启用从权威正文生成文件。技能候选由成功任务提取，遵循既有自动提议开关，明确“保存为技能”请求可产生待审核候选，不自动启用。

## 问题与修复

| ID / 优先级 | 问题与证据 | 修复前行为 | 解决方案 / 预期行为 | 风险 | 状态 |
| --- | --- | --- | --- | --- | --- |
| K01 / P1 | 投影函数遇到空记录直接返回（代码证据） | 预计最后一条记忆删除后 USER/PROJECT 等仍含旧内容 | 仅清空带生成标记的空投影；未知手写文件不抹除 | 不修复会继续误召回；修复不代替旧库备份 | 回归通过 |
| K02 / P1 | 禁用只删正文，未存数据库；patch 无状态判断 | 预计停用后无法恢复、编辑停用项重新产生文件 | SQLite 保存正文，启停重建/移除投影，编辑尊重停用状态 | 已被旧版删除的正文无法凭空恢复，界面明确报缺失 | 回归及真实模型通过 |
| K03 / P1 | cleanup 调用不存在的 list_skills(name=...) 并吞异常；保存用 REPLACE | 预计清理会删活动技能，更新可能级联删除审计事件 | 按名称查询；ON CONFLICT UPDATE 保留事件 | 不修复会损失活动投影/审计；旧来源路径搬迁需 P5 处理 | 回归通过 |
| K04 / P1 | 新 DSH 链路原无知识入口，画像纠正可能被旧摘要覆盖 | 原仅有文件工具，无记忆/技能 UI | 动态系统上下文、受控工具、管理入口与旧摘要失效边界 | 不自动删除聊天史；正在生成的请求无法撤回已发上下文 | 真实模型和 UI 通过 |
| K05 / P2 | macOS /var 与 /private/var 别名被字符串路径比较判为不同（真实 smoke 观察） | 停用合成旧技能报 ValueError | 比较规范路径，同时检查实际管理路径的符号链接与范围 | 不放宽实际越界/符号链接防护 | 新回归及真实 smoke 通过 |
| K06 / P2 | React 表单重建后 textarea 文本进入标签文本（真实 Electron 观察） | getByLabel 精确定位失败，字段可访问名称不稳定 | textarea/select 使用固定 aria-label | 无业务行为变更 | UI 重测通过 |

## 检查记录

| ID | 命令 / 步骤 | 变更前结果 | 变更后期望 | 实际结果 | 状态 |
| --- | --- | --- | --- | --- | --- |
| K01–K05 | 临时 cwd 下运行 `pytest tests/test_memory* tests/test_skill* tests/test_session_search.py tests/test_knowledge_service.py tests/test_headless_service.py tests/test_dsh_tools.py -q`（绝对路径 + PYTHONPATH） | 新回归预计失败；既有回归为 P0 基线 | 旧接口兼容，数据生命周期及拒绝边界成立 | 165 passed，两个既有 Pydantic 弃用警告 | 通过 |
| K02/K03/K05 | 最后代码调整后运行 knowledge_service、skill_manager、nanobot_adapter、dsh_tools | 身份提取兼容/技能生命周期需回归 | 不丢旧调用约定和来源 ID | 50 passed | 通过 |
| K04/K05 | `PYTHONPATH=. .venv/bin/python scripts/smoke_dsh_knowledge.py` | 原无知识上下文；首次发现路径别名问题 | 真实模型召回、同会话纠正、删除、新会话、技能启停、审批、检索、重启保持 ID | 四组 PASS；实际记忆拒绝无落库、允许关联真实消息；搜索工具有完成事件 | 通过 |
| K04/K06 | `node desktop/tests/knowledge-smoke.cjs` | 原无管理页；首次发现 textarea 标签问题 | 真实 Electron/Python 完成记忆增删改、来源、取消删除、技能停用编辑重载恢复、历史入口 | 三组 PASS，renderer 无 pageerror；最终视觉调整后再通过 | 通过 |
| K04 | `npm test --prefix desktop` | P3 3 tests 已通过 | 类型、生产构建、路径/URL安全及 Python stdio 不退化 | 3 tests passed + TypeScript/Vite 通过 | 通过 |
| K04 | `npm test --prefix bridge/dsh` | P1 3 tests 已通过 | 插件类型、构建、鉴权/去重/断连通过 | 3 tests passed | 通过 |
| K01–K06 | 14 个新建/整理 Python 文件 Ruff、Black、mypy | 部分旧文件有已记录静态债务 | 本次独立实现和整理文件通过 | 全部通过，见下方边界 | 通过 |

静态检查集合：core/service/{knowledge,knowledge_protocol,application,protocol,stdio}.py、core/agent/dsh/tools.py、core/memory/{identity,memory_write_gateway,memory_projection,conversation_summarizer}.py、core/skills/skill_manager.py、scripts/{generate_desktop_protocol,smoke_dsh_knowledge}.py、tests/test_knowledge_service.py。两个仅局部改动的历史文件 memory_service.py / nanobot_adapter.py 仍有既有 Ruff/Black 债务，不宣称全仓静态检查绿色；未为了 P4 清理无关旧适配器。

视觉沿用 P3 已确认的蓝绿/冷白设计，实际 Electron 1536×1024 CSS 窗口核对了主导航、卡片选中、编辑/来源/审批、滚动与空态；添加明确来源中文标签并修正卡片内部对齐。截图均为测试操作后的真实数据：[记忆](assets/p4-memory.png)、[技能](assets/p4-skills.png)。

## 剩余边界

- 原文件已被旧版删除、数据库没有正文的停用技能，显示缺失并要求恢复或补全文本，不生成空实现。
- 旧技能绝对路径指向不同工作区时，保留记录但拒绝文件操作，交由 P5 备份迁移映射；不静默写入旧目录。
- 跨会话历史检索继续遵循既有设置；模型历史检索开关默认关闭，真实 smoke 在临时子进程中显式开启。
- 全量回归、真实库搬迁、独立安装包、语音和两小时运行验收尚未完成，仍按 P5–P9 推进。
