// Required legacy columns; additions remain preserved for forward-compatible data evidence.
export const REQUIRED_COLUMNS = {
  "app_settings": [
    "key",
    "value",
    "updated_at"
  ],
  "chat_message": [
    "id",
    "session_id",
    "role",
    "content",
    "image_path",
    "created_at"
  ],
  "chat_session": [
    "id",
    "pet_id",
    "title",
    "created_at",
    "updated_at"
  ],
  "companion_topic": [
    "id",
    "memory_id",
    "revision",
    "shown_at",
    "cooldown_until",
    "blocked"
  ],
  "conversation_summary": [
    "id",
    "session_id",
    "summary_type",
    "content",
    "from_message_id",
    "to_message_id",
    "token_estimate",
    "created_at",
    "updated_at"
  ],
  "delegation": [
    "id",
    "body"
  ],
  "delegation_checkpoint": [
    "run_id",
    "version",
    "sources",
    "body"
  ],
  "delegation_event": [
    "id",
    "kind",
    "subject",
    "at"
  ],
  "delegation_event_consumed": [
    "delegation_id",
    "event_id"
  ],
  "delegation_request": [
    "id",
    "fingerprint",
    "result"
  ],
  "delegation_revision": [
    "id",
    "revision",
    "body"
  ],
  "delegation_run": [
    "id",
    "delegation_id",
    "trigger_id",
    "turn_id",
    "body"
  ],
  "delegation_schedule": [
    "id",
    "signature",
    "next_at"
  ],
  "delegation_schema": [
    "version"
  ],
  "delegation_usage": [
    "run_id",
    "calls",
    "started_at",
    "spent"
  ],
  "dialogue_boundary": [
    "id",
    "body"
  ],
  "dialogue_invitation": [
    "id",
    "event",
    "source_id",
    "revision",
    "topic_id",
    "body",
    "expires"
  ],
  "dialogue_state": [
    "session_id",
    "body"
  ],
  "engine_session": [
    "session_id",
    "lane",
    "engine_id",
    "ready"
  ],
  "hitl_approval_log": [
    "id",
    "session_id",
    "tool_name",
    "command_hash",
    "command_preview",
    "working_dir",
    "affected_paths_json",
    "risk_tags_json",
    "reason",
    "decision",
    "decision_reason",
    "created_at",
    "decided_at"
  ],
  "jev_budget": [
    "day",
    "calls",
    "request_bytes"
  ],
  "jev_decision": [
    "notification_id",
    "context_hash",
    "body"
  ],
  "knowledge_state": [
    "name",
    "value"
  ],
  "learning_budget": [
    "day",
    "calls",
    "input_tokens",
    "output_tokens"
  ],
  "learning_job": [
    "id",
    "kind",
    "source_id",
    "status",
    "attempts",
    "updated_at",
    "error",
    "result"
  ],
  "learning_schema": [
    "version"
  ],
  "memory_item": [
    "id",
    "memory_type",
    "scope",
    "title",
    "content",
    "source",
    "source_session_id",
    "source_message_id",
    "confidence",
    "importance",
    "priority",
    "status",
    "expires_at",
    "last_used_at",
    "created_at",
    "updated_at"
  ],
  "memory_item_fts": [
    "title",
    "content"
  ],
  "migration_record": [
    "migration_id",
    "detail_json",
    "created_at"
  ],
  "model_usage": [
    "turn_id",
    "sequence",
    "session_id",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "created_at"
  ],
  "notification": [
    "id",
    "body"
  ],
  "personal_project": [
    "id",
    "body"
  ],
  "pet_state": [
    "id",
    "name",
    "level",
    "exp",
    "evolution_stage",
    "mood",
    "skin",
    "personality_json",
    "created_at",
    "updated_at"
  ],
  "project_context_use": [
    "turn_id",
    "source_id"
  ],
  "project_request": [
    "id",
    "fingerprint",
    "entity_id"
  ],
  "project_schema": [
    "version"
  ],
  "project_session": [
    "session_id",
    "project_id",
    "revision"
  ],
  "project_source": [
    "id",
    "body"
  ],
  "relationship": [
    "id",
    "key",
    "kind",
    "content",
    "scope",
    "status",
    "reason",
    "session_id",
    "source_ids",
    "revision",
    "updated_at",
    "content_hash",
    "sensitive"
  ],
  "relationship_barrier": [
    "source_id",
    "forgotten_at"
  ],
  "relationship_revision": [
    "relation_id",
    "revision",
    "value"
  ],
  "schedule_dispatch": [
    "trigger_id",
    "delegation_id",
    "revision",
    "done"
  ],
  "schedule_owner": [
    "id",
    "owner",
    "expires"
  ],
  "service_event": [
    "sequence",
    "event_json"
  ],
  "service_schema_version": [
    "version"
  ],
  "service_turn": [
    "turn_id",
    "request_id",
    "request_json",
    "state_json"
  ],
  "skill_candidate": [
    "id",
    "title",
    "rationale",
    "proposed_name",
    "proposed_content",
    "source_session_id",
    "source_task_id",
    "confidence",
    "status",
    "created_at",
    "updated_at",
    "metadata"
  ],
  "skill_candidate_revision": [
    "candidate_id",
    "revision",
    "body"
  ],
  "skill_event": [
    "id",
    "skill_id",
    "event_type",
    "detail",
    "session_id",
    "created_at"
  ],
  "skill_record": [
    "id",
    "name",
    "path",
    "description",
    "category",
    "status",
    "version",
    "source",
    "source_session_id",
    "success_count",
    "failure_count",
    "last_used_at",
    "review_after",
    "expires_at",
    "created_at",
    "updated_at",
    "content"
  ],
  "skill_use": [
    "task_id",
    "skill_id"
  ],
  "skill_version": [
    "skill_id",
    "version",
    "content",
    "description",
    "source",
    "created_at"
  ],
  "task_acceptance": [
    "turn_id",
    "body",
    "created_at"
  ],
  "task_effect": [
    "id",
    "turn_id",
    "state",
    "body"
  ],
  "task_record": [
    "id",
    "input_text",
    "task_type",
    "status",
    "difficulty",
    "reward_exp",
    "created_at",
    "started_at",
    "finished_at"
  ],
  "task_result": [
    "id",
    "task_id",
    "success",
    "raw_result",
    "summary",
    "error_message",
    "created_at"
  ],
  "turn_settlement": [
    "task_id",
    "turn_id",
    "status",
    "progress_json",
    "created_at"
  ],
  "unlocked_abilities": [
    "ability_id",
    "unlocked_at"
  ],
  "user_themes": [
    "id",
    "name",
    "source",
    "colors_json",
    "source_image_path",
    "is_active",
    "created_at",
    "updated_at"
  ],
  "workflow_active": [
    "name",
    "version_id",
    "enabled"
  ],
  "workflow_observation": [
    "run_id",
    "version_id",
    "state"
  ],
  "workflow_version": [
    "id",
    "name",
    "parent",
    "body",
    "reason",
    "evidence",
    "status",
    "evaluation",
    "observed"
  ]
} as const;
