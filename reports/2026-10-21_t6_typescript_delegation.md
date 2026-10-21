# T6：持久委托、调度与 Jev 迁移验收

基线：T5 `7295107`。本阶段在既有 TypeScript 业务进程内实现持久委托、日历调度、通知与 Jev。当前桌面默认后端尚未切换；本报告不代替 T8–T10 连续语音、安装包和长稳验收。

## 改动与问题

| ID / 优先级 | 问题与证据 | 改动前行为 | 方案 | 改动后预期 | 风险 | 状态 |
|---|---|---|---|---|---|---|
| TS6-01 / P1 | T5 不提供委托 RPC；旧请求指纹包含 Pydantic 浮点格式 | TS 无法领取、确认或暂停持久委托；直接 JSON.stringify 会改变部分请求指纹（预测） | 版本修订、授权状态机、固定工作流版本；八个实际旧序列化合成样例 | 重复请求读同一次执行；修改范围取消原授权 | 保持旧 float 序列化是兼容约束 | 通过自动检查 |
| TS6-02 / P1 | 完成事件若落在结算事务之外，崩溃会漏掉依赖委托 | TS 没有委托完成事件 | 任务、结果、委托、通知及 completion event 同事务；故障注入回滚 | 失败提交全部回滚；成功提交只产生一份事件和奖励 | 文件副作用不能用数据库事务撤销 | 通过自动及原生检查 |
| TS6-03 / P1 | 未知写入、旧审批和预算不能因重启重新执行 | TS 无检查点恢复入口 | 只读来源哈希与固定版本校验；原 run/turn ID 恢复；累计调用和时间；写入只检查产物 | 来源改变拒绝恢复；未知写不重放；暂停后拒绝旧审批 | 远程 URL 无法锁定来源，不提供检查点恢复 | 通过自动检查 |
| TS6-04 / P1 | 机器时区和 Date 算术不能保留日历墙钟规则 | TS 无持久调度 | Temporal 墙钟转换，跳过 DST 缺口，重复时刻首次；单所有者与持久游标 | 原时区不变；错过周期合并；展示确认与已读分离 | 应用退出时不运行；恢复后的过期任务需核对 | 通过自动检查 |
| TS6-05 / P1 | 无 Jev 接线时可能遗漏预算、重复判断或扩大权限 | TS 无 Jev 消费者 | 固定 HTTPS 端点、严格分布校验、独立每日预留预算、异步所有者与过期结果检查 | 未配置保持原行为；失败不重试；明确提醒不经 Jev；判定只影响通知 | 一次真实接口通过不代表普遍判断准确率 | 通过自动及真实接口检查 |

委托运行依赖工作流，因此提前迁移了固定版本读取和声明式执行器；T7 仍负责候选生成、评测、自动晋升、观察期及回退。没有提前把这些进化功能标为完成。

凭据通过 Electron 主进程的受信启动消息传入，运行在内存中；渲染器 RPC 不提供秘密字段。新增 TypeSafe 凭据与模型凭据分别处理，未配置模型仍可执行不含模型节点的固定工作流。最终桌面凭据启动接线由 T9 完成。

## 定向验证

改动前结果除注明外均为依据 T5 缺少相应 TS 接口的预测，不是恢复旧行为后的测量。

| ID | 测试 / 命令 | 改动前预期 | 改动后预期 | 实际结果与证据 | 状态 |
|---|---|---|---|---|---|
| TS6-01 | `scheduling.test.ts` 身份、授权、修订与旧 JSON 样例；`delegation-execution.test.ts` 原生队列重放 | 无对应 TS 服务 | 同 ID 同执行、旧请求兼容 | 断言通过；重复提交与重启不加消息/奖励 | 已执行 |
| TS6-02 | `delegation-execution.test.ts` settlement failure 测试 | 无原子委托结算 | 任意提交失败不留下通知、奖励或完成事件 | 故障注入后全部回滚，重试一次后仅一份事件 | 已执行 |
| TS6-03 | 同文件 readonly checkpoint、uncertain copies、persistent budgets、approval 测试 | 无恢复与审批闭环 | 只读恢复，变化拒绝，旧审批无效，预算不重置 | 七组应用链路测试通过 | 已执行 |
| TS6-04 | `scheduling.test.ts` calendar、lease、missed/event；应用 power 测试 | 无 TS 日历调度 | 保留时区、DST、去重、睡眠抑制 | 六组调度测试通过 | 已执行 |
| TS6-05 | `jev.test.ts`；`qualification/ts-runtime/delegation-probe.cts` | 无 TS Jev | 严格校验、预留、去重、安全降级 | 五组 Jev 测试及一次真实 TypeSafe 请求通过，记录实际 token | 已执行 |

完整命令：

- `npm run build:packages`
- `node --test packages/service/dist/delegation-execution.test.js packages/service/dist/scheduling.test.js packages/service/dist/jev.test.js`：18 组通过。
- 独立快照执行 `npm ci --offline --ignore-scripts` 与 `LOBUDDY_PYTHON=<旧对照环境> npm run check`：qualification 2、contracts 5（988 输入样例）、integration 94、bridge 8、desktop 16，全部通过。旧对照环境仅为尚未退役的桌面兼容检查服务，T9 后移除。
- 独立快照离线安装 674 个包，审计 682 个包，0 vulnerabilities。Temporal 是此前已锁定依赖，本阶段声明 domain 的直接使用关系，未升级依赖。
- Electron 44.8.0 / Node 24.22.0 utilityProcess 原生检查：固定工作流结果、Jev 真实调用、重启去重、拒绝写审批、关闭五组通过，见 [原生证据](2026-10-21_t6_native_evidence.json)。全部使用临时合成资料；报告无用户文字或凭据。

## 映射与边界

`migration/progress.json` 本阶段增加 41 项明确等价断言映射，累计 111 / 1077；剩余 966 项保持 pending，不能把契约样例或少量场景检查当作全部旧业务测试已迁移。固定旧测试清单、哈希和原 ID 均未修改。

默认桌面仍走旧后端；T7 的技能/进化、T8 的完整连续语音、T9 默认切换与退役及 T10 发布门槛尚未关闭。真人语音、外放回声、端到端延迟、两个 7200 秒运行检查均不由本阶段宣称通过。
