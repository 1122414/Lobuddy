# Lobuddy 5.8 系统优化 — 测试与调试指南

## 快速验证

### 1. 运行核心测试

```bash
# 事件总线测试
pytest tests/test_event_bus.py -q

# Token 计量测试
pytest tests/test_token_meter.py -q

# 5.8 统一事件模型测试
pytest tests/test_unified_events.py -q

# 5.8 功能测试
python tests/test_58_functional.py
```

### 2. 运行完整测试套件

```bash
pytest tests/ -q
```

### 3. 带覆盖率报告

```bash
pytest tests/ --cov=app --cov=core -q
```

## 模块验证

### P1-B1: 统一运行事件模型

验证 EventBus 事件发布：

```python
python -c "
from core.events import EventBus, TaskQueued, TaskCompleted
bus = EventBus()
received = []
bus.subscribe(TaskQueued, lambda e: received.append(e))
bus.publish(TaskQueued(task_id='test', session_id='s1'))
assert len(received) == 1
print('EventBus OK')
"
```

验证事件 payload 安全（不含敏感字段）：

```bash
pytest tests/test_unified_events.py::TestUnifiedEventModel::test_event_payload_no_long_output -v
```

### P1-B2: 维护调度器

验证维护调度器注册和运行：

```python
python -c "
from core.services.maintenance_scheduler import MaintenanceScheduler, MaintenanceTask
import time

scheduler = MaintenanceScheduler(start_delay_seconds=0.1, poll_interval_seconds=0.1)
results = []
scheduler.register(MaintenanceTask(name='test', fn=lambda: results.append(1) or 'ok', interval_seconds=0.2))
scheduler.start()
time.sleep(0.5)
scheduler.stop()
print(f'Maintenance runs: {len(results)}')
assert len(results) >= 1
"
```

### P1-B3: 可观测性面板

验证 ObservabilityService 数据结构：

```python
python -c "
from core.services.observability_service import ObservabilityService
svc = ObservabilityService()
summary = svc.get_summary()
assert all(k in summary for k in ['token', 'recent_tasks', 'recent_traces', 'hitl_decisions', 'recent_errors'])
print('ObservabilityService OK')
"
```

### P1-B4: 启动性能

验证设置懒加载：

```bash
# 检查 ui_controller.py 中是否使用函数内导入
grep -n "from ui.history_window import" ui/ui_controller.py
grep -n "from ui.theme_editor import" ui/ui_controller.py
```

## 环境变量验证

检查 .env 文件是否包含 5.8 新增配置：

```bash
# 必需的环境变量
grep -E "^(MAINTENANCE_|OBSERVABILITY_)" .env
```

可用的环境变量列表：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MAINTENANCE_START_DELAY_SECONDS` | 维护调度器启动延迟 | 60 |
| `MAINTENANCE_POLL_INTERVAL_SECONDS` | 维护任务轮询间隔 | 10 |
| `MAINTENANCE_MEMORY_CLEANUP_INTERVAL_SECONDS` | Memory 清理间隔 | 86400 |
| `MAINTENANCE_SKILL_REVIEW_INTERVAL_SECONDS` | Skill 评审间隔 | 86400 |
| `MAINTENANCE_TRACE_CLEANUP_INTERVAL_SECONDS` | Trace 清理间隔 | 86400 |
| `MAINTENANCE_ASSET_CACHE_CLEANUP_INTERVAL_SECONDS` | 缓存清理间隔 | 604800 |
| `OBSERVABILITY_MAX_TRACES` | 最大轨迹展示数 | 10 |
| `OBSERVABILITY_MAX_HITL_RECORDS` | 最大 HITL 记录数 | 10 |
| `OBSERVABILITY_MAX_TOKEN_SESSIONS` | 最大 Token 会话数 | 5 |

## 调试技巧

### 查看维护调度器状态

```python
python -c "
from app.service_wiring import create_services
from core.config import Settings

settings = Settings(llm_api_key='test')
# 需要 mock TaskManager
"
```

### 查看事件发布日志

事件发布会记录 DEBUG 级别日志：

```python
import logging
logging.getLogger('event').setLevel(logging.DEBUG)
```

### 检查可观测性面板数据

```python
python -c "
from core.services.observability_service import ObservabilityService
from core.storage.execution_trace_repository import ExecutionTraceRepository
from core.storage.hitl_approval_repo import HitlApprovalRepository

svc = ObservabilityService(
    trace_repo=ExecutionTraceRepository(),
    hitl_repo=HitlApprovalRepository(),
)
print(svc.get_summary())
"
```

## 常见问题

### Q: 维护任务没有运行？
A: 检查 `MAINTENANCE_START_DELAY_SECONDS` 是否设置过长，或对应间隔是否为 0（禁用）。

### Q: 可观测性面板没有数据？
A: 需要执行任务后才会有数据。新启动时数据库为空是正常的。

### Q: 事件没有触发？
A: 确保 EventBus 是同一个实例。TaskManager 使用 `self.adapter.event_bus`。

## 提交记录

```bash
git log --oneline -5
```

预期看到：
- `feat(5.8): P1-B1 统一运行事件模型`
- `feat(5.8): P1-B2/B3/B4 维护调度器、可观测性面板与启动优化`
