"""Validated non-secret settings and opaque credential status for the renderer."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from core.config import Settings
from core.config.credentials import SECRET_FIELDS
from core.storage.db import Database

# Storage locations require backed-up migration, not a live textbox edit.
FIXED_FIELDS = {
    "data_dir",
    "workspace_path",
    "logs_dir",
    "nanobot_config_path",
    "skill_archive_dir",
    "memory_profile_file",
    "memory_system_profile_file",
    "memory_project_profile_file",
    "guardrails_enabled",
    "execution_governance_enabled",
}


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    values: dict[str, JsonValue] = Field(max_length=150)


class SettingsView(BaseModel):
    values: dict[str, JsonValue]
    schema_fields: dict[str, JsonValue]
    credentials: dict[str, bool]
    restart_required: bool = False


def apply_stored_settings(settings: Settings, db: Database) -> Settings:
    values = settings.model_dump()
    with db.get_connection() as conn:
        rows = conn.execute("SELECT key,value FROM app_settings").fetchall()
    for row in rows:
        key, raw = row["key"], row["value"]
        if key not in Settings.model_fields or key in SECRET_FIELDS or key in FIXED_FIELDS:
            continue
        current = values[key]
        if isinstance(current, str) or current is None:
            values[key] = raw
        else:
            try:
                values[key] = json.loads(raw)
            except json.JSONDecodeError:
                values[key] = raw
    return Settings.model_validate(values)


class SettingsService:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings, self.db = settings, db
        self.restart_required = False
        self.credential_status: dict[str, bool] = {}

    def view(self) -> SettingsView:
        effective = apply_stored_settings(self.settings, self.db)
        schema = Settings.model_json_schema()["properties"]
        values: dict[str, JsonValue] = {}
        fields: dict[str, JsonValue] = {}
        for key, value in effective.model_dump(mode="json").items():
            if key not in SECRET_FIELDS and key not in FIXED_FIELDS:
                values[key] = value
                # Defaults of secret fields never enter this descriptor.
                fields[key] = schema[key]
        return SettingsView(
            values=values,
            schema_fields=fields,
            credentials={
                key: self.credential_status.get(key, bool(getattr(effective, key, "")))
                for key in SECRET_FIELDS
            },
            restart_required=self.restart_required,
        )

    def patch(self, patch: SettingsPatch) -> SettingsView:
        allowed = set(self.view().values)
        if set(patch.values) - allowed:
            raise ValueError("此设置需要专用迁移或凭据入口")
        values = apply_stored_settings(self.settings, self.db).model_dump()
        values.update(patch.values)
        validated = Settings.model_validate(values)
        with self.db.transaction() as conn:
            for key in patch.values:
                value = getattr(validated, key)
                if isinstance(value, Path):
                    raise ValueError("路径配置需要专用迁移入口")  # noqa: TRY004 - wire validation
                serialized = (
                    value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                )
                conn.execute(
                    """INSERT INTO app_settings(key,value,updated_at) VALUES (?,?,datetime('now'))
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                    (key, serialized),
                )
            if "pet_name" in patch.values:
                conn.execute(
                    "UPDATE pet_state SET name=? WHERE id='default'", (validated.pet_name,)
                )
        self.restart_required = True
        return self.view()
