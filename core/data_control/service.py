"""Deep Module for explaining and revoking current-session data access."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from core.companion.runtime import CompanionRuntime
from core.config import Settings
from core.data_control.models import (
    DataControlAction,
    DataControlCard,
    DataControlFact,
    DataControlResult,
    DataControlSnapshot,
    DataControlTone,
)
from core.memory.memory_control_service import MemoryControlService
from core.memory.privacy_mode import PrivacyModeManager
from core.screen_region.runtime import ScreenRegionRuntime
from core.skills.skill_manager import SkillManager
from core.storage.chat_repo import ChatRepository
from core.storage.computer_use_repo import ComputerUseRepository


class DataControlCenter:
    """One Interface over collection, retention, sharing, grants, and revocation."""

    def __init__(
        self,
        settings: Settings,
        *,
        privacy: PrivacyModeManager,
        chat_repo: ChatRepository,
        computer_repo: ComputerUseRepository,
        screen_regions: ScreenRegionRuntime,
        companion: CompanionRuntime,
        memories: MemoryControlService,
        skills: SkillManager,
    ) -> None:
        self._settings = settings
        self._privacy = privacy
        self._chat_repo = chat_repo
        self._computer_repo = computer_repo
        self._screen_regions = screen_regions
        self._companion = companion
        self._memories = memories
        self._skills = skills

    def update_settings(self, settings: Settings) -> None:
        self._settings = settings

    def snapshot(self, session_id: str) -> DataControlSnapshot:
        """Project effective state without exposing chat, memory, or screen content."""
        session_id = self._require_session(session_id)
        privacy_active = self._privacy.is_privacy_active(session_id)
        if privacy_active:
            headline = "本次对话受隐私模式保护"
            detail = "不会读取历史记忆或生成长期记忆，技能也不会从本次任务学习。" "对话是否保存在本机仍由下方“对话记录”单独说明。"
        else:
            headline = "本次对话使用你的常规数据设置"
            detail = "Lobuddy 只按下方状态观察、保留和调用数据；电脑操作仍需要" "单独授权，并可随时撤销。"
        return DataControlSnapshot(
            session_id=session_id,
            privacy_active=privacy_active,
            headline=headline,
            detail=detail,
            cards=[
                self._chat_card(session_id, privacy_active),
                self._memory_card(privacy_active),
                self._checkin_card(),
                self._observation_card(privacy_active),
                self._screen_region_card(),
                self._computer_use_card(session_id),
                self._skill_card(privacy_active),
                self._model_card(),
            ],
        )

    def execute(
        self,
        action: DataControlAction | str,
        session_id: str,
    ) -> DataControlResult:
        """Execute one narrow revocation and return the refreshed projection."""
        session_id = self._require_session(session_id)
        parsed = DataControlAction(action)
        changed_count = 0

        if parsed == DataControlAction.ENABLE_SESSION_PRIVACY:
            changed_count = int(not self._privacy.is_privacy_active(session_id))
            self._privacy.enable_privacy(session_id)
            message = "已为当前对话开启隐私模式。"
        elif parsed == DataControlAction.DISABLE_SESSION_PRIVACY:
            changed_count = int(self._privacy.is_privacy_active(session_id))
            self._privacy.disable_privacy(session_id)
            message = "当前对话已恢复常规数据设置。"
        elif parsed == DataControlAction.REVOKE_COMPUTER_USE:
            changed_count = self._computer_repo.revoke_authorizations(session_id)
            message = f"已暂停 {changed_count} 个电脑操作计划并撤销授权。" if changed_count else "当前对话没有可撤销的电脑操作授权。"
        elif parsed == DataControlAction.CLEAR_SCREEN_REGIONS:
            changed_count = self._screen_regions.clear_all()
            message = f"已删除 {changed_count} 份临时屏幕选区。" if changed_count else "当前没有临时屏幕选区。"
        elif parsed == DataControlAction.CLEAR_COMPANION_CHECKIN:
            changed_count = self._companion.clear_check_in()
            message = "已清除当前状态。" if changed_count else "当前没有已分享的状态。"
        elif parsed == DataControlAction.CLEAR_SESSION_CHAT:
            changed_count = self._chat_repo.clear_session(session_id)
            message = f"已从本机删除当前对话的 {changed_count} 条消息。" if changed_count else "当前对话没有已保存的消息。"
        else:
            raise ValueError(f"Unsupported Data Control action: {parsed}")

        return DataControlResult(
            action=parsed,
            changed_count=changed_count,
            message=message,
            snapshot=self.snapshot(session_id),
        )

    def _chat_card(self, session_id: str, privacy_active: bool) -> DataControlCard:
        count = self._chat_repo.count_messages(session_id)
        retained = not privacy_active or self._settings.privacy_mode_allow_chat_history
        if retained:
            state = f"本机保存 · {count} 条"
            summary = "当前对话消息保存在本机，便于恢复会话和查看记录。"
            tone = DataControlTone.ATTENTION if privacy_active else DataControlTone.ACTIVE
        else:
            state = "本次不保存"
            summary = "隐私模式已阻止新消息写入本机；已有消息仍可由你手动清除。"
            tone = DataControlTone.PROTECTED
        return DataControlCard(
            key="chat_history",
            group="本次对话",
            title="对话记录",
            state_label=state,
            summary=summary,
            tone=tone,
            facts=[
                DataControlFact(label="采集", value="你发送的消息与助手回复"),
                DataControlFact(label="保存", value="仅本机 SQLite；可清除当前对话"),
                DataControlFact(label="范围", value="只清除消息，不会连带删除结构化记忆"),
            ],
            action=DataControlAction.CLEAR_SESSION_CHAT if count else None,
            action_label="清除当前对话" if count else "",
            requires_confirmation=True,
        )

    def _memory_card(self, privacy_active: bool) -> DataControlCard:
        summary = self._memories.get_status_summary()
        active = summary.get("active", 0)
        review = summary.get("needs_review", 0)
        enabled = self._settings.memory_profile_inject_enabled and not privacy_active
        if enabled:
            state = f"按需使用 · {active} 条"
            detail = "仅相关、有效且在提示预算内的记忆会进入任务上下文。"
            tone = DataControlTone.ATTENTION if review else DataControlTone.ACTIVE
        else:
            state = "本次不使用"
            detail = "隐私模式阻止历史记忆读取与长期写入。" if privacy_active else "记忆上下文已在设置中关闭。"
            tone = DataControlTone.PROTECTED if privacy_active else DataControlTone.INACTIVE
        return DataControlCard(
            key="structured_memory",
            group="本次对话",
            title="结构化记忆",
            state_label=state,
            summary=detail,
            tone=tone,
            facts=[
                DataControlFact(label="保存", value="净化后的事实与经历保存在本机"),
                DataControlFact(label="使用", value="当前请求相关时才会按预算召回"),
                DataControlFact(label="待确认", value=f"{review} 条；可在记忆档案中裁决"),
            ],
            secondary_route="memory",
            secondary_label="打开记忆档案",
        )

    def _checkin_card(self) -> DataControlCard:
        active = self._companion.active_check_in()
        if active is None:
            return DataControlCard(
                key="companion_checkin",
                group="本次对话",
                title="我现在的状态",
                state_label="未分享",
                summary="Lobuddy 不会从窗口或屏幕推断你的情绪。",
                tone=DataControlTone.INACTIVE,
                facts=[
                    DataControlFact(label="来源", value="只接受你主动选择的心情、精力与支持方式"),
                    DataControlFact(label="期限", value="自动过期；隐私模式下仅存内存"),
                ],
            )
        expires = self._format_time(active.expires_at)
        return DataControlCard(
            key="companion_checkin",
            group="本次对话",
            title="我现在的状态",
            state_label=f"已分享 · 至 {expires}",
            summary="这份明确分享只用于调整陪伴语气与主动关怀。",
            tone=DataControlTone.ACTIVE,
            facts=[
                DataControlFact(label="来源", value="由你主动选择，不做情绪识别"),
                DataControlFact(label="保存", value="只保留最新一份，并在到期后失效"),
            ],
            action=DataControlAction.CLEAR_COMPANION_CHECKIN,
            action_label="撤回当前状态",
        )

    def _observation_card(self, privacy_active: bool) -> DataControlCard:
        enabled = self._settings.observation_enabled
        if not enabled:
            state = "已关闭"
            summary = "不会读取空闲时长或前台应用信息。"
            tone = DataControlTone.INACTIVE
        elif privacy_active or not self._settings.observation_active_app_enabled:
            state = "最小观察"
            summary = "仅在本机使用活动与空闲信号；不读取前台应用名称。"
            tone = DataControlTone.PROTECTED
        else:
            state = "本机观察"
            summary = "使用空闲时长和前台可执行文件名判断是否适合轻声关怀。"
            tone = DataControlTone.ACTIVE
        return DataControlCard(
            key="activity_observation",
            group="感知与行动",
            title="活动观察",
            state_label=state,
            summary=summary,
            tone=tone,
            facts=[
                DataControlFact(label="不采集", value="屏幕内容、按键内容、情绪与诊断信息"),
                DataControlFact(label="保存", value="当前快照只在运行时使用"),
                DataControlFact(label="外发", value="主动观察本身不会调用模型"),
            ],
            secondary_route="settings",
            secondary_label="调整观察设置",
        )

    def _screen_region_card(self) -> DataControlCard:
        count = self._screen_regions.managed_capture_count
        if not self._screen_regions.available:
            state = "不可用"
            summary = "屏幕选区或多模态模型尚未启用。"
            tone = DataControlTone.INACTIVE
        elif count:
            state = f"临时保管 · {count} 份"
            summary = "只保管你明确框选的像素，用于一次视觉问题。"
            tone = DataControlTone.ATTENTION
        else:
            state = "按需启用"
            summary = "当前没有临时截图；不会后台截屏或保留屏幕历史。"
            tone = DataControlTone.ACTIVE
        return DataControlCard(
            key="screen_region",
            group="感知与行动",
            title="屏幕选区",
            state_label=state,
            summary=summary,
            tone=tone,
            facts=[
                DataControlFact(label="采集", value="仅你主动框选的区域"),
                DataControlFact(
                    label="期限",
                    value=f"未提交时最多保留 {self._settings.screen_region_ttl_seconds // 60} 分钟",
                ),
                DataControlFact(label="清理", value="完成、取消、替换、过期或退出时删除"),
            ],
            action=DataControlAction.CLEAR_SCREEN_REGIONS if count else None,
            action_label="删除临时选区" if count else "",
            requires_confirmation=bool(count),
        )

    def _computer_use_card(self, session_id: str) -> DataControlCard:
        plans = self._computer_repo.list_session_plans(session_id, limit=100)
        active = [plan for plan in plans if plan.authorization_is_valid()]
        if not self._settings.computer_use_enabled:
            state = "已关闭"
            summary = "当前设置不允许 Lobuddy 观察屏幕或控制鼠标键盘。"
            tone = DataControlTone.INACTIVE
        elif active:
            nearest = min(plan.authorized_until for plan in active if plan.authorized_until)
            state = f"已授权 · {len(active)} 个计划"
            summary = f"仅批准计划可执行；最近授权将在 {self._format_time(nearest)} 到期。"
            tone = DataControlTone.ATTENTION
        else:
            state = "每个计划单独授权"
            summary = "没有有效授权；开始电脑操作前会展示目标、动作范围和预算。"
            tone = DataControlTone.PROTECTED
        return DataControlCard(
            key="computer_use",
            group="感知与行动",
            title="电脑操作",
            state_label=state,
            summary=summary,
            tone=tone,
            facts=[
                DataControlFact(label="授权", value="按计划、动作类型、步数和到期时间限制"),
                DataControlFact(label="记录", value="只留动作摘要与验证结果，不保存截图"),
                DataControlFact(label="高影响", value="发送、删除、支付等动作再次确认"),
            ],
            action=DataControlAction.REVOKE_COMPUTER_USE if active else None,
            action_label="立即撤销授权" if active else "",
            requires_confirmation=bool(active),
            secondary_route="settings",
            secondary_label="调整操作设置",
        )

    def _skill_card(self, privacy_active: bool) -> DataControlCard:
        stats = self._skills.get_candidate_stats()
        pending = stats.get("pending", 0)
        enabled = self._settings.skill_auto_candidate_enabled and not privacy_active
        if enabled:
            state = f"只生成候选 · {pending} 待审"
            summary = "成功工作流只能生成净化后的候选，评测通过并由你批准后才可启用。"
            tone = DataControlTone.ATTENTION if pending else DataControlTone.ACTIVE
        else:
            state = "本次不学习" if privacy_active else "已关闭"
            summary = "隐私模式阻止从本次任务提取技能候选。" if privacy_active else "自动生成技能候选已在设置中关闭。"
            tone = DataControlTone.PROTECTED if privacy_active else DataControlTone.INACTIVE
        return DataControlCard(
            key="skill_evolution",
            group="学习与模型",
            title="能力进化",
            state_label=state,
            summary=summary,
            tone=tone,
            facts=[
                DataControlFact(label="来源", value="仅净化后的成功工作流证据"),
                DataControlFact(label="门禁", value="隔离评测、内容哈希匹配、明确审批"),
                DataControlFact(label="禁止", value="不会读取私密结构化记忆生成技能"),
            ],
            secondary_route="skills",
            secondary_label="查看待审能力",
        )

    def _model_card(self) -> DataControlCard:
        host = self._provider_host(self._settings.llm_base_url)
        multimodal = self._settings.llm_multimodal_model.strip()
        return DataControlCard(
            key="model_sharing",
            group="学习与模型",
            title="模型服务",
            state_label=f"已配置 · {host}",
            summary="只有你发起对话或任务时，必要的请求上下文才会发送给已配置的模型服务。",
            tone=DataControlTone.ACTIVE,
            facts=[
                DataControlFact(label="可能外发", value="任务文本、附件和获准的工具上下文"),
                DataControlFact(
                    label="图像",
                    value="视觉问题可用多模态模型" if multimodal else "多模态模型未配置",
                ),
                DataControlFact(
                    label="密钥",
                    value="仅用于服务鉴权，不进入提示词、结构化记忆或日志",
                ),
            ],
            secondary_route="settings",
            secondary_label="管理模型设置",
        )

    @staticmethod
    def _provider_host(base_url: str) -> str:
        parsed = urlparse(base_url.strip())
        return parsed.hostname or "已配置服务"

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.astimezone().strftime("%H:%M")

    @staticmethod
    def _require_session(session_id: str) -> str:
        normalized = session_id.strip()
        if not normalized:
            raise ValueError("Data Control requires a current session")
        return normalized
