// Runtime schemas are the TS contract source; legacy fixtures only verify behavior.
import { z } from "zod";
import { unicodeString, dateTimeString, localTimestamp, trimUserText } from "./values.js";
import { validateWait, validateRepeat, validateDelegation, validateSource, validateSourceMove, validateWorkflow } from "./rules.js";

export const ConversationSummarySchema = z.object({
  "id": unicodeString({}),
  "session_id": unicodeString({}),
  "summary_type": unicodeString({}).default("rolling"),
  "content": unicodeString({}),
  "from_message_id": z.union([unicodeString({}), z.null()]).default(null),
  "to_message_id": z.union([unicodeString({}), z.null()]).default(null),
  "token_estimate": z.number().int().safe().min(0).default(0),
  "created_at": dateTimeString().default(localTimestamp),
  "updated_at": dateTimeString().default(localTimestamp),
});
export type ConversationSummary = z.infer<typeof ConversationSummarySchema>;

export const MemoryStatusSchema = z.enum(["active","needs_review","deprecated"]);
export type MemoryStatus = z.infer<typeof MemoryStatusSchema>;

export const MemoryTypeSchema = z.enum(["user_profile","system_profile","project_memory","conversation_summary","episodic_memory","procedural_memory"]);
export type MemoryType = z.infer<typeof MemoryTypeSchema>;

export const MemoryItemSchema = z.object({
  "id": unicodeString({}),
  "memory_type": MemoryTypeSchema,
  "scope": unicodeString({}).default("global"),
  "title": unicodeString({}).default(""),
  "content": unicodeString({}),
  "source": unicodeString({}).default("ai"),
  "source_session_id": z.union([unicodeString({}), z.null()]).default(null),
  "source_message_id": z.union([unicodeString({}), z.null()]).default(null),
  "confidence": z.number().min(0).max(1).default(0.8),
  "importance": z.number().min(0).max(1).default(0.5),
  "priority": z.number().int().safe().min(1).max(100).default(50),
  "status": MemoryStatusSchema.default("active"),
  "expires_at": z.union([dateTimeString(), z.null()]).default(null),
  "last_used_at": z.union([dateTimeString(), z.null()]).default(null),
  "created_at": dateTimeString().default(localTimestamp),
  "updated_at": dateTimeString().default(localTimestamp),
});
export type MemoryItem = z.infer<typeof MemoryItemSchema>;

export const SessionSearchResultSchema = z.object({
  "session_id": unicodeString({}),
  "message_id": unicodeString({}),
  "role": unicodeString({}),
  "content": unicodeString({}),
  "created_at": dateTimeString(),
  "score": z.number().default(0),
});
export type SessionSearchResult = z.infer<typeof SessionSearchResultSchema>;

export const SessionSearchResponseSchema = z.object({
  "results": z.array(SessionSearchResultSchema).default([]),
  "query": unicodeString({}).default(""),
  "scope": unicodeString({}).default(""),
  "total_found": z.number().int().safe().default(0),
  "total_shown": z.number().int().safe().default(0),
  "budget_exhausted": z.boolean().default(false),
  "note": unicodeString({}).default(""),
});
export type SessionSearchResponse = z.infer<typeof SessionSearchResponseSchema>;

export const ChatMessageSchema = z.object({
  "id": unicodeString({}),
  "session_id": unicodeString({}).default("default"),
  "role": unicodeString({}),
  "content": unicodeString({}),
  "image_path": z.union([unicodeString({}), z.null()]).default(null),
  "created_at": dateTimeString().default(localTimestamp),
});
export type ChatMessage = z.infer<typeof ChatMessageSchema>;

export const ChatSessionSchema = z.object({
  "id": unicodeString({}).default("default"),
  "pet_id": unicodeString({}).default("default"),
  "title": unicodeString({}).default("Chat History"),
  "created_at": dateTimeString().default(localTimestamp),
  "updated_at": dateTimeString().default(localTimestamp),
  "messages": z.array(ChatMessageSchema).default([]),
});
export type ChatSession = z.infer<typeof ChatSessionSchema>;

export const EvolutionStageSchema = z.union([z.literal(1),z.literal(2),z.literal(3)]);
export type EvolutionStage = z.infer<typeof EvolutionStageSchema>;

export const PetPersonalitySchema = z.object({
  "friendliness": z.number().min(0).max(100).default(50),
  "curiosity": z.number().min(0).max(100).default(50),
  "technical_skill": z.number().min(0).max(100).default(50),
  "creativity": z.number().min(0).max(100).default(50),
  "diligence": z.number().min(0).max(100).default(50),
  "interaction_counts": z.record(z.string(), z.number().int().safe()).default({}),
});
export type PetPersonality = z.infer<typeof PetPersonalitySchema>;

export const PetStateSchema = z.object({
  "id": unicodeString({}).default("default"),
  "name": unicodeString({}).default("Lobuddy"),
  "level": z.number().int().safe().min(1).max(10).default(1),
  "exp": z.number().int().safe().min(0).default(0),
  "evolution_stage": EvolutionStageSchema.default(1),
  "mood": unicodeString({}).default("happy"),
  "skin": unicodeString({}).default("default"),
  "personality": PetPersonalitySchema.default({"friendliness":50,"curiosity":50,"technical_skill":50,"creativity":50,"diligence":50,"interaction_counts":{}}),
  "created_at": dateTimeString().default(localTimestamp),
  "updated_at": dateTimeString().default(localTimestamp),
});
export type PetState = z.infer<typeof PetStateSchema>;

export const CompanionNoticeSchema = z.object({
  "notice_id": unicodeString({}),
  "text": unicodeString({}),
  "source": unicodeString({}),
  "expires_at": z.number(),
  "topic_id": unicodeString({}).default(""),
  "memory_id": unicodeString({}).default(""),
});
export type CompanionNotice = z.infer<typeof CompanionNoticeSchema>;

export const DelegationRunSchema = z.strictObject({
  "id": unicodeString({}),
  "delegation_id": unicodeString({}),
  "revision": z.number().int().safe(),
  "trigger_id": unicodeString({}),
  "workflow_version": unicodeString({}),
  "turn_id": unicodeString({}).default(""),
  "status": z.enum(["reserved","running","completed","cancelled","failed","interrupted"]).default("reserved"),
  "verdict": z.enum(["verified","failed","unknown"]).default("unknown"),
  "created_at": z.number(),
  "finished_at": z.union([z.number(), z.null()]).default(null),
  "reason": unicodeString({}).default("尚未执行"),
});
export type DelegationRun = z.infer<typeof DelegationRunSchema>;

export const DelegationWaitSchema = z.strictObject({
  "kind": z.enum(["none","time","user","event"]).default("none"),
  "at": z.union([z.number().min(0), z.null()]).default(null),
  "timezone": unicodeString({}).default("Asia/Shanghai"),
  "event": z.enum(["","app_returned","focus_finished","delegation_completed"]).default(""),
  "subject_id": unicodeString({"max":128}).default(""),
}).superRefine(validateWait);
export type DelegationWait = z.infer<typeof DelegationWaitSchema>;

export const RepeatRuleSchema = z.strictObject({
  "frequency": z.enum(["once","daily","weekly"]).default("once"),
  "local_time": unicodeString({"pattern":"^$|^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"}).default(""),
  "weekdays": z.array(z.number().int().safe()).max(7).default([]),
  "end_at": z.union([z.number().gt(0), z.null()]).default(null),
  "catch_up": z.boolean().default(true),
}).superRefine(validateRepeat);
export type RepeatRule = z.infer<typeof RepeatRuleSchema>;

export const DelegationSpecSchema = z.strictObject({
  "goal": unicodeString({"min":1,"max":2000}).transform(value => trimUserText(value)).refine(value => value.length > 0, "目标不能为空"),
  "kind": z.enum(["reminder","source-digest","organize-files"]).default("reminder"),
  "session_id": unicodeString({"max":128}).default(""),
  "source_message_id": unicodeString({"max":128}).default(""),
  "project_id": unicodeString({"max":128}).default(""),
  "sources": z.array(unicodeString({})).max(6).default([]),
  "source_directory": unicodeString({"max":2000}).default(""),
  "output_directory": unicodeString({"max":2000}).default(""),
  "criteria": z.array(unicodeString({})).min(1).max(10),
  "wait": DelegationWaitSchema.default({"kind":"none","at":null,"timezone":"Asia/Shanghai","event":"","subject_id":""}),
  "repeat": RepeatRuleSchema.default({"frequency":"once","local_time":"","weekdays":[],"end_at":null,"catch_up":true}),
  "max_tool_calls": z.number().int().safe().min(1).max(50).default(12),
  "timeout_seconds": z.number().int().safe().min(1).max(600).default(120),
}).superRefine(validateDelegation);
export type DelegationSpec = z.infer<typeof DelegationSpecSchema>;

export const DelegationViewSchema = z.strictObject({
  "id": unicodeString({}),
  "revision": z.number().int().safe(),
  "spec": DelegationSpecSchema,
  "status": z.enum(["draft","scheduled","ready","running","waiting_user","waiting_event","paused","completed","cancelled","failed","needs_review"]).default("draft"),
  "created_at": z.number(),
  "updated_at": z.number(),
  "authorized_at": z.union([z.number(), z.null()]).default(null),
  "expires_at": z.union([z.number(), z.null()]).default(null),
  "active_run_id": unicodeString({}).default(""),
  "reason": unicodeString({}).default("等待你确认目标、范围与验收条件"),
});
export type DelegationView = z.infer<typeof DelegationViewSchema>;

export const JsonValueSchema = z.json();
export type JsonValue = z.infer<typeof JsonValueSchema>;

export const OutcomeSchema = z.object({
  "turn_id": unicodeString({}),
  "verdict": z.enum(["verified","failed","unknown"]).default("unknown"),
  "criteria": z.array(unicodeString({})).default([]),
  "evidence": z.array(z.record(z.string(), JsonValueSchema)).default([]),
  "metrics": z.record(z.string(), z.number()).default({}),
  "scenario": unicodeString({}).default("chat"),
  "reason": unicodeString({}).default("没有可独立检查的任务验收证据"),
});
export type Outcome = z.infer<typeof OutcomeSchema>;

export const DelegationDetailSchema = z.strictObject({
  "delegation": DelegationViewSchema,
  "runs": z.array(DelegationRunSchema),
  "revisions": z.array(DelegationViewSchema),
  "outcomes": z.array(OutcomeSchema).default([]),
});
export type DelegationDetail = z.infer<typeof DelegationDetailSchema>;

export const DialogueStateSchema = z.object({
  "session_id": unicodeString({}),
  "mode": z.enum(["listening","discussing","executing","quiet"]),
  "expires_at": z.number(),
  "reason": unicodeString({}),
});
export type DialogueState = z.infer<typeof DialogueStateSchema>;

export const QuietBoundarySchema = z.object({
  "id": unicodeString({}),
  "subject": unicodeString({}),
  "expires_at": z.union([z.number(), z.null()]).default(null),
  "reason": unicodeString({}),
  "active": z.boolean().default(true),
});
export type QuietBoundary = z.infer<typeof QuietBoundarySchema>;

export const ImageInfoSchema = z.strictObject({
  "image_id": unicodeString({"pattern":"^[a-f0-9]{64}$"}),
  "media_type": unicodeString({}),
  "width": z.number().int().safe(),
  "height": z.number().int().safe(),
  "preview": unicodeString({}),
});
export type ImageInfo = z.infer<typeof ImageInfoSchema>;

export const ChoiceAnswerSchema = z.strictObject({
  "type": z.literal("choice"),
  "choice": z.enum(["yes","no","unknown"]),
  "confidence": z.number().min(0).max(1),
  "probabilities": z.record(z.string(), z.number().min(0).max(1)),
});
export type ChoiceAnswer = z.infer<typeof ChoiceAnswerSchema>;

export const JevAnswersSchema = z.strictObject({
  "relevant": ChoiceAnswerSchema,
  "time_sensitive": ChoiceAnswerSchema,
  "duplicate": ChoiceAnswerSchema,
});
export type JevAnswers = z.infer<typeof JevAnswersSchema>;

export const JevDecisionSchema = z.strictObject({
  "action": z.enum(["notify","defer","quiet"]).default("defer"),
  "reason": unicodeString({}),
  "mode": z.enum(["shadow","active"]),
  "status": z.enum(["running","decided","fallback","interrupted","stale"]),
  "model": unicodeString({}).default(""),
  "answers": z.union([JevAnswersSchema, z.null()]).default(null),
  "created_at": z.number(),
  "not_before": z.number(),
  "elapsed_ms": z.number().default(0),
  "input_tokens": z.union([z.number().int().safe(), z.null()]).default(null),
  "output_tokens": z.union([z.number().int().safe(), z.null()]).default(null),
});
export type JevDecision = z.infer<typeof JevDecisionSchema>;

export const JevStatusSchema = z.strictObject({
  "mode": z.enum(["off","shadow","active"]),
  "configured": z.boolean(),
  "model": unicodeString({}),
  "calls_today": z.number().int().safe(),
  "request_bytes_today": z.number().int().safe(),
  "daily_calls": z.number().int().safe(),
  "daily_request_bytes": z.number().int().safe(),
  "running": z.boolean(),
  "recent": z.array(JevDecisionSchema).default([]),
});
export type JevStatus = z.infer<typeof JevStatusSchema>;

export const SkillStatusSchema = z.enum(["draft","active","needs_review","disabled","archived","deleted"]);
export type SkillStatus = z.infer<typeof SkillStatusSchema>;

export const SkillRecordSchema = z.object({
  "id": unicodeString({}),
  "name": unicodeString({}),
  "path": unicodeString({}),
  "description": unicodeString({}),
  "content": unicodeString({}).default(""),
  "category": unicodeString({}).default("general"),
  "status": SkillStatusSchema.default("draft"),
  "version": z.number().int().safe().min(1).default(1),
  "source": unicodeString({}).default("manual"),
  "source_session_id": z.union([unicodeString({}), z.null()]).default(null),
  "success_count": z.number().int().safe().min(0).default(0),
  "failure_count": z.number().int().safe().min(0).default(0),
  "last_used_at": z.union([dateTimeString(), z.null()]).default(null),
  "review_after": z.union([dateTimeString(), z.null()]).default(null),
  "expires_at": z.union([dateTimeString(), z.null()]).default(null),
  "created_at": dateTimeString().default(localTimestamp),
  "updated_at": dateTimeString().default(localTimestamp),
});
export type SkillRecord = z.infer<typeof SkillRecordSchema>;

export const SkillDetailSchema = z.object({
  "record": SkillRecordSchema,
  "content": z.union([unicodeString({}), z.null()]),
  "content_error": unicodeString({}).default(""),
});
export type SkillDetail = z.infer<typeof SkillDetailSchema>;

export const LearningBudgetSchema = z.object({
  "day": unicodeString({}),
  "calls": z.number().int().safe().default(0),
  "input_tokens": z.number().int().safe().default(0),
  "output_tokens": z.number().int().safe().default(0),
});
export type LearningBudget = z.infer<typeof LearningBudgetSchema>;

export const LearningConsumerSchema = z.object({
  "setting": unicodeString({}),
  "enabled": z.boolean(),
  "consumer": unicodeString({}),
  "behavior": unicodeString({}),
});
export type LearningConsumer = z.infer<typeof LearningConsumerSchema>;

export const LearningJobViewSchema = z.object({
  "id": unicodeString({}),
  "kind": unicodeString({}),
  "status": z.enum(["pending","running","completed","failed","interrupted"]),
  "attempts": z.number().int().safe(),
  "updated_at": z.number(),
  "error": unicodeString({}),
  "result": z.record(z.string(), JsonValueSchema),
});
export type LearningJobView = z.infer<typeof LearningJobViewSchema>;

export const LearningPolicySchema = z.strictObject({
  "enabled": z.boolean().default(true),
  "idle_seconds": z.number().int().safe().min(1).max(3600).default(60),
  "daily_calls": z.number().int().safe().min(0).max(500).default(30),
  "daily_input_tokens": z.number().int().safe().min(0).max(1000000).default(60000),
  "daily_output_tokens": z.number().int().safe().min(0).max(100000).default(8000),
});
export type LearningPolicy = z.infer<typeof LearningPolicySchema>;

export const LearningViewSchema = z.object({
  "policy": LearningPolicySchema,
  "state": z.enum(["disabled","idle","waiting","running","budget_exhausted","closed"]),
  "usage": LearningBudgetSchema,
  "jobs": z.array(LearningJobViewSchema),
  "consumers": z.array(LearningConsumerSchema),
});
export type LearningView = z.infer<typeof LearningViewSchema>;

export const ProjectViewSchema = z.strictObject({
  "name": unicodeString({"min":1,"max":100}),
  "goal": unicodeString({"max":2000}).default(""),
  "id": unicodeString({}),
  "revision": z.number().int().safe().default(1),
  "status": z.enum(["active","paused","completed"]).default("active"),
  "created_at": z.number(),
  "updated_at": z.number(),
});
export type ProjectView = z.infer<typeof ProjectViewSchema>;

export const SourceViewSchema = z.strictObject({
  "id": unicodeString({}),
  "revision": z.number().int().safe().default(1),
  "kind": z.enum(["text","file","url"]),
  "category": z.enum(["material","recent","decision","pending","shared"]),
  "title": unicodeString({}),
  "text": unicodeString({}),
  "locator": unicodeString({}).default(""),
  "project_id": unicodeString({}).default(""),
  "session_id": unicodeString({}).default(""),
  "source_message_id": unicodeString({}).default(""),
  "sha256": unicodeString({}),
  "status": z.enum(["active","changed","missing","expired","forgotten"]).default("active"),
  "sensitive": z.boolean().default(false),
  "expires_at": z.union([z.number(), z.null()]).default(null),
  "created_at": z.number(),
  "checked_at": z.number(),
  "reason": unicodeString({}).default(""),
});
export type SourceView = z.infer<typeof SourceViewSchema>;

export const ProjectOverviewSchema = z.strictObject({
  "project": ProjectViewSchema,
  "sources": z.array(SourceViewSchema),
  "delegations": z.array(DelegationViewSchema),
});
export type ProjectOverview = z.infer<typeof ProjectOverviewSchema>;

export const RpcRequestSchema = z.strictObject({
  "jsonrpc": z.literal("2.0"),
  "id": unicodeString({"min":1,"max":128}),
  "method": unicodeString({}),
  "params": z.record(z.string(), JsonValueSchema),
});
export type RpcRequest = z.infer<typeof RpcRequestSchema>;

export const ServiceEventSchema = z.strictObject({
  "delegation_id": unicodeString({}).default(""),
  "run_id": unicodeString({}).default(""),
  "project_id": unicodeString({}).default(""),
  "session_id": unicodeString({}),
  "task_id": unicodeString({}),
  "turn_id": unicodeString({}),
  "sequence": z.number().int().safe().min(1),
  "kind": unicodeString({}),
  "data": z.record(z.string(), JsonValueSchema),
});
export type ServiceEvent = z.infer<typeof ServiceEventSchema>;

export const TurnStateSchema = z.strictObject({
  "turn_id": unicodeString({}),
  "task_id": unicodeString({}),
  "session_id": unicodeString({}),
  "engine_id": unicodeString({}),
  "lane": z.enum(["foreground","background"]),
  "status": z.enum(["queued","running","completed","cancelled","failed","interrupted"]),
  "input_text": unicodeString({}),
  "image_id": z.union([unicodeString({}), z.null()]).default(null),
  "delegation_id": unicodeString({}).default(""),
  "run_id": unicodeString({}).default(""),
  "project_id": unicodeString({}).default(""),
  "workflow_version": unicodeString({}).default(""),
  "workflow_input": z.record(z.string(), JsonValueSchema).default({}),
  "output_text": unicodeString({}).default(""),
  "error": unicodeString({}).default(""),
});
export type TurnState = z.infer<typeof TurnStateSchema>;

export const RelationViewSchema = z.object({
  "id": unicodeString({}),
  "key": unicodeString({}),
  "kind": unicodeString({}),
  "content": unicodeString({}),
  "scope": unicodeString({}),
  "status": z.enum(["pending","applying","active","rejected","superseded","forgotten"]),
  "reason": unicodeString({}),
  "session_id": unicodeString({}),
  "source_ids": z.array(unicodeString({})),
  "revision": z.number().int().safe(),
  "updated_at": unicodeString({}),
});
export type RelationView = z.infer<typeof RelationViewSchema>;

export const NotificationBatchSchema = z.strictObject({
  "batch_id": unicodeString({}),
  "text": unicodeString({}),
  "count": z.number().int().safe(),
  "expires_at": z.number(),
});
export type NotificationBatch = z.infer<typeof NotificationBatchSchema>;

export const NotificationViewSchema = z.strictObject({
  "id": unicodeString({}),
  "reason": z.enum(["reminder","task_result","companionship"]),
  "source_id": unicodeString({}),
  "delegation_id": unicodeString({}).default(""),
  "text": unicodeString({}),
  "planned_at": z.number(),
  "created_at": z.number(),
  "delivered_at": z.union([z.number(), z.null()]).default(null),
  "read_at": z.union([z.number(), z.null()]).default(null),
  "status": z.enum(["pending","leased","delivered","read","missed","cancelled"]).default("pending"),
  "batch_id": unicodeString({}).default(""),
  "lease_until": z.number().default(0),
  "decision": z.union([JevDecisionSchema, z.null()]).default(null),
});
export type NotificationView = z.infer<typeof NotificationViewSchema>;

export const ScheduleViewSchema = z.strictObject({
  "delegation_id": unicodeString({}),
  "next_at": z.union([z.number(), z.null()]),
  "timezone": unicodeString({}),
  "repeat": RepeatRuleSchema,
  "state": unicodeString({}),
  "reason": unicodeString({}),
});
export type ScheduleView = z.infer<typeof ScheduleViewSchema>;

export const SettingsViewSchema = z.object({
  "values": z.record(z.string(), JsonValueSchema),
  "schema_fields": z.record(z.string(), JsonValueSchema),
  "credentials": z.record(z.string(), z.boolean()),
  "restart_required": z.boolean().default(false),
});
export type SettingsView = z.infer<typeof SettingsViewSchema>;

export const ThemeViewSchema = z.strictObject({
  "name": unicodeString({"min":1,"max":80}),
  "accent": unicodeString({"pattern":"^#[0-9a-fA-F]{6}$"}),
  "side": unicodeString({"pattern":"^#[0-9a-fA-F]{6}$"}),
  "theme_id": unicodeString({}),
});
export type ThemeView = z.infer<typeof ThemeViewSchema>;

export const CompanionOverviewSchema = z.object({
  "experiences": z.array(z.record(z.string(), unicodeString({}))),
  "preferences": z.array(z.record(z.string(), unicodeString({}))),
  "available": z.array(unicodeString({})),
  "verified_skills": z.array(unicodeString({})).default([]),
});
export type CompanionOverview = z.infer<typeof CompanionOverviewSchema>;

export const TopicViewSchema = z.object({
  "topic_id": unicodeString({}),
  "memory_id": unicodeString({}),
  "label": unicodeString({}),
  "blocked": z.boolean(),
  "cooldown_until": z.number(),
});
export type TopicView = z.infer<typeof TopicViewSchema>;

export const WorkflowNodeSchema = z.strictObject({
  "id": unicodeString({"pattern":"^[a-z][a-z0-9_]{0,31}$"}),
  "kind": z.enum(["context","model","tool","condition","verify","output"]),
  "after": z.array(unicodeString({})).max(12).default([]),
  "tool": z.union([z.enum(["lobuddy_organize","lobuddy_digest","lobuddy_read_file"]), z.null()]).default(null),
  "arguments": z.record(z.string(), JsonValueSchema).default({}),
  "source": unicodeString({}).default("input"),
  "format": z.enum(["pretty","compact"]).default("pretty"),
  "prompt": unicodeString({"max":2000}).default(""),
  "operator": z.enum(["exists","equals"]).default("exists"),
  "expected": JsonValueSchema.default(null),
  "when": unicodeString({}).default(""),
});
export type WorkflowNode = z.infer<typeof WorkflowNodeSchema>;

export const WorkflowDefinitionSchema = z.strictObject({
  "name": unicodeString({"pattern":"^[a-z][a-z0-9-]{0,63}$"}),
  "nodes": z.array(WorkflowNodeSchema).min(1).max(12),
  "permissions": z.array(z.enum(["lobuddy_organize","lobuddy_digest","lobuddy_read_file"])).default([]),
  "repairs": z.number().int().safe().min(0).max(2).default(0),
}).superRefine(validateWorkflow);
export type WorkflowDefinition = z.infer<typeof WorkflowDefinitionSchema>;

export const WorkflowViewSchema = z.object({
  "version_id": unicodeString({}),
  "parent_id": unicodeString({}),
  "definition": WorkflowDefinitionSchema,
  "status": unicodeString({}),
  "reason": unicodeString({}),
  "evidence": z.array(unicodeString({})),
  "diff": unicodeString({}),
  "evaluation": z.record(z.string(), JsonValueSchema),
  "observed": z.number().int().safe(),
  "active": z.boolean(),
});
export type WorkflowView = z.infer<typeof WorkflowViewSchema>;

export const CandidateSourceSchema = z.enum(["manual","successful_task","diagnosed_failure","correction","import"]);
export type CandidateSource = z.infer<typeof CandidateSourceSchema>;

export const CandidateStatusSchema = z.enum(["pending","approved","rejected","converted"]);
export type CandidateStatus = z.infer<typeof CandidateStatusSchema>;

export const SkillCandidateSchema = z.object({
  "id": unicodeString({}),
  "title": unicodeString({}),
  "rationale": unicodeString({}),
  "proposed_name": unicodeString({}),
  "proposed_content": unicodeString({}),
  "source_session_id": z.union([unicodeString({}), z.null()]).default(null),
  "source_task_id": z.union([unicodeString({}), z.null()]).default(null),
  "source_kind": CandidateSourceSchema.default("manual"),
  "revision": z.number().int().safe().min(1).default(1),
  "confidence": z.number().min(0).max(1).default(0.5),
  "evidence": z.record(z.string(), z.json()).default({}),
  "validation_errors": z.array(unicodeString({})).default([]),
  "status": CandidateStatusSchema.default("pending"),
  "reject_reason": z.union([unicodeString({}), z.null()]).default(null),
  "created_at": dateTimeString().default(localTimestamp),
  "updated_at": dateTimeString().default(localTimestamp),
});
export type SkillCandidate = z.infer<typeof SkillCandidateSchema>;

export const AbilityViewSchema = z.object({
  "id": unicodeString({}),
  "name": unicodeString({}),
  "description": unicodeString({}),
  "type": unicodeString({}),
  "unlocked_at": z.union([unicodeString({}), z.null()]),
  "min_level": z.union([z.number().int().safe(), z.null()]),
  "min_stage": z.union([z.number().int().safe(), z.null()]),
  "trait": z.union([unicodeString({}), z.null()]),
  "trait_value": z.union([z.number(), z.null()]),
  "tasks_completed": z.union([z.number().int().safe(), z.null()]),
});
export type AbilityView = z.infer<typeof AbilityViewSchema>;

export const UsageTotalsSchema = z.object({
  "input": z.number().int().safe(),
  "output": z.number().int().safe(),
  "cached": z.number().int().safe(),
  "calls": z.number().int().safe(),
});
export type UsageTotals = z.infer<typeof UsageTotalsSchema>;

export const ProgressOverviewSchema = z.object({
  "completed_tasks": z.number().int().safe(),
  "usage": UsageTotalsSchema,
  "abilities": z.array(AbilityViewSchema),
  "pet": PetStateSchema,
});
export type ProgressOverview = z.infer<typeof ProgressOverviewSchema>;

export const VoiceEventSchema = z.object({
  "voice_id": unicodeString({}),
  "session_id": unicodeString({}),
  "turn_id": unicodeString({}).default(""),
  "round_id": z.number().int().safe(),
  "sequence": z.number().int().safe(),
  "kind": z.enum(["interrupt","transcript","audio","audio.end","error"]),
  "text": unicodeString({}).default(""),
  "pcm": unicodeString({}).default(""),
  "sample_rate": z.number().int().safe().default(24000),
});
export type VoiceEvent = z.infer<typeof VoiceEventSchema>;

export const VoiceStatusSchema = z.object({
  "voice_id": unicodeString({}).default(""),
  "session_id": unicodeString({}).default(""),
  "state": z.enum(["off","loading","listening","thinking","speaking","muted","error"]).default("off"),
  "model_ready": z.boolean().default(false),
  "downloading": z.boolean().default(false),
  "fish_configured": z.boolean().default(false),
  "silence_ms": z.number().int().safe().default(700),
  "error": unicodeString({}).default(""),
  "fish_model": z.enum(["s2.1-pro","s2.1-pro-free"]).default("s2.1-pro-free"),
  "reference_id": unicodeString({}).default("e4a66454f7a44f63a2cc9e8c044d701d"),
});
export type VoiceStatus = z.infer<typeof VoiceStatusSchema>;

export const SessionReferenceSchema = z.strictObject({
  "session_id": unicodeString({"min":1,"max":128}),
});
export type SessionReference = z.infer<typeof SessionReferenceSchema>;

export const BoundaryReferenceSchema = z.strictObject({
  "boundary_id": unicodeString({"min":1,"max":128}),
});
export type BoundaryReference = z.infer<typeof BoundaryReferenceSchema>;

export const SourceReferenceSchema = z.strictObject({
  "source_id": unicodeString({"min":1,"max":128}),
});
export type SourceReference = z.infer<typeof SourceReferenceSchema>;

export const EmptySchema = z.strictObject({

});
export type Empty = z.infer<typeof EmptySchema>;

export const ProjectCreateSchema = z.strictObject({
  "name": unicodeString({"min":1,"max":100}),
  "goal": unicodeString({"max":2000}).default(""),
});
export type ProjectCreate = z.infer<typeof ProjectCreateSchema>;

export const ProjectReferenceSchema = z.strictObject({
  "project_id": unicodeString({"min":1,"max":128}),
});
export type ProjectReference = z.infer<typeof ProjectReferenceSchema>;

export const ProjectChangeSchema = z.strictObject({
  "project_id": unicodeString({"min":1,"max":128}),
  "revision": z.number().int().safe().min(1),
  "name": unicodeString({"min":1,"max":100}),
  "goal": unicodeString({"max":2000}).default(""),
  "status": z.enum(["active","paused","completed"]).default("active"),
});
export type ProjectChange = z.infer<typeof ProjectChangeSchema>;

export const ProjectBindSchema = z.strictObject({
  "revision": z.number().int().safe().min(0),
  "session_id": unicodeString({"min":1,"max":128}),
  "project_id": unicodeString({"max":128}).default(""),
});
export type ProjectBind = z.infer<typeof ProjectBindSchema>;

export const SourceShareSchema = z.strictObject({
  "kind": z.enum(["text","file","url"]).default("text"),
  "category": z.enum(["material","recent","decision","pending","shared"]).default("material"),
  "title": unicodeString({"min":1,"max":100}),
  "text": unicodeString({"max":12000}).default(""),
  "locator": unicodeString({"max":4096}).default(""),
  "project_id": unicodeString({"max":128}).default(""),
  "session_id": unicodeString({"max":128}).default(""),
  "source_message_id": unicodeString({"max":128}).default(""),
  "expires_at": z.union([z.number().gt(0), z.null()]).default(null),
  "sensitive_confirmed": z.boolean().default(false),
}).superRefine(validateSource);
export type SourceShare = z.infer<typeof SourceShareSchema>;

export const SourceCorrectSchema = z.strictObject({
  "source_id": unicodeString({"min":1,"max":128}),
  "revision": z.number().int().safe().min(1),
  "text": unicodeString({"min":1,"max":12000}),
  "sensitive_confirmed": z.boolean().default(false),
});
export type SourceCorrect = z.infer<typeof SourceCorrectSchema>;

export const SourceMoveSchema = z.strictObject({
  "source_id": unicodeString({"min":1,"max":128}),
  "revision": z.number().int().safe().min(1),
  "project_id": unicodeString({"max":128}).default(""),
  "session_id": unicodeString({"max":128}).default(""),
}).superRefine(validateSourceMove);
export type SourceMove = z.infer<typeof SourceMoveSchema>;

export const SourceChangeSchema = z.strictObject({
  "source_id": unicodeString({"min":1,"max":128}),
  "revision": z.number().int().safe().min(1),
});
export type SourceChange = z.infer<typeof SourceChangeSchema>;

export const DelegationReferenceSchema = z.strictObject({
  "delegation_id": unicodeString({"min":1,"max":128}),
});
export type DelegationReference = z.infer<typeof DelegationReferenceSchema>;

export const ScheduleResolveSchema = z.strictObject({
  "local": unicodeString({"pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$"}),
  "timezone": unicodeString({"min":1,"max":128}),
});
export type ScheduleResolve = z.infer<typeof ScheduleResolveSchema>;

export const RuntimePowerSchema = z.strictObject({
  "suspended": z.boolean(),
});
export type RuntimePower = z.infer<typeof RuntimePowerSchema>;

export const NotificationBatchReferenceSchema = z.strictObject({
  "batch_id": unicodeString({"min":1,"max":128}),
});
export type NotificationBatchReference = z.infer<typeof NotificationBatchReferenceSchema>;

export const NotificationReferenceSchema = z.strictObject({
  "notification_id": unicodeString({"min":1,"max":128}),
});
export type NotificationReference = z.infer<typeof NotificationReferenceSchema>;

export const RecoveryRequestSchema = z.strictObject({
  "delegation_id": unicodeString({"min":1,"max":128}),
  "revision": z.number().int().safe().min(1),
  "action": z.enum(["inspect","resume_readonly"]).default("inspect"),
});
export type RecoveryRequest = z.infer<typeof RecoveryRequestSchema>;

export const DelegationConfirmSchema = z.strictObject({
  "delegation_id": unicodeString({"min":1,"max":128}),
  "revision": z.number().int().safe().min(1),
  "expires_at": z.number().gt(0),
});
export type DelegationConfirm = z.infer<typeof DelegationConfirmSchema>;

export const DelegationEditSchema = z.strictObject({
  "delegation_id": unicodeString({"min":1,"max":128}),
  "revision": z.number().int().safe().min(1),
  "spec": DelegationSpecSchema,
});
export type DelegationEdit = z.infer<typeof DelegationEditSchema>;

export const DelegationChangeSchema = z.strictObject({
  "delegation_id": unicodeString({"min":1,"max":128}),
  "revision": z.number().int().safe().min(1),
});
export type DelegationChange = z.infer<typeof DelegationChangeSchema>;

export const WorkflowProposalSchema = z.strictObject({
  "definition": WorkflowDefinitionSchema,
  "reason": unicodeString({"min":1,"max":1000}),
});
export type WorkflowProposal = z.infer<typeof WorkflowProposalSchema>;

export const WorkflowReferenceSchema = z.strictObject({
  "version_id": unicodeString({"min":1,"max":128}),
});
export type WorkflowReference = z.infer<typeof WorkflowReferenceSchema>;

export const RelationReferenceSchema = z.strictObject({
  "relation_id": unicodeString({"min":1,"max":128}),
});
export type RelationReference = z.infer<typeof RelationReferenceSchema>;

export const RelationResolveSchema = z.strictObject({
  "relation_id": unicodeString({"min":1,"max":128}),
  "approved": z.boolean(),
});
export type RelationResolve = z.infer<typeof RelationResolveSchema>;

export const RelationForgetSchema = z.strictObject({
  "relation_id": unicodeString({"min":1,"max":128}),
  "delete_history": z.boolean().default(false),
});
export type RelationForget = z.infer<typeof RelationForgetSchema>;

export const RelationEditSchema = z.strictObject({
  "relation_id": unicodeString({"min":1,"max":128}),
  "content": unicodeString({"min":1,"max":1000}),
});
export type RelationEdit = z.infer<typeof RelationEditSchema>;

export const RelationPolicySchema = z.strictObject({
  "enabled": z.boolean().default(true),
});
export type RelationPolicy = z.infer<typeof RelationPolicySchema>;

export const VoiceOptionsSchema = z.strictObject({
  "fish_model": z.enum(["s2.1-pro","s2.1-pro-free"]).default("s2.1-pro-free"),
  "silence_ms": z.number().int().safe().min(300).max(2000).default(700),
});
export type VoiceOptions = z.infer<typeof VoiceOptionsSchema>;

export const VoiceStartSchema = z.strictObject({
  "session_id": unicodeString({"min":1,"max":128}),
});
export type VoiceStart = z.infer<typeof VoiceStartSchema>;

export const VoiceMuteSchema = z.strictObject({
  "voice_id": unicodeString({"min":1,"max":128}),
  "muted": z.boolean(),
});
export type VoiceMute = z.infer<typeof VoiceMuteSchema>;

export const VoiceFrameSchema = z.strictObject({
  "voice_id": unicodeString({"min":1,"max":128}),
  "sequence": z.number().int().safe().min(1),
  "pcm": unicodeString({"min":1368,"max":1368}),
});
export type VoiceFrame = z.infer<typeof VoiceFrameSchema>;

export const VoicePollSchema = z.strictObject({
  "voice_id": unicodeString({"min":1,"max":128}),
  "playing": z.boolean().default(false),
  "after": z.number().int().safe().min(0),
});
export type VoicePoll = z.infer<typeof VoicePollSchema>;

export const TopicReferenceSchema = z.strictObject({
  "topic_id": unicodeString({"min":1,"max":128}),
});
export type TopicReference = z.infer<typeof TopicReferenceSchema>;

export const CompanionPolicySchema = z.strictObject({
  "enabled": z.boolean().default(true),
  "daily_limit": z.number().int().safe().min(0).max(10).default(3),
  "interval_minutes": z.number().int().safe().min(1).max(1440).default(60),
  "ignore_minutes": z.number().int().safe().min(1).max(10080).default(120),
  "do_not_disturb": z.boolean().default(false),
});
export type CompanionPolicy = z.infer<typeof CompanionPolicySchema>;

export const CompanionActivitySchema = z.strictObject({
  "client": z.enum(["manage","quick"]),
  "typing": z.boolean(),
  "conversation": z.boolean(),
});
export type CompanionActivity = z.infer<typeof CompanionActivitySchema>;

export const CompanionTriggerSchema = z.strictObject({
  "event": z.enum(["app_returned","conversation_finished","focus_finished"]),
});
export type CompanionTrigger = z.infer<typeof CompanionTriggerSchema>;

export const CompanionFeedbackSchema = z.strictObject({
  "notice_id": unicodeString({"min":1,"max":128}),
  "action": z.enum(["opened","ignored","later","never"]),
});
export type CompanionFeedback = z.infer<typeof CompanionFeedbackSchema>;

export const CompanionPreferenceSchema = z.strictObject({
  "kind": z.enum(["nickname","tone","boundary","shared"]),
  "content": unicodeString({"max":1000}),
});
export type CompanionPreference = z.infer<typeof CompanionPreferenceSchema>;

export const ThemeSaveSchema = z.strictObject({
  "name": unicodeString({"min":1,"max":80}),
  "accent": unicodeString({"pattern":"^#[0-9a-fA-F]{6}$"}),
  "side": unicodeString({"pattern":"^#[0-9a-fA-F]{6}$"}),
});
export type ThemeSave = z.infer<typeof ThemeSaveSchema>;

export const ThemeReferenceSchema = z.strictObject({
  "theme_id": unicodeString({"min":1,"max":128}),
});
export type ThemeReference = z.infer<typeof ThemeReferenceSchema>;

export const ImageReferenceSchema = z.strictObject({
  "image_id": unicodeString({"pattern":"^[a-f0-9]{64}$"}),
});
export type ImageReference = z.infer<typeof ImageReferenceSchema>;

export const CompanionPreferencesSchema = z.strictObject({
  "sprite": z.enum(["skadi-v2","skadi","custom"]).default("skadi-v2"),
  "image_id": z.union([unicodeString({"pattern":"^[a-f0-9]{64}$"}), z.null()]).default(null),
  "scale": z.number().min(0.5).max(2).default(1),
  "opacity": z.number().min(0.3).max(1).default(1),
  "always_on_top": z.boolean().default(true),
  "accent": unicodeString({"pattern":"^#[0-9a-fA-F]{6}$"}).default("#367572"),
  "side": unicodeString({"pattern":"^#[0-9a-fA-F]{6}$"}).default("#deebec"),
});
export type CompanionPreferences = z.infer<typeof CompanionPreferencesSchema>;

export const ImageImportSchema = z.strictObject({
  "path": unicodeString({"min":1,"max":4096}),
});
export type ImageImport = z.infer<typeof ImageImportSchema>;

export const MemoryQuerySchema = z.strictObject({
  "query": unicodeString({"max":200}).default(""),
});
export type MemoryQuery = z.infer<typeof MemoryQuerySchema>;

export const MemorySaveSchema = z.strictObject({
  "memory_id": z.union([unicodeString({"max":128}), z.null()]).default(null),
  "memory_type": z.enum(["user_profile","system_profile","project_memory","conversation_summary","episodic_memory","procedural_memory"]),
  "title": unicodeString({"max":100}),
  "content": unicodeString({"min":1,"max":2000}),
});
export type MemorySave = z.infer<typeof MemorySaveSchema>;

export const MemoryReferenceSchema = z.strictObject({
  "memory_id": unicodeString({"min":1,"max":128}),
});
export type MemoryReference = z.infer<typeof MemoryReferenceSchema>;

export const HistorySearchSchema = z.strictObject({
  "session_id": unicodeString({"min":1,"max":128}),
  "query": unicodeString({"min":1,"max":200}),
  "scope": z.enum(["current_session","all_sessions"]).default("current_session"),
});
export type HistorySearch = z.infer<typeof HistorySearchSchema>;

export const SkillReferenceSchema = z.strictObject({
  "skill_id": unicodeString({"min":1,"max":128}),
});
export type SkillReference = z.infer<typeof SkillReferenceSchema>;

export const SkillSaveSchema = z.strictObject({
  "skill_id": z.union([unicodeString({"max":128}), z.null()]).default(null),
  "name": unicodeString({"min":1,"max":80,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]*$"}),
  "description": unicodeString({"min":1,"max":500}),
  "content": unicodeString({"min":1,"max":64000}),
});
export type SkillSave = z.infer<typeof SkillSaveSchema>;

export const SkillToggleSchema = z.strictObject({
  "skill_id": unicodeString({"min":1,"max":128}),
  "enabled": z.boolean(),
});
export type SkillToggle = z.infer<typeof SkillToggleSchema>;

export const CandidateResolveSchema = z.strictObject({
  "candidate_id": unicodeString({"min":1,"max":128}),
  "approved": z.boolean(),
});
export type CandidateResolve = z.infer<typeof CandidateResolveSchema>;

export const SessionCreateSchema = z.strictObject({
  "title": unicodeString({"min":1,"max":100}).default("新对话"),
});
export type SessionCreate = z.infer<typeof SessionCreateSchema>;

export const TurnSendSchema = z.strictObject({
  "session_id": unicodeString({"min":1,"max":128}),
  "workflow_id": unicodeString({"max":64}).default(""),
  "workflow_input": z.record(z.string(), JsonValueSchema).default({}),
  "image_id": z.union([unicodeString({"pattern":"^[a-f0-9]{64}$"}), z.null()]).default(null),
  "text": unicodeString({"min":1,"max":4000}),
  "lane": z.enum(["foreground","background"]).default("foreground"),
});
export type TurnSend = z.infer<typeof TurnSendSchema>;

export const TurnReferenceSchema = z.strictObject({
  "turn_id": unicodeString({"min":1,"max":128}),
});
export type TurnReference = z.infer<typeof TurnReferenceSchema>;

export const ApprovalResolveSchema = z.strictObject({
  "approval_id": unicodeString({"min":1,"max":128}),
  "approved": z.boolean(),
});
export type ApprovalResolve = z.infer<typeof ApprovalResolveSchema>;

export const CredentialConfigureSchema = z.strictObject({
  "account": z.enum(["llm_api_key","llm_multimodal_api_key","fish_api_key","typesafe_api_key"]),
});
export type CredentialConfigure = z.infer<typeof CredentialConfigureSchema>;

export const SettingsPatchSchema = z.strictObject({
  "values": z.record(z.string(), JsonValueSchema),
});
export type SettingsPatch = z.infer<typeof SettingsPatchSchema>;

export const FocusStartSchema = z.strictObject({
  "minutes": z.number().int().safe().min(1).max(240).default(25),
});
export type FocusStart = z.infer<typeof FocusStartSchema>;
