"""Service wiring for Lobuddy — creates & wires backend services to TaskManager."""

from app.config import Settings
from core.companion.runtime import CompanionRuntime
from core.data_control.service import DataControlCenter
from core.focus.focus_companion import FocusCompanion
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_maintenance import MemoryMaintenance
from core.memory.memory_service import MemoryService
from core.memory.memory_write_gateway import MemoryWriteGateway
from core.memory.privacy_mode import PrivacyModeManager
from core.personality.evolution import PersonalityEvolution
from core.relationship.rhythm_service import RelationshipRhythmService
from core.screen_region.runtime import ScreenRegionRuntime
from core.skills.skill_maintenance import SkillMaintenance
from core.skills.skill_manager import SkillManager
from core.services.runtime_maintenance import RuntimeMaintenance
from core.storage.chat_repo import ChatRepository
from core.storage.computer_use_repo import ComputerUseRepository
from core.storage.pet_repo import PetRepository
from core.storage.task_repo import TaskRepository
from ui.theme import ThemePreset


class Services:
    """Bundle of all backend services."""

    def __init__(self):
        self.memory_service: MemoryService | None = None
        self.memory_gateway: MemoryWriteGateway | None = None
        self.memory_maintenance: MemoryMaintenance | None = None
        self.memory_control: MemoryControlService | None = None
        self.personality_evolution: PersonalityEvolution | None = None
        self.relationship_rhythm: RelationshipRhythmService | None = None
        self.privacy_manager: PrivacyModeManager | None = None
        self.companion_runtime: CompanionRuntime | None = None
        self.screen_region_runtime: ScreenRegionRuntime | None = None
        self.data_control: DataControlCenter | None = None
        self.skill_manager: SkillManager | None = None
        self.skill_maintenance: SkillMaintenance | None = None
        self.focus_companion: FocusCompanion | None = None
        self.runtime_maintenance: RuntimeMaintenance | None = None
        # Compatibility seam for status panels. Scheduling ownership lives in
        # RuntimeMaintenance.
        self.maintenance_scheduler = None
        self.observability = None
        self._hitl_provider = None


def apply_theme_from_settings(theme_mgr, settings: Settings) -> None:
    """Apply theme from settings to ThemeManager singleton."""
    preset_map = {
        "cozy_orange": ThemePreset.COZY_ORANGE,
        "sakura_pink": ThemePreset.SAKURA_PINK,
        "mint_green": ThemePreset.MINT_GREEN,
        "night_companion": ThemePreset.NIGHT_COMPANION,
    }
    preset = preset_map.get(settings.theme_preset, ThemePreset.COZY_ORANGE)

    custom_overrides: dict[str, str] = {}
    if settings.theme_primary_color:
        custom_overrides["primary"] = settings.theme_primary_color
    if settings.theme_background_color:
        custom_overrides["background"] = settings.theme_background_color
    if settings.theme_accent_color:
        custom_overrides["border_focus"] = settings.theme_accent_color

    if custom_overrides:
        theme_mgr.apply_theme(preset, custom_overrides)
    else:
        theme_mgr.set_preset(preset)


def create_services(
    settings: Settings,
    task_manager,
    *,
    chat_repo: ChatRepository | None = None,
) -> Services:
    """Create all backend services and wire them to the TaskManager adapter.

    Returns a Services bundle holding all created service instances.
    """
    svc = Services()

    svc.privacy_manager = PrivacyModeManager(settings)
    svc.companion_runtime = CompanionRuntime(settings)
    svc.screen_region_runtime = ScreenRegionRuntime(settings)
    svc.memory_service = MemoryService(settings, privacy=svc.privacy_manager)
    svc.memory_gateway = MemoryWriteGateway(
        svc.memory_service, settings, privacy=svc.privacy_manager
    )
    svc.memory_control = MemoryControlService(
        settings=settings,
        memory_service=svc.memory_service,
        gateway=svc.memory_gateway,
    )
    personality_pets = PetRepository()
    svc.personality_evolution = PersonalityEvolution(pets=personality_pets)
    svc.relationship_rhythm = RelationshipRhythmService(
        svc.memory_control,
        svc.companion_runtime,
        pets=personality_pets,
        privacy=svc.privacy_manager,
        personality_evolution=svc.personality_evolution,
    )
    task_manager.adapter.set_privacy_manager(svc.privacy_manager)
    task_manager.adapter.set_memory_service(svc.memory_service)
    task_manager.adapter.set_memory_gateway(svc.memory_gateway)

    svc.memory_maintenance = MemoryMaintenance(settings, memory_service=svc.memory_service)

    svc.skill_manager = SkillManager(settings)
    task_manager.adapter.set_skill_manager(svc.skill_manager)

    svc.skill_maintenance = SkillMaintenance(settings, manager=svc.skill_manager)
    svc.data_control = DataControlCenter(
        settings,
        privacy=svc.privacy_manager,
        chat_repo=chat_repo or ChatRepository(),
        computer_repo=ComputerUseRepository(),
        screen_regions=svc.screen_region_runtime,
        companion=svc.companion_runtime,
        memories=svc.memory_control,
        skills=svc.skill_manager,
    )

    from ui.hitl_approval_provider import QtHitlApprovalProvider

    hitl_provider = QtHitlApprovalProvider(parent_window=None)
    hitl_provider.approval_requested.connect(hitl_provider._show_dialog)
    task_manager.adapter.set_hitl_approval_provider(hitl_provider)
    svc._hitl_provider = hitl_provider

    svc.focus_companion = FocusCompanion(settings)

    from core.storage.execution_trace_repository import ExecutionTraceRepository
    from core.storage.hitl_approval_repo import HitlApprovalRepository
    from core.services.observability_service import ObservabilityService

    trace_repo = ExecutionTraceRepository()
    svc.runtime_maintenance = RuntimeMaintenance(
        settings,
        memory_maintenance=svc.memory_maintenance,
        skill_maintenance=svc.skill_maintenance,
        trace_repository=trace_repo,
    )
    svc.maintenance_scheduler = svc.runtime_maintenance.scheduler
    svc.runtime_maintenance.start()

    hitl_repo = HitlApprovalRepository()
    task_repo = TaskRepository()
    token_meter = getattr(task_manager.adapter, "_token_meter", None)
    svc.observability = ObservabilityService(
        token_meter=token_meter,
        trace_repo=trace_repo,
        hitl_repo=hitl_repo,
        task_repo=task_repo,
        task_runs=task_manager.task_runs,
    )

    return svc
