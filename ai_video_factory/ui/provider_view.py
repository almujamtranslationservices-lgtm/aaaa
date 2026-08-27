"""AI Providers page — registry table, key status, Test Connection (spec §24)."""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ai_video_factory.ai.factory import create_provider
from ai_video_factory.ai.llm.base import LLMProvider, LLMRequest
from ai_video_factory.config.providers import ProviderKind, ProviderInfo, providers_for
from ai_video_factory.core.event_bus import Event
from ai_video_factory.ui.widgets.event_bridge import on_event

if TYPE_CHECKING:
    from ai_video_factory.app import AppContext

_TIER_LABEL = {"local": "🟢 LOCAL", "free": "🔵 FREE", "paid": "🟠 PAID"}


class ProviderPage(QWidget):
    """Provider registry + connection tests. Keys are NEVER shown — only set/unset."""

    def __init__(self, context: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = context
        self._test_tasks: dict[str, tuple[str, ProviderInfo]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("AI Providers")
        title.setObjectName("SectionTitle")
        subtitle = QLabel("Free-first priority: LOCAL → FREE → PAID. Keys live in .env only — never in the DB or logs.")
        subtitle.setObjectName("MutedLabel")
        test_button = QPushButton("🔌  Test Selected")
        test_button.setObjectName("PrimaryButton")
        test_button.clicked.connect(self._test_selected)
        refresh_button = QPushButton("⟳  Refresh")
        refresh_button.clicked.connect(self.refresh)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(refresh_button)
        header.addWidget(test_button)
        root.addLayout(header)
        root.addWidget(subtitle)

        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            ["Kind", "Provider", "Tier", "Status", "API Key", "Model", "Endpoint", "Last Test"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.doubleClicked.connect(self._maybe_edit_model)
        root.addWidget(self._table, 1)

        legend = QLabel("“planned PHASE n” = registered in the architecture but not implemented yet "
                        "(spec §39 — the app never pretends a feature works). "
                        "Double-click a Model cell to override it (falls back to env/default).")
        legend.setObjectName("MutedLabel")
        legend.setWordWrap(True)
        root.addWidget(legend)

        on_event(self, self._ctx.bus, "task.succeeded", self._on_test_done)
        on_event(self, self._ctx.bus, "task.failed", self._on_test_failed)
        self.refresh()

    # ----------------------------------------------------------------- table
    def refresh(self) -> None:
        rows: list[tuple[ProviderInfo, dict[str, str]]] = []
        for kind in ProviderKind:
            for info in providers_for(kind):
                if info.env_key:
                    key_state = "✅ set" if os.environ.get(info.env_key) else "❌ missing (required)"
                else:
                    key_state = "—"
                status = "implemented" if info.implemented else f"planned PHASE {info.phase}"
                endpoint = os.environ.get(info.endpoint_env, "") if info.endpoint_env else ""
                endpoint = endpoint or (info.default_endpoint or "—")
                rows.append((info, {
                    "kind": kind.value.upper(), "tier": _TIER_LABEL.get(info.tier.value, info.tier.value),
                    "status": status, "key": key_state, "model": self._current_model(kind, info),
                    "endpoint": endpoint, "last": self._last_status(kind, info),
                }))
        self._table.setRowCount(len(rows))
        for row, (info, cells) in enumerate(rows):
            for column, value in enumerate(
                (cells["kind"], f"{info.id} — {info.name}", cells["tier"], cells["status"],
                 cells["key"], cells["model"], cells["endpoint"], cells["last"])
            ):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setData(Qt.UserRole, info)
                if column == 5:  # Model — editable hint
                    item.setToolTip("Double-click to override this provider's model")
                self._table.setItem(row, column, item)

    def _current_model(self, kind: ProviderKind, info: ProviderInfo) -> str:
        """Model shown in the table: DB override → env → default → —."""
        from ai_video_factory.ai.factory import create_provider

        for entry in self._ctx.provider_repo.list(kind.value):
            if entry["provider_id"] == info.id and entry["model"]:
                return f"{entry['model']} (custom)"
        try:
            provider = create_provider(kind, info.id)
            return str(getattr(provider, "model", "") or "—")
        except Exception:  # noqa: BLE001 — not implemented / not configured
            return "—"

    def _maybe_edit_model(self, index) -> None:
        """Double-click on the Model column opens an editor persisted to the DB."""
        if index.column() != 5:
            return
        info_item = self._table.item(index.row(), 1)
        kind_item = self._table.item(index.row(), 0)
        if not info_item or not kind_item:
            return
        info: ProviderInfo = info_item.data(Qt.UserRole)
        from PySide6.QtWidgets import QInputDialog

        current = ""
        for entry in self._ctx.provider_repo.list(info.kind.value):
            if entry["provider_id"] == info.id and entry["model"]:
                current = entry["model"]
                break
        value, ok = QInputDialog.getText(
            self, f"Model — {info.id}",
            f"Model override for '{info.id}' (empty = use env/default):",
            text=current,
        )
        if not ok:
            return
        self._ctx.provider_repo.upsert(
            info.kind.value, info.id, model=value.strip() or None,
            endpoint=os.environ.get(info.endpoint_env, "") if info.endpoint_env else info.default_endpoint,
            api_key_env=info.env_key,
        )
        self.refresh()

    def _last_status(self, kind: ProviderKind, info: ProviderInfo) -> str:
        row = self._ctx.provider_repo.list(kind.value)
        for entry in row:
            if entry["provider_id"] == info.id:
                return entry["last_status"] or ""
        return ""

    # ------------------------------------------------------------------ tests
    def _selected_info(self) -> ProviderInfo | None:
        item = self._table.item(self._table.currentRow(), 1) if self._table.currentRow() >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def _test_selected(self) -> None:
        info = self._selected_info()
        if info is None:
            QMessageBox.information(self, "Select a provider", "Select a provider row first.")
            return
        kind = info.kind
        model_override = None
        for entry in self._ctx.provider_repo.list(kind.value):
            if entry["provider_id"] == info.id and entry["model"]:
                model_override = entry["model"]
                break

        def job(tctx: Any) -> str:
            provider = create_provider(kind, info.id, model=model_override)
            if isinstance(provider, LLMProvider):
                result = asyncio.run(provider.test_connection())
                return "online" if result else "unavailable"
            ok = asyncio.run(provider.test_connection())
            return "online" if ok else "unavailable"

        self._ctx.provider_repo.upsert(
            kind.value, info.id, model=model_override,
            endpoint=os.environ.get(info.endpoint_env, "") if info.endpoint_env else info.default_endpoint,
            api_key_env=info.env_key,
        )
        task = self._ctx.task_manager.submit(
            f"test:{kind.value}:{info.id}", job, max_retries=0, metadata={"kind": "provider-test"},
        )
        self._test_tasks[task.id] = (kind.value, info)
        self._set_last_test(kind.value, info.id, "testing…")

    def _on_test_done(self, event: Event) -> None:
        entry = self._test_tasks.pop(event.payload.get("task_id", ""), None)
        if not entry:
            return
        kind_value, info = entry
        self._ctx.provider_repo.set_status(kind_value, info.id, "online")
        self._set_last_test(kind_value, info.id, f"✅ {event.payload.get('result') or 'online'}")

    def _on_test_failed(self, event: Event) -> None:
        entry = self._test_tasks.pop(event.payload.get("task_id", ""), None)
        if not entry:
            return
        kind_value, info = entry
        error = str(event.payload.get("error", ""))[:80]
        self._ctx.provider_repo.set_status(kind_value, info.id, f"error: {error}")
        self._set_last_test(kind_value, info.id, f"❌ {error}")

    def _set_last_test(self, kind_value: str, provider_id: str, text: str) -> None:
        for row in range(self._table.rowCount()):
            kind_item = self._table.item(row, 0)
            name_item = self._table.item(row, 1)
            if kind_item and name_item and kind_item.text() == kind_value.upper() \
                    and name_item.text().split(" — ")[0] == provider_id:
                self._table.setItem(row, 7, QTableWidgetItem(text))
