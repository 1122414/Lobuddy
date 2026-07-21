"""Real Qt regression coverage for the user-facing work record."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.config import Settings
from core.models.model_usage import ModelUsageEvidence, ModelUsageSource
from core.models.pet import TaskRecord, TaskResult, TaskStatus
from core.runtime.token_meter import TokenMeter
from core.services.observability_service import ObservabilityService
from core.storage.db import Database
from core.storage.execution_trace_repository import ExecutionTraceRepository
from core.storage.task_repo import TaskRepository
from core.tasks.task_run_service import TaskRunService
from ui.observability_panel import ObservabilityPanel


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_work_record_renders_real_task_run_and_tool_evidence(
    tmp_path: Path,
) -> None:
    app = _qapp()
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
    )
    database = Database(settings)
    database.init_database()
    runs = TaskRunService(settings, TaskRepository(database))
    task = TaskRecord(
        id="visible-run",
        input_text="整理项目发布清单",
        status=TaskStatus.QUEUED,
        session_id="session-1",
    )
    runs.create(task)
    runs.start(task.id)
    runs.progress(
        task.id,
        key="verify-output",
        title="验证执行结果",
        detail="发布设置已经保存",
        step_index=2,
        max_actions=3,
    )
    runs.complete(
        task.id,
        TaskResult(
            task_id=task.id,
            success=True,
            summary="发布清单已经整理完成",
            usage_evidence=ModelUsageEvidence(
                provider_model="provider-model",
                prompt_tokens=1_000,
                completion_tokens=200,
                cached_tokens=400,
                source=ModelUsageSource.PROVIDER,
            ),
        ),
    )
    traces = ExecutionTraceRepository(database)
    traces.record(
        "session-1",
        "检查文件",
        "read_file",
        {"path": "README.md"},
        "success",
        result_summary="文件读取完成",
    )

    meter = TokenMeter()
    meter.increment_turn("session-1")
    meter.record_measurement_source("session-1", "provider")
    meter.record_usage("session-1", "model_input", prompt_tokens=1_000)
    meter.record_usage("session-1", "model_output", completion_tokens=200)
    panel = ObservabilityPanel(
        ObservabilityService(
            task_runs=runs,
            trace_repo=traces,
            token_meter=meter,
        )
    )
    panel.show()
    app.processEvents()

    assert panel.windowTitle() == "工作记录"
    assert panel._total_metric[1].text() == "1"
    assert panel._success_metric[1].text() == "100%"
    assert panel._runs_table.rowCount() == 1
    assert panel._runs_table.item(0, 0).text() == "整理项目发布清单"
    assert panel._runs_table.item(0, 1).text() == "已完成"
    assert panel._runs_table.item(0, 3).text() == "< 1 秒"
    assert panel._runs_table.item(0, 4).text() == "实测 1.2k"
    assert panel._runs_table.item(0, 5).text() == "工作已完成"
    assert panel._token_label.text() == "Token：1,200 · 服务商计量 · 对话轮次：1"
    assert panel._tools_table.rowCount() == 1
    assert panel._tools_table.item(0, 0).text() == "read_file"
    assert panel.grab().width() >= 920
    assert panel.grab().height() >= 650

    panel.close()
    app.processEvents()
