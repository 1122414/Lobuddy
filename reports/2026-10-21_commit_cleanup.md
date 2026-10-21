# 独立提交与工作区收尾记录

日期：2026-10-21。基线 `ee63e3a`，分支 `codex/lobuddy-dsh-rebuild`；远程 main 已合并该基线。仅整理本轮开始时的未提交内容及必要验证修复，不等同于重新完成全部产品验收。

## Changed

| ID / 优先级 | 问题与证据 | 改前行为 | 方案 / 预期 | 风险 | 状态 |
|---|---|---|---|---|---|
| CL-01 / P1 | Git 实测 68 修改、1 删除、71 未跟踪；后续功能共享应用与协议文件 | 完整实现仅在工作区，无法按模块复现 | 依赖顺序拆分，逐个独立快照验证后提交 | 错误拆分可遗漏调用方；每批检查生成协议与构建 | 处理中 |
| CL-02 / P2 | `test_53_phase1_verification.py` 未设置 `skill_archive_dir`，固定内容与未跟踪 `archive-test_v1.md` 相同 | 归档测试写入默认项目 data 目录（源码及产物证据） | 显式临时归档路径并断言；原产物移至忽略的收尾副本目录保留 | 不改生产归档行为 | 本轮验证通过 |
| CL-03 / P1 | 历史报告中真人语音和连续语音两小时仍待验收 | 实现、自动验证与阶段完成状态混在未提交工作中 | 提交实现，持续列出待验收项；不宣称可发布 | 实际语音质量与长稳仍未保证 | 保留边界 |

## Verified

| 批次 / 问题 | 命令 / 检查 | 修复前预期 | 修复后预期 | 本次实际结果 | 状态 |
|---|---|---|---|---|---|
| C1 / CL-02 | 独立快照 `pytest tests/test_nanobot_adapter.py tests/test_53_phase1_verification.py -q` | 默认归档目录可污染项目（源码推断） | 归档留在临时目录、原功能不退化 | 47 passed；新增归档范围断言通过；1 条既有警告 | 通过 |
| C1 / CL-01 | `node --test desktop/tests/wait-for.test.cjs`；五个更新脚本 `node --check` | Promise 可能被误当成 true（历史实测） | 等待异步 false；保留最终断言 | 1 项通过，脚本语法检查通过；本轮未重跑五个真实模型 UI 场景 | 通过，范围明确 |

C1：`test_nanobot_adapter.py` Ruff/Black 通过；原 5.3 测试文件仅修改临时路径及增加断言，未扩展清理其既有格式。

## Risks

真人连续十轮、耳机/扬声器回声、自然接话、真实设备延迟及连续语音长稳仍待验收。本次不自动启用麦克风、不修改个人库、不发布或推送。历史报告中的失败保留，不用新短测覆盖旧失败。

### C2：语音实现（产品验收待完成）

- 独立快照：`pytest tests/test_voice_service.py tests/test_headless_service.py tests/test_scheduling.py tests/test_jev.py -q`：97 passed，1 条既有警告。
- `npm test --prefix desktop`：16 passed，包含七项语音迟到回调/采音队列测试；类型和生产构建通过。
- 9 个 Python 文件 Ruff/Black、8 个源文件 mypy 通过。首次 mypy 指出语音冒烟脚本未校验 RPC 会话返回类型；增加真实类型检查后通过，不削弱断言。
- `voice-download-smoke.cjs`：使用已有只读模型目录及隔离合成凭据，设置页、模型就绪和管理窗口拒绝麦克风通过。本次没有下载、真实采音、Fish 请求或长稳测试；脚本固定 PASS 文案中的下载不代表本次发生下载。
- 中间提交只接入 voice 协议和消费者；陪伴/方法学习/默认桌面入口仍留给后续批次。
