"""Settings page — behaviour, tasks, autosave and provider selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ai_video_factory.config.providers import ProviderKind, providers_for

if TYPE_CHECKING:
    from ai_video_factory.app import AppContext


class SettingsPage(QWidget):
    """Edits AppSettings through SettingsService (persisted to config/settings.json)."""

    def __init__(self, context: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = context

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("Settings")
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        behaviour = QGroupBox("Behaviour")
        behaviour_form = QFormLayout(behaviour)
        self._demo_check = QCheckBox("Demo mode — offline mock providers (no API keys needed)")
        self._language_combo = QComboBox()
        for code, label in (("ar", "العربية (Arabic)"), ("en", "English")):
            self._language_combo.addItem(label, code)
        self._log_level_combo = QComboBox()
        for level in ("DEBUG", "INFO", "WARNING", "ERROR"):
            self._log_level_combo.addItem(level)
        behaviour_form.addRow("Mode", self._demo_check)
        behaviour_form.addRow("Content language", self._language_combo)
        behaviour_form.addRow("Log level", self._log_level_combo)
        root.addWidget(behaviour)

        tasks = QGroupBox("Tasks & Autosave")
        tasks_form = QFormLayout(tasks)
        self._autosave_check = QCheckBox("Auto-save projects on every change")
        self._autosave_interval = QDoubleSpinBox()
        self._autosave_interval.setRange(5.0, 600.0)
        self._autosave_interval.setSuffix(" s")
        self._parallel_spin = QSpinBox()
        self._parallel_spin.setRange(1, 32)
        self._retry_spin = QSpinBox()
        self._retry_spin.setRange(1, 10)
        self._timeout_spin = QDoubleSpinBox()
        self._timeout_spin.setRange(10.0, 3600.0)
        self._timeout_spin.setSuffix(" s")
        tasks_form.addRow("Autosave", self._autosave_check)
        tasks_form.addRow("Autosave interval", self._autosave_interval)
        tasks_form.addRow("Max parallel tasks", self._parallel_spin)
        tasks_form.addRow("Retry attempts", self._retry_spin)
        tasks_form.addRow("Provider request timeout", self._timeout_spin)
        root.addWidget(tasks)

        providers = QGroupBox("Default Providers (free-first chains)")
        providers_form = QFormLayout(providers)
        self._provider_combos: dict[ProviderKind, QComboBox] = {}
        for kind in ProviderKind:
            combo = QComboBox()
            for info in providers_for(kind):
                suffix = "" if info.implemented else f"  (planned PHASE {info.phase})"
                combo.addItem(f"{info.id} — {info.name}{suffix}", info.id)
            self._provider_combos[kind] = combo
            providers_form.addRow(kind.value.upper(), combo)
        root.addWidget(providers)

        paths = QGroupBox("Storage (read-only — change via config/settings.json or env)")
        paths_form = QFormLayout(paths)
        for label_text, attr in (
            ("Projects", "projects_dir"), ("Output", "output_dir"),
            ("Logs", "logs_dir"), ("Database", "database_path"),
        ):
            line = QLineEdit()
            line.setReadOnly(True)
            setattr(self, f"_{attr}_line", line)
            paths_form.addRow(label_text, line)
        root.addWidget(paths)

        footer = QHBoxLayout()
        self._save_button = QPushButton("💾  Save Settings")
        self._save_button.setObjectName("PrimaryButton")
        self._save_button.clicked.connect(self._save)
        self._status = QLabel("")
        self._status.setObjectName("MutedLabel")
        footer.addWidget(self._save_button)
        footer.addWidget(self._status)
        footer.addStretch(1)
        root.addLayout(footer)
        root.addStretch(1)

        self.load()

    # -------------------------------------------------------------------- data
    def load(self) -> None:
        settings = self._ctx.settings_service.settings
        self._demo_check.setChecked(settings.demo_mode)
        self._language_combo.setCurrentIndex(max(0, self._language_combo.findData(settings.language)))
        self._log_level_combo.setCurrentText(settings.log_level)
        self._autosave_check.setChecked(settings.autosave_enabled)
        self._autosave_interval.setValue(settings.autosave_interval_seconds)
        self._parallel_spin.setValue(settings.max_parallel_tasks)
        self._retry_spin.setValue(settings.retry_max_attempts)
        self._timeout_spin.setValue(settings.request_timeout_seconds)
        for kind, combo in self._provider_combos.items():
            selected = getattr(settings.providers, kind.value)
            index = combo.findData(selected)
            combo.setCurrentIndex(max(0, index))
        self._projects_dir_line.setText(str(settings.projects_dir))
        self._output_dir_line.setText(str(settings.output_dir))
        self._logs_dir_line.setText(str(settings.logs_dir))
        self._database_path_line.setText(str(settings.database_path))

    def _save(self) -> None:
        provider_selection = {kind.value: combo.currentData() for kind, combo in self._provider_combos.items()}
        self._ctx.settings_service.update(
            demo_mode=self._demo_check.isChecked(),
            language=self._language_combo.currentData(),
            log_level=self._log_level_combo.currentText(),
            autosave_enabled=self._autosave_check.isChecked(),
            autosave_interval_seconds=self._autosave_interval.value(),
            max_parallel_tasks=self._parallel_spin.value(),
            retry_max_attempts=self._retry_spin.value(),
            request_timeout_seconds=self._timeout_spin.value(),
            providers=provider_selection,
        )
        self._status.setText("Saved ✓ — task/provider changes apply immediately; log level on restart.")
