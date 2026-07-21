"""Render deterministic offscreen previews of Lobuddy's core windows."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QRect, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from PIL import Image, ImageDraw

from core.companion.models import (
    CompanionCheckIn,
    CompanionEnergy,
    CompanionIntervention,
    CompanionMood,
    CompanionSupportMode,
    InterventionKind,
)
from core.companion.runtime import CompanionRuntime
from core.computer_use.models import ComputerAction, ComputerActionType, utc_now
from core.config import Settings
from core.data_control import DataControlCenter
from core.events import MemoryContextPrepared
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    ConflictCandidate,
    ConflictType,
    MemoryContextEvidence,
    MemoryItem,
    MemoryRecallFeedback,
    MemoryType,
)
from core.memory.memory_service import MemoryService
from core.memory.privacy_mode import PrivacyModeManager
from core.models.appearance import get_appearance
from core.models.model_usage import ModelUsageEvidence, ModelUsageSource
from core.models.pet import TaskDifficulty, TaskRecord, TaskResult, TaskStatus
from core.models.task_card import TaskCardModel, TaskStep
from core.personality.evolution import PersonalityEvolution
from core.relationship.rhythm_service import RelationshipRhythmService
from core.screen_region import ScreenRegionBounds, ScreenRegionCapture
from core.screen_region.runtime import ScreenRegionRuntime
from core.services.codex_pet_service import CodexPetService
from core.services.observability_service import ObservabilityService
from core.skills.skill_evolution_service import SkillEvolutionService
from core.skills.skill_manager import SkillManager
from core.storage import db as db_module
from core.storage.chat_repo import ChatRepository
from core.storage.computer_use_repo import ComputerUseRepository
from core.storage.db import Database
from core.storage.execution_trace_repository import ExecutionTraceRepository
from core.storage.pet_repo import PetRepository
from core.storage.task_repo import TaskRepository
from core.tasks.task_run_service import TaskRunService
from core.tasks.task_recovery_service import TaskRecoveryService
from ui.companion_checkin_dialog import CompanionCheckInDialog
from ui.data_control_dialog import DataControlDialog
from ui.pet_window import PetWindow
from ui.codex_pet_library_dialog import CodexPetLibraryDialog
from ui.memory_console_window import MemoryConsoleWindow
from ui.memory_portability_dialog import MemoryImportReviewDialog
from ui.memory_recall_review_dialog import MemoryRecallReviewDialog
from ui.observability_panel import ObservabilityPanel
from ui.personality_evolution_dialog import PersonalityEvolutionDialog
from ui.quick_action_menu import QuickActionMenu
from ui.relationship_rhythm_dialog import RelationshipRhythmDialog
from ui.settings_window import SettingsWindow
from ui.skill_lab_panel import SkillLabPanel
from ui.screen_region_selector import ScreenRegionSelector
from ui.task_card_panel import TaskCardPanel
from ui.task_panel import TaskPanel
from ui.task_recovery_dialog import TaskRecoveryDialog


def render_previews(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    rendered: list[Path] = []

    with tempfile.TemporaryDirectory(prefix="lobuddy-ui-preview-") as temp_dir:
        settings = Settings(
            llm_api_key="preview",
            llm_multimodal_model="preview-vision",
            pet_name="Lobuddy",
            data_dir=Path(temp_dir) / "data",
            workspace_path=Path(temp_dir) / "workspace",
            skill_archive_dir=Path(temp_dir) / "archive",
            computer_use_enabled=True,
        )
        db_module._db = Database(settings)
        db_module._db.init_database()

        appearance = get_appearance()
        custom_asset_path = appearance.custom_asset_path
        custom_asset_type = appearance.custom_asset_type
        custom_asset_source = appearance.custom_asset_source
        custom_asset_name = appearance.custom_asset_name
        codex_pet_id = appearance.codex_pet_id
        custom_state_asset_paths = appearance.custom_state_asset_paths.copy()
        appearance.custom_asset_path = None
        appearance.custom_asset_type = "default"
        appearance.custom_asset_source = "default"
        appearance.custom_asset_name = ""
        appearance.codex_pet_id = None
        appearance.custom_state_asset_paths = {}

        pet = PetWindow()
        pet.set_settings(settings)
        pet.show_speech_bubble("我在这里。要不要一起把这件事慢慢做完？", 10000)
        rendered.append(_render(app, pet, output_dir / "pet-window.png"))
        pet.show_companion_intervention(
            CompanionIntervention(
                event_id=1,
                kind=InterventionKind.REST,
                title="休息一下",
                message="已经专注很久啦，活动一下肩颈、喝口水吧。回来我继续陪你。",
                reason="检测到你已连续活跃约 51 分钟。",
            )
        )
        rendered.append(
            _render(
                app,
                pet._companion_card,
                output_dir / "companion-feedback.png",
            )
        )

        quick_menu = QuickActionMenu()
        rendered.append(_render(app, quick_menu, output_dir / "quick-menu.png"))

        now = datetime.now().replace(second=0, microsecond=0)
        check_in = CompanionCheckInDialog(
            pet,
            active_check_in=CompanionCheckIn(
                mood=CompanionMood.TIRED,
                energy=CompanionEnergy.LOW,
                support_mode=CompanionSupportMode.ENCOURAGE,
                created_at=now,
                expires_at=now + timedelta(hours=2),
            ),
            duration_minutes=settings.companion_checkin_duration_minutes,
        )
        rendered.append(_render(app, check_in, output_dir / "companion-check-in.png"))

        preview_chat_repo = ChatRepository()
        preview_session = preview_chat_repo.get_or_create_session(
            "preview-session",
            title="今天的收尾工作",
        )
        preview_chat_repo.save_message(
            preview_session.add_message(
                "user",
                "今天有点累，但还想把项目收个尾。",
            )
        )
        preview_chat_repo.save_message(
            preview_session.add_message(
                "assistant",
                "那我们只抓最重要的一件事。我先帮你拆成三步。",
            )
        )
        task_panel = TaskPanel(preview_chat_repo)
        task_panel.set_settings(settings)
        task_panel.current_session_id = "preview-session"
        task_panel.update_skill_candidate_count(1)
        task_panel.update_memory_context(
            MemoryContextPrepared(
                task_id="preview-task",
                session_id="preview-session",
                selected_count=3,
                type_counts={"user_profile": 1, "episodic_memory": 2},
                total_chars=420,
            )
        )
        task_panel.resize(520, 680)
        task_panel._add_message_to_display(
            "今天有点累，但还想把项目收个尾。",
            is_user=True,
        )
        task_panel._add_message_to_display(
            "那我们只抓最重要的一件事。我先帮你拆成三步，你随时可以停下来。",
            is_user=False,
        )
        rendered.append(_render(app, task_panel, output_dir / "task-panel.png"))

        region_path = Path(temp_dir) / "screen-region-preview.png"
        Image.new("RGB", (520, 260), (242, 226, 209)).save(region_path, "PNG")
        task_panel.attach_screen_region(
            ScreenRegionCapture(
                id="preview-region",
                path=region_path,
                bounds=ScreenRegionBounds(x=310, y=190, width=520, height=260),
                screen_name="Preview display",
                pixel_width=520,
                pixel_height=260,
                size_bytes=region_path.stat().st_size,
                captured_at=now,
                expires_at=now + timedelta(minutes=5),
            )
        )
        rendered.append(
            _render(
                app,
                task_panel,
                output_dir / "task-panel-screen-region.png",
            )
        )
        task_panel._clear_image_preview(notify=False)

        desktop_path = Path(temp_dir) / "desktop-preview.png"
        desktop = Image.new("RGB", (960, 600), (231, 221, 209))
        draw = ImageDraw.Draw(desktop)
        draw.rounded_rectangle((48, 56, 912, 544), radius=22, fill=(251, 248, 244))
        draw.rectangle((48, 56, 912, 106), fill=(113, 84, 65))
        draw.rounded_rectangle((90, 150, 430, 492), radius=18, fill=(242, 226, 209))
        draw.rounded_rectangle((470, 150, 868, 280), radius=18, fill=(255, 255, 255))
        draw.rounded_rectangle((470, 310, 868, 492), radius=18, fill=(255, 255, 255))
        desktop.save(desktop_path, "PNG")
        selector = ScreenRegionSelector(
            task_panel,
            background=QPixmap(str(desktop_path)),
            screen_geometry=QRect(0, 0, 960, 600),
            screen_name="Preview display",
        )
        selector._selection = QRect(456, 132, 430, 176)
        rendered.append(
            _render(
                app,
                selector,
                output_dir / "screen-region-selector.png",
            )
        )

        card_panel = TaskCardPanel()
        card_panel.show_card(
            TaskCardModel(
                title="整理项目发布清单",
                status="running",
                short_result="正在核对测试、版本与发布说明",
                meta_text="第 1 次尝试 · 已用 18 秒 · 预计还需 42 秒",
                progress=0.42,
                details="1. 全量测试\n2. 生成变更摘要\n3. 等待发布确认",
                stage_summary="工作阶段 3/5 · 等待 1 · 关键路径约 18 秒",
                steps=[
                    TaskStep(
                        text="规划受控电脑操作",
                        status="success",
                        detail="最多 8 个动作",
                        duration_text="1.4 秒",
                    ),
                    TaskStep(
                        text="获得本次操作授权",
                        status="success",
                        detail="有效期 10 分钟",
                        duration_text="4.8 秒",
                        critical=True,
                    ),
                    TaskStep(
                        text="观察并定位当前界面",
                        status="success",
                        detail="融合视觉与原生控件，找到 7 个候选目标",
                        duration_text="6.5 秒",
                        critical=True,
                    ),
                    TaskStep(
                        text="验证执行结果",
                        status="warning",
                        detail="等待确认保存后的可见变化",
                        duration_text="已用 2.1 秒",
                        waiting_text="等待：执行输入动作",
                        critical=True,
                    ),
                    TaskStep(
                        text="验证执行结果",
                        status="running",
                        detail="发布设置已经保存",
                    ),
                ],
            )
        )
        rendered.append(_render(app, card_panel, output_dir / "task-card.png"))
        card_panel.show_card(
            TaskCardModel(
                title="这项工作已安全暂停",
                status="cancelled",
                short_result="应用退出前已停止执行，没有自动重放。",
                meta_text="第 1 次尝试 · 已用 18 秒 · 可安全重新尝试",
                progress=0.42,
                details="暂停原因：应用退出时撤销了本次运行授权。",
                steps=[
                    TaskStep(
                        text="观察并定位当前界面",
                        status="success",
                        duration_text="6.5 秒",
                    ),
                    TaskStep(
                        text="执行输入动作",
                        status="warning",
                        detail="应用退出，动作未继续",
                    ),
                ],
                available_actions=["retry"],
            )
        )
        rendered.append(
            _render(
                app,
                card_panel,
                output_dir / "task-card-cancelled.png",
            )
        )

        task_runs = TaskRunService(settings, TaskRepository(db_module._db))
        completed_task = TaskRecord(
            id="preview-completed-run",
            input_text="整理项目发布清单",
            status=TaskStatus.QUEUED,
            session_id="preview-session",
        )
        task_runs.create(completed_task)
        task_runs.start(completed_task.id)
        task_runs.progress(
            completed_task.id,
            key="verify-output",
            title="验证执行结果",
            detail="测试、版本和发布说明已经核对",
            step_index=3,
            max_actions=4,
        )
        task_runs.complete(
            completed_task.id,
            TaskResult(
                task_id=completed_task.id,
                success=True,
                summary="发布清单已经整理完成",
                usage_evidence=ModelUsageEvidence(
                    provider_model="preview-model",
                    prompt_tokens=1_680,
                    completion_tokens=420,
                    cached_tokens=640,
                    source=ModelUsageSource.PROVIDER,
                ),
            ),
        )
        interrupted_task = TaskRecord(
            id="preview-interrupted-run",
            input_text="继续同步远程发布状态",
            status=TaskStatus.QUEUED,
            session_id="preview-session",
        )
        task_runs.create(interrupted_task)
        task_runs.start(interrupted_task.id)
        task_runs.progress(
            interrupted_task.id,
            key="wait-remote",
            title="等待远程状态",
            detail="已经完成本地核对，尚未执行外部变更",
        )
        task_runs.interrupt_incomplete()
        task_runs.retry(interrupted_task.id)

        traces = ExecutionTraceRepository(db_module._db)
        traces.record(
            "preview-session",
            "读取发布说明",
            "read_file",
            {"path": "README.md"},
            "success",
            result_summary="已读取并完成核对",
        )
        traces.record(
            "preview-session",
            "检查远程状态",
            "browser_observe",
            {"target": "发布页"},
            "failed",
            result_summary="页面暂时不可用，未执行后续操作",
        )
        work_record = ObservabilityPanel(
            ObservabilityService(task_runs=task_runs, trace_repo=traces)
        )
        work_record.resize(1040, 720)
        rendered.append(_render(app, work_record, output_dir / "work-record.png"))

        settings_window = SettingsWindow(settings)
        settings_window.resize(820, 680)
        rendered.append(_render(app, settings_window, output_dir / "settings-window.png"))
        settings_window._tabs.setCurrentIndex(3)
        rendered.append(_render(app, settings_window, output_dir / "settings-companion.png"))
        settings_window._companion_scroll.ensureWidgetVisible(
            settings_window._feedback_summary_label,
            0,
            80,
        )
        rendered.append(_render(app, settings_window, output_dir / "settings-feedback.png"))
        settings_window._tabs.setCurrentIndex(4)
        rendered.append(_render(app, settings_window, output_dir / "settings-computer-use.png"))

        codex_pets_root = Path(temp_dir) / ".codex" / "pets"
        _create_preview_codex_pet(codex_pets_root)
        codex_library = CodexPetLibraryDialog(CodexPetService(settings.data_dir, codex_pets_root))
        codex_library.resize(720, 540)
        _wait_until(
            lambda: codex_library._discovery_thread is None,
            "Codex pet preview discovery",
        )
        rendered.append(_render(app, codex_library, output_dir / "codex-pets.png"))

        memory_repo = MemoryRepository(db_module._db)
        memory_service = MemoryService(settings, memory_repo)
        memory_control = MemoryControlService(
            settings,
            memory_service=memory_service,
            repo=memory_repo,
        )
        memory_service.save_memory(
            MemoryItem(
                id="preview-preference",
                memory_type=MemoryType.USER_PROFILE,
                title="沟通偏好",
                content="先给我清晰结论，再补充真正有用的细节。",
                source="ai_patch",
                confidence=0.84,
            )
        )
        memory_control.revise_memory(
            "preview-preference",
            "先给我清晰结论，再补充真正有用的细节。",
            "这是我们多次协作后确认的沟通方式",
        )
        memory_service.save_memory(
            MemoryItem(
                id="preview-moment",
                memory_type=MemoryType.EPISODIC_MEMORY,
                title="第一次一起完成发布",
                content="我们核对了测试、版本和发布说明，顺利完成了交付。",
                source="exit_analysis",
                confidence=0.91,
            )
        )
        memory_service.save_memory(
            MemoryItem(
                id="preview-old-focus",
                memory_type=MemoryType.USER_PROFILE,
                title="适合专注的时间",
                content="上午更适合处理复杂任务。",
                source="ai_patch",
            )
        )
        memory_service.save_memory(
            MemoryItem(
                id="preview-new-focus",
                memory_type=MemoryType.USER_PROFILE,
                title="适合专注的时间",
                content="最近晚上更容易进入专注状态。",
                source="ai_patch",
            )
        )
        memory_repo.save_conflict_candidate(
            ConflictCandidate(
                id="preview-conflict",
                existing_item_id="preview-old-focus",
                new_item_id="preview-new-focus",
                conflict_type=ConflictType.DIFFERENT_VALUE,
            )
        )
        memory_console = MemoryConsoleWindow(memory_control)
        memory_console.resize(1220, 790)
        rendered.append(_render(app, memory_console, output_dir / "memory-console.png"))
        memory_service.record_recall(
            "preview-memory-recall",
            "preview-session",
            [
                MemoryContextEvidence(
                    memory_id="preview-preference",
                    memory_type=MemoryType.USER_PROFILE,
                    reason="用户档案优先级",
                    chars=54,
                ),
                MemoryContextEvidence(
                    memory_id="preview-moment",
                    memory_type=MemoryType.EPISODIC_MEMORY,
                    reason="命中 2 个请求关键词",
                    chars=72,
                ),
            ],
        )
        memory_control.record_recall_feedback(
            "preview-memory-recall",
            "preview-preference",
            MemoryRecallFeedback.HELPFUL,
        )
        recall_review = MemoryRecallReviewDialog(
            memory_control,
            "preview-memory-recall",
        )
        rendered.append(
            _render(
                app,
                recall_review,
                output_dir / "memory-recall-review.png",
            )
        )

        portability_path = Path(temp_dir) / "lobuddy-memory-preview.json"
        memory_control.export_memory_package(portability_path)
        portability_settings = Settings(
            llm_api_key="preview",
            data_dir=Path(temp_dir) / "portability-target",
            workspace_path=Path(temp_dir) / "portability-workspace",
            memory_enable_migration=False,
            user_name="",
        )
        portability_repo = MemoryRepository(Database(portability_settings))
        portability_control = MemoryControlService(
            portability_settings,
            repo=portability_repo,
        )
        portability_dialog = MemoryImportReviewDialog(
            portability_control.inspect_memory_package(portability_path)
        )
        rendered.append(
            _render(
                app,
                portability_dialog,
                output_dir / "memory-portability-review.png",
            )
        )

        skill_manager = SkillManager(settings, db_module._db)
        SkillEvolutionService(settings, skill_manager).consider_task(
            success=True,
            task_input="整理项目发布清单并核对测试结果",
            tools_used=["read_file", "write_file"],
            output_length=860,
            session_id="preview-session",
            task_id="preview-task",
            privacy_active=False,
            has_image=False,
        )
        skill_lab = SkillLabPanel(skill_manager, settings)
        skill_lab.resize(860, 680)
        rendered.append(_render(app, skill_lab, output_dir / "skill-lab.png"))

        privacy = PrivacyModeManager(settings)
        companion = CompanionRuntime(settings, db=db_module._db)
        companion.submit_check_in(
            CompanionMood.TIRED,
            CompanionEnergy.LOW,
            CompanionSupportMode.PRACTICAL,
        )
        preview_pet = PetRepository(db_module._db).get_or_create_pet()
        preview_pet.personality.technical_skill = 58.5
        preview_pet.personality.creativity = 54.0
        preview_pet.personality.diligence = 56.3
        preview_pet.personality.interaction_counts = {
            "technical_skill:task_analysis": 4,
            "creativity:task_analysis": 2,
            "diligence:task_analysis": 21,
        }
        preview_pets = PetRepository(db_module._db)
        preview_pets.save_pet(preview_pet)
        personality_evolution = PersonalityEvolution(pets=preview_pets)
        personality_evolution.version_count()
        personality_evolution.evolve_from_task(
            TaskRecord(
                id="preview-personality-design",
                input_text="design and build a creative frontend companion experience",
                status=TaskStatus.SUCCESS,
                difficulty=TaskDifficulty.MEDIUM,
            )
        )
        personality_evolution.evolve_from_task(
            TaskRecord(
                id="preview-personality-debug",
                input_text="debug the Python API and explain why the test failed",
                status=TaskStatus.SUCCESS,
                difficulty=TaskDifficulty.COMPLEX,
            )
        )
        relationship_service = RelationshipRhythmService(
            memory_control,
            companion,
            pets=preview_pets,
            privacy=privacy,
            personality_evolution=personality_evolution,
        )
        relationship_rhythm = RelationshipRhythmDialog(
            relationship_service,
            session_id_provider=lambda: "preview-session",
            personality_evolution=personality_evolution,
        )
        relationship_rhythm.resize(980, 790)
        rendered.append(
            _render(
                app,
                relationship_rhythm,
                output_dir / "relationship-rhythm.png",
            )
        )
        personality_history = PersonalityEvolutionDialog(personality_evolution)
        personality_history.resize(980, 690)
        rendered.append(
            _render(
                app,
                personality_history,
                output_dir / "personality-evolution.png",
            )
        )
        computer_repo = ComputerUseRepository(db_module._db)
        preview_plan, _ = computer_repo.create_or_resume_plan(
            session_id="preview-session",
            task_id="preview-task",
            goal="完成发布前核对",
            target_app="editor",
            allowed_actions=[ComputerActionType.CLICK, ComputerActionType.PRESS_KEY],
            max_actions=8,
        )
        computer_repo.authorize(
            preview_plan.id,
            utc_now() + timedelta(minutes=8),
        )
        data_control = DataControlDialog(
            DataControlCenter(
                settings,
                privacy=privacy,
                chat_repo=preview_chat_repo,
                computer_repo=computer_repo,
                screen_regions=ScreenRegionRuntime(
                    settings,
                    root=Path(temp_dir) / "regions",
                    draft_roots=[Path(temp_dir)],
                    file_hardener=lambda _path: None,
                ),
                companion=companion,
                memories=memory_control,
                skills=skill_manager,
            ),
            "preview-session",
        )
        data_control.resize(940, 760)
        rendered.append(_render(app, data_control, output_dir / "data-control.png"))

        recovery_task = TaskRecord(
            id="preview-recovery-run",
            input_text="完成发布前核对并保存设置",
            status=TaskStatus.QUEUED,
            session_id="preview-session",
        )
        task_runs.create(recovery_task)
        task_runs.start(recovery_task.id)
        task_runs.progress(
            recovery_task.id,
            key="open-settings",
            title="打开发布设置",
            detail="已经进入设置页面，尚未完成最终核对",
            status="success",
            step_index=2,
            max_actions=4,
        )
        task_runs.complete(
            recovery_task.id,
            TaskResult(
                task_id=recovery_task.id,
                success=False,
                summary="最终核对尚未完成",
                error_message="模型服务暂时不可用",
            ),
        )
        recovery_plan, _ = computer_repo.create_or_resume_plan(
            session_id="preview-session",
            task_id=recovery_task.id,
            goal="完成发布前核对",
            target_app="editor",
            allowed_actions=[ComputerActionType.CLICK],
            max_actions=4,
        )
        recovery_plan = computer_repo.authorize(
            recovery_plan.id,
            utc_now() + timedelta(minutes=6),
        )
        computer_repo.record_action(
            recovery_plan,
            ComputerAction(
                action=ComputerActionType.CLICK,
                x=120,
                y=90,
                description="打开发布设置",
            ),
            success=True,
            result_summary="设置页面已打开",
        )
        traces.record(
            recovery_task.id,
            "computer_use",
            "computer_act",
            {"action": "click"},
            "completed",
        )
        recovery_dialog = TaskRecoveryDialog(
            TaskRecoveryService(
                settings,
                task_runs,
                computers=computer_repo,
                traces=traces,
            ).review(recovery_task.id)
        )
        recovery_dialog.resize(740, 570)
        rendered.append(_render(app, recovery_dialog, output_dir / "task-recovery.png"))

        for widget in (
            pet,
            quick_menu,
            check_in,
            task_panel,
            selector,
            card_panel,
            work_record,
            settings_window,
            codex_library,
            memory_console,
            portability_dialog,
            skill_lab,
            data_control,
            recovery_dialog,
        ):
            widget.close()
        app.processEvents()
        appearance.custom_asset_path = custom_asset_path
        appearance.custom_asset_type = custom_asset_type
        appearance.custom_asset_source = custom_asset_source
        appearance.custom_asset_name = custom_asset_name
        appearance.codex_pet_id = codex_pet_id
        appearance.custom_state_asset_paths = custom_state_asset_paths
        db_module._db = None

    return rendered


def render_screen_region_previews(output_dir: Path) -> list[Path]:
    """Render only the two region-ask surfaces for fast visual iteration."""
    output_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    rendered: list[Path] = []

    with tempfile.TemporaryDirectory(prefix="lobuddy-region-preview-") as temp_dir:
        settings = Settings(
            llm_api_key="preview",
            llm_multimodal_model="preview-vision",
            data_dir=Path(temp_dir) / "data",
            workspace_path=Path(temp_dir) / "workspace",
        )
        db_module._db = Database(settings)
        db_module._db.init_database()
        panel = TaskPanel(ChatRepository())
        panel.set_settings(settings)
        panel.resize(520, 680)

        now = datetime.now().replace(second=0, microsecond=0)
        region_path = Path(temp_dir) / "screen-region-preview.png"
        Image.new("RGB", (520, 260), (242, 226, 209)).save(region_path, "PNG")
        panel.attach_screen_region(
            ScreenRegionCapture(
                id="preview-region",
                path=region_path,
                bounds=ScreenRegionBounds(x=310, y=190, width=520, height=260),
                screen_name="Preview display",
                pixel_width=520,
                pixel_height=260,
                size_bytes=region_path.stat().st_size,
                captured_at=now,
                expires_at=now + timedelta(minutes=5),
            )
        )
        rendered.append(
            _render(
                app,
                panel,
                output_dir / "task-panel-screen-region.png",
            )
        )

        desktop_path = Path(temp_dir) / "desktop-preview.png"
        desktop = Image.new("RGB", (960, 600), (231, 221, 209))
        draw = ImageDraw.Draw(desktop)
        draw.rounded_rectangle((48, 56, 912, 544), radius=22, fill=(251, 248, 244))
        draw.rectangle((48, 56, 912, 106), fill=(113, 84, 65))
        draw.rounded_rectangle((90, 150, 430, 492), radius=18, fill=(242, 226, 209))
        draw.rounded_rectangle((470, 150, 868, 280), radius=18, fill=(255, 255, 255))
        draw.rounded_rectangle((470, 310, 868, 492), radius=18, fill=(255, 255, 255))
        desktop.save(desktop_path, "PNG")
        selector = ScreenRegionSelector(
            panel,
            background=QPixmap(str(desktop_path)),
            screen_geometry=QRect(0, 0, 960, 600),
            screen_name="Preview display",
        )
        selector._selection = QRect(456, 132, 430, 176)
        rendered.append(
            _render(
                app,
                selector,
                output_dir / "screen-region-selector.png",
            )
        )

        selector.close()
        panel.close()
        app.processEvents()
        db_module._db = None

    return rendered


def _create_preview_codex_pet(pets_root: Path) -> None:
    directory = pets_root / "warm-pixel"
    directory.mkdir(parents=True)
    sheet = Image.new("RGBA", CodexPetService.SHEET_SIZES[1], (0, 0, 0, 0))
    for row, durations in (value for value in CodexPetService.ANIMATIONS.values()):
        for column in range(len(durations)):
            left = column * CodexPetService.FRAME_WIDTH + 52
            top = row * CodexPetService.FRAME_HEIGHT + 52
            sheet.paste((255, 138, 61, 255), (left, top, left + 88, top + 112))
            sheet.paste((74, 46, 31, 255), (left + 18, top + 24, left + 28, top + 34))
            sheet.paste((74, 46, 31, 255), (left + 60, top + 24, left + 70, top + 34))
    sheet.save(directory / "spritesheet.png")
    (directory / "pet.json").write_text(
        json.dumps(
            {
                "displayName": "暖暖像素搭档",
                "description": "从 Codex 宠物库来到 Lobuddy，随时准备陪你完成下一件事。",
                "spriteVersionNumber": 1,
                "spritesheetPath": "spritesheet.png",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _render(app: QApplication, widget, path: Path) -> Path:
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.show()
    app.processEvents()
    if not widget.grab().save(str(path), "PNG"):
        raise RuntimeError(f"Failed to render {path}")
    return path


def _wait_until(predicate, label: str, timeout_ms: int = 15_000) -> None:
    if predicate():
        return
    loop = QEventLoop()

    def check() -> None:
        if predicate():
            loop.quit()
        else:
            QTimer.singleShot(20, check)

    QTimer.singleShot(0, check)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    if not predicate():
        raise RuntimeError(f"Timed out waiting for {label}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/ui-preview"),
    )
    parser.add_argument(
        "--screen-region-only",
        action="store_true",
        help="Render only the Screen Region Ask selector and composer preview",
    )
    args = parser.parse_args()
    renderer = render_screen_region_previews if args.screen_region_only else render_previews
    for path in renderer(args.output_dir.resolve()):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
