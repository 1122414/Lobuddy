"""Settings window for Lobuddy."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
)

from app.config import Settings, reload_settings
from core.storage.settings_repo import SettingsRepository


class SettingsWindow(QDialog):
    """Settings configuration dialog."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.repo = SettingsRepository()
        self._init_ui()

    def showEvent(self, event):
        """Reload settings each time window opens."""
        super().showEvent(event)
        self.settings = reload_settings()
        self._refresh_ui()

    def _init_ui(self):
        self.setWindowTitle("Lobuddy Settings")
        self.setMinimumWidth(450)

        layout = QFormLayout(self)

        # Pet name
        self.pet_name_input = QLineEdit(self.settings.pet_name)
        layout.addRow("Pet Name:", self.pet_name_input)

        # LLM API Key (masked)
        api_key_layout = QHBoxLayout()
        self.api_key_input = QLineEdit(self.settings.llm_api_key)
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_toggle = QPushButton("Show")
        self.api_key_toggle.setCheckable(True)
        self.api_key_toggle.clicked.connect(self._toggle_api_key_visibility)
        api_key_layout.addWidget(self.api_key_input)
        api_key_layout.addWidget(self.api_key_toggle)
        layout.addRow("LLM API Key:", api_key_layout)

        # LLM Base URL
        self.base_url_input = QLineEdit(self.settings.llm_base_url)
        layout.addRow("LLM Base URL:", self.base_url_input)

        # LLM Model
        self.model_input = QLineEdit(self.settings.llm_model)
        layout.addRow("LLM Model:", self.model_input)

        # Task timeout
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(30, 600)
        self.timeout_spin.setValue(self.settings.task_timeout)
        layout.addRow("Task Timeout (s):", self.timeout_spin)

        # Shell enabled
        self.shell_check = QCheckBox("Enable Shell Tool (dangerous)")
        self.shell_check.setChecked(self.settings.shell_enabled)
        layout.addRow("Tools:", self.shell_check)

        # Buttons
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._on_save)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addRow(btn_layout)

    def _refresh_ui(self):
        """Update UI fields from current settings."""
        self.pet_name_input.setText(self.settings.pet_name)
        self.api_key_input.setText(self.settings.llm_api_key)
        self.base_url_input.setText(self.settings.llm_base_url)
        self.model_input.setText(self.settings.llm_model)
        self.timeout_spin.setValue(self.settings.task_timeout)
        self.shell_check.setChecked(self.settings.shell_enabled)

    def _toggle_api_key_visibility(self):
        if self.api_key_toggle.isChecked():
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.api_key_toggle.setText("Hide")
        else:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.api_key_toggle.setText("Show")

    def _validate_settings(self) -> str | None:
        """Validate settings inputs. Returns error message or None if valid."""
        pet_name = self.pet_name_input.text().strip()
        if not pet_name:
            return "Pet name cannot be empty."
        if len(pet_name) > 50:
            return "Pet name must be 50 characters or fewer."

        base_url = self.base_url_input.text().strip()
        if base_url:
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return f"Invalid URL format: {base_url}"

        model = self.model_input.text().strip()
        if not model:
            return "LLM Model cannot be empty."

        return None

    def _on_save(self):
        error = self._validate_settings()
        if error:
            QMessageBox.warning(self, "Validation Error", error)
            return

        try:
            # Save to SQLite (source of truth)
            self.repo.set_setting("pet_name", self.pet_name_input.text().strip())
            self.repo.set_setting("llm_api_key", self.api_key_input.text())
            self.repo.set_setting("llm_base_url", self.base_url_input.text().strip())
            self.repo.set_setting("llm_model", self.model_input.text().strip())
            self.repo.set_setting("task_timeout", str(self.timeout_spin.value()))
            self.repo.set_setting("shell_enabled", str(self.shell_check.isChecked()))

            reload_settings()

            QMessageBox.information(self, "Success", "Settings saved successfully!")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")

    def _export_to_env(self):
        """Export settings to .env file as backup."""
        env_path = Path(".env")
        lines = []

        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        updates = {
            "PET_NAME": self.pet_name_input.text(),
            "LLM_API_KEY": self.api_key_input.text(),
            "LLM_BASE_URL": self.base_url_input.text(),
            "LLM_MODEL": self.model_input.text(),
            "TASK_TIMEOUT": str(self.timeout_spin.value()),
            "RESULT_POPUP_DURATION": str(self.popup_spin.value()),
            "SHELL_ENABLED": str(self.shell_check.isChecked()),
        }

        updated_keys = set()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                new_lines.append(line)
                continue

            key = stripped.split("=")[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
            else:
                new_lines.append(line)

        for key, value in updates.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
