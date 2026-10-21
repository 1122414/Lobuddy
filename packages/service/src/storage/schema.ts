// Existing DSH desktop schema, frozen at 7195718; FTS shadows are managed by SQLite.
export const LEGACY_SCHEMA_SQL = `CREATE TABLE app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

CREATE TABLE chat_message (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    image_path TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES chat_session(id) ON DELETE CASCADE
                );

CREATE TABLE chat_session (
                    id TEXT PRIMARY KEY,
                    pet_id TEXT NOT NULL DEFAULT 'default',
                    title TEXT NOT NULL DEFAULT 'New Chat',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

CREATE TABLE companion_topic (
                id TEXT PRIMARY KEY, memory_id TEXT NOT NULL, revision TEXT NOT NULL,
                shown_at REAL NOT NULL, cooldown_until REAL NOT NULL DEFAULT 0,
                blocked INTEGER NOT NULL DEFAULT 0);

CREATE TABLE conversation_summary (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    summary_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    from_message_id TEXT,
                    to_message_id TEXT,
                    token_estimate INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

CREATE TABLE delegation(
                id TEXT PRIMARY KEY, body TEXT NOT NULL);

CREATE TABLE delegation_checkpoint(run_id TEXT PRIMARY KEY,version TEXT,sources TEXT,body TEXT);

CREATE TABLE delegation_event(id TEXT PRIMARY KEY,kind TEXT,subject TEXT,at REAL);

CREATE TABLE delegation_event_consumed(delegation_id TEXT,event_id TEXT,PRIMARY KEY(delegation_id,event_id));

CREATE TABLE delegation_request(
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);

CREATE TABLE delegation_revision(
                id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(id,revision), FOREIGN KEY(id) REFERENCES delegation(id));

CREATE TABLE delegation_run(
                id TEXT PRIMARY KEY, delegation_id TEXT NOT NULL, trigger_id TEXT NOT NULL UNIQUE,
                turn_id TEXT UNIQUE, body TEXT NOT NULL,
                FOREIGN KEY(delegation_id) REFERENCES delegation(id));

CREATE TABLE delegation_schedule(id TEXT PRIMARY KEY,signature TEXT,next_at REAL);

CREATE TABLE delegation_schema(
                version INTEGER PRIMARY KEY);

CREATE TABLE delegation_usage(run_id TEXT PRIMARY KEY,calls INTEGER,started_at REAL,spent REAL);

CREATE TABLE dialogue_boundary(id TEXT PRIMARY KEY,body TEXT);

CREATE TABLE dialogue_invitation(id TEXT PRIMARY KEY,event TEXT,source_id TEXT,revision TEXT,topic_id TEXT,body TEXT NOT NULL DEFAULT '{}',expires REAL);

CREATE TABLE dialogue_state(session_id TEXT PRIMARY KEY,body TEXT);

CREATE TABLE engine_session (
                session_id TEXT NOT NULL REFERENCES chat_session(id), lane TEXT NOT NULL,
                engine_id TEXT NOT NULL UNIQUE, ready INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (session_id, lane));

CREATE TABLE hitl_approval_log (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    command_hash TEXT NOT NULL,
                    command_preview TEXT NOT NULL,
                    working_dir TEXT,
                    affected_paths_json TEXT NOT NULL,
                    risk_tags_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    decision_reason TEXT,
                    created_at TEXT NOT NULL,
                    decided_at TEXT NOT NULL
                );

CREATE TABLE jev_budget (
                day TEXT PRIMARY KEY, calls INTEGER NOT NULL, request_bytes INTEGER NOT NULL);

CREATE TABLE jev_decision (
                notification_id TEXT PRIMARY KEY, context_hash TEXT NOT NULL, body TEXT NOT NULL);

CREATE TABLE knowledge_state (name TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE learning_budget (
                day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0);

CREATE TABLE learning_job (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, source_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL, error TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '{}', UNIQUE(kind, source_id));

CREATE TABLE learning_schema (version INTEGER PRIMARY KEY);

CREATE TABLE memory_item (
                    id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'global',
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'ai',
                    source_session_id TEXT,
                    source_message_id TEXT,
                    confidence REAL NOT NULL DEFAULT 0.8,
                    importance REAL NOT NULL DEFAULT 0.5,
                    priority INTEGER NOT NULL DEFAULT 50,
                    status TEXT NOT NULL DEFAULT 'active',
                    expires_at TEXT,
                    last_used_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

CREATE VIRTUAL TABLE memory_item_fts
                        USING fts5(title, content, content='memory_item', content_rowid='rowid');

CREATE TABLE migration_record (
            migration_id TEXT PRIMARY KEY, detail_json TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE model_usage (
            turn_id TEXT NOT NULL, sequence INTEGER NOT NULL,
            session_id TEXT NOT NULL, input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL, cached_tokens INTEGER NOT NULL,
            created_at TEXT NOT NULL, PRIMARY KEY(turn_id, sequence));

CREATE TABLE notification(
                id TEXT PRIMARY KEY, body TEXT NOT NULL);

CREATE TABLE personal_project(id TEXT PRIMARY KEY,body TEXT NOT NULL);

CREATE TABLE pet_state (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT 'Lobuddy',
                    level INTEGER NOT NULL DEFAULT 1,
                    exp INTEGER NOT NULL DEFAULT 0,
                    evolution_stage INTEGER NOT NULL DEFAULT 1,
                    mood TEXT NOT NULL DEFAULT 'happy',
                    skin TEXT NOT NULL DEFAULT 'default',
                    personality_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

CREATE TABLE project_context_use(turn_id TEXT,source_id TEXT,PRIMARY KEY(turn_id,source_id));

CREATE TABLE project_request(id TEXT PRIMARY KEY,fingerprint TEXT,entity_id TEXT);

CREATE TABLE project_schema(version INTEGER PRIMARY KEY);

CREATE TABLE project_session(session_id TEXT PRIMARY KEY,project_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0);

CREATE TABLE project_source(id TEXT PRIMARY KEY,body TEXT NOT NULL);

CREATE TABLE relationship (
                id TEXT PRIMARY KEY, key TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL,
                scope TEXT NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL,
                session_id TEXT NOT NULL, source_ids TEXT NOT NULL, revision INTEGER NOT NULL,
                updated_at TEXT NOT NULL, content_hash TEXT NOT NULL, sensitive INTEGER NOT NULL DEFAULT 0);

CREATE TABLE relationship_barrier (
                source_id TEXT PRIMARY KEY, forgotten_at TEXT NOT NULL);

CREATE TABLE relationship_revision (
                relation_id TEXT NOT NULL, revision INTEGER NOT NULL, value TEXT NOT NULL,
                PRIMARY KEY(relation_id, revision));

CREATE TABLE schedule_dispatch(trigger_id TEXT PRIMARY KEY,delegation_id TEXT,revision INTEGER,done INTEGER NOT NULL DEFAULT 0);

CREATE TABLE schedule_owner(id INTEGER PRIMARY KEY CHECK(id=1),owner TEXT,expires REAL);

CREATE TABLE service_event (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_json TEXT NOT NULL);

CREATE TABLE service_schema_version (version INTEGER PRIMARY KEY);

CREATE TABLE service_turn (
                turn_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                request_json TEXT NOT NULL, state_json TEXT NOT NULL);

CREATE TABLE skill_candidate (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    proposed_name TEXT NOT NULL,
                    proposed_content TEXT NOT NULL,
                    source_session_id TEXT,
                    source_task_id TEXT,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                , metadata TEXT NOT NULL DEFAULT '{}');

CREATE TABLE skill_candidate_revision(
                candidate_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(candidate_id, revision));

CREATE TABLE skill_event (
                    id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    session_id TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (skill_id) REFERENCES skill_record(id) ON DELETE CASCADE
                );

CREATE TABLE skill_record (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    path TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    status TEXT NOT NULL DEFAULT 'draft',
                    version INTEGER NOT NULL DEFAULT 1,
                    source TEXT NOT NULL DEFAULT 'manual',
                    source_session_id TEXT,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    last_used_at TEXT,
                    review_after TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                , content TEXT NOT NULL DEFAULT '');

CREATE TABLE skill_use (
            task_id TEXT NOT NULL, skill_id TEXT NOT NULL,
            PRIMARY KEY(task_id, skill_id));

CREATE TABLE skill_version(
                skill_id TEXT NOT NULL, version INTEGER NOT NULL, content TEXT NOT NULL,
                description TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(skill_id,version),
                FOREIGN KEY(skill_id) REFERENCES skill_record(id) ON DELETE CASCADE);

CREATE TABLE task_acceptance(
                turn_id TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE task_effect(
                id TEXT PRIMARY KEY, turn_id TEXT NOT NULL, state TEXT NOT NULL,
                body TEXT NOT NULL);

CREATE TABLE task_record (
                    id TEXT PRIMARY KEY,
                    input_text TEXT NOT NULL,
                    task_type TEXT NOT NULL DEFAULT 'general',
                    status TEXT NOT NULL DEFAULT 'created',
                    difficulty TEXT NOT NULL DEFAULT 'simple',
                    reward_exp INTEGER NOT NULL DEFAULT 5,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );

CREATE TABLE task_result (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE,
                    success INTEGER NOT NULL DEFAULT 0,
                    raw_result TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES task_record(id) ON DELETE CASCADE
                );

CREATE TABLE turn_settlement (
            task_id TEXT PRIMARY KEY, turn_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL, progress_json TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE unlocked_abilities (
                    ability_id TEXT PRIMARY KEY,
                    unlocked_at TEXT NOT NULL
                );

CREATE TABLE user_themes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    colors_json TEXT NOT NULL,
                    source_image_path TEXT,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

CREATE TABLE workflow_active(
                name TEXT PRIMARY KEY,version_id TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1);

CREATE TABLE workflow_observation(
                run_id TEXT PRIMARY KEY,version_id TEXT NOT NULL,state TEXT NOT NULL);

CREATE TABLE workflow_version(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,parent TEXT NOT NULL,body TEXT NOT NULL,
                reason TEXT NOT NULL,evidence TEXT NOT NULL,status TEXT NOT NULL,
                evaluation TEXT NOT NULL DEFAULT '{}',observed INTEGER NOT NULL DEFAULT 0);

CREATE INDEX idx_chat_message_session
                ON chat_message(session_id, created_at ASC);

CREATE INDEX idx_chat_session_updated
                ON chat_session(updated_at DESC);

CREATE INDEX idx_conversation_summary_session
                ON conversation_summary(session_id, created_at DESC);

CREATE INDEX idx_memory_created
                ON memory_item(created_at DESC);

CREATE INDEX idx_memory_scope
                ON memory_item(scope);

CREATE INDEX idx_memory_type_status
                ON memory_item(memory_type, status);

CREATE INDEX idx_skill_category ON skill_record(category);

CREATE INDEX idx_skill_status ON skill_record(status);

CREATE INDEX idx_task_created ON task_record(created_at);

CREATE INDEX idx_task_status ON task_record(status);

INSERT OR IGNORE INTO service_schema_version VALUES(1),(2);
INSERT OR IGNORE INTO learning_schema VALUES(1);
INSERT OR IGNORE INTO delegation_schema VALUES(1);
INSERT OR IGNORE INTO project_schema VALUES(1);`;
export const BUSINESS_TABLES = [
  "app_settings",
  "chat_message",
  "chat_session",
  "companion_topic",
  "conversation_summary",
  "delegation",
  "delegation_checkpoint",
  "delegation_event",
  "delegation_event_consumed",
  "delegation_request",
  "delegation_revision",
  "delegation_run",
  "delegation_schedule",
  "delegation_schema",
  "delegation_usage",
  "dialogue_boundary",
  "dialogue_invitation",
  "dialogue_state",
  "engine_session",
  "hitl_approval_log",
  "jev_budget",
  "jev_decision",
  "knowledge_state",
  "learning_budget",
  "learning_job",
  "learning_schema",
  "memory_item",
  "migration_record",
  "model_usage",
  "notification",
  "personal_project",
  "pet_state",
  "project_context_use",
  "project_request",
  "project_schema",
  "project_session",
  "project_source",
  "relationship",
  "relationship_barrier",
  "relationship_revision",
  "schedule_dispatch",
  "schedule_owner",
  "service_event",
  "service_schema_version",
  "service_turn",
  "skill_candidate",
  "skill_candidate_revision",
  "skill_event",
  "skill_record",
  "skill_use",
  "skill_version",
  "task_acceptance",
  "task_effect",
  "task_record",
  "task_result",
  "turn_settlement",
  "unlocked_abilities",
  "user_themes",
  "workflow_active",
  "workflow_observation",
  "workflow_version"
] as const;
