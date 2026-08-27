"""Project page — VIDEO IDEA box, Generate Script (real), scene results.

The "Generate Everything" button stays disabled until the pipeline stages
land (PHASE 6+): no fake functionality (spec §39).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ai_video_factory.config.providers import ProviderKind, providers_for
from ai_video_factory.core.event_bus import Event
from ai_video_factory.core.exceptions import AVFError
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.core.task_manager import TaskManager
from ai_video_factory.models.project import Project, ProjectStatus
from ai_video_factory.models.scene import Script
from ai_video_factory.services.script_service import generate_script
from ai_video_factory.ui.widgets.event_bridge import on_event
from ai_video_factory.ui.widgets.progress_panel import ProgressPanel

if TYPE_CHECKING:
    from ai_video_factory.app import AppContext


class ProjectPage(QWidget):
    """Workspace for the currently open project."""

    scenesChanged = Signal()

    def __init__(self, context: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = context
        self._project: Project | None = None
        self._generating_task_id: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # ---- header ----------------------------------------------------
        header = QFrame()
        header.setObjectName("Card")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18, 12, 18, 12)
        top = QHBoxLayout()
        self._name_label = QLabel("No project open")
        self._name_label.setObjectName("SectionTitle")
        self._status_chip = QLabel("—")
        self._status_chip.setObjectName("Chip")
        top.addWidget(self._name_label)
        top.addStretch(1)
        top.addWidget(self._status_chip)
        header_layout.addLayout(top)
        self._meta_label = QLabel("Create or open a project from the Dashboard.")
        self._meta_label.setObjectName("MutedLabel")
        header_layout.addWidget(self._meta_label)
        root.addWidget(header)

        # ---- idea ------------------------------------------------------
        idea_box = QGroupBox("VIDEO IDEA")
        idea_layout = QVBoxLayout(idea_box)
        self._idea_edit = QPlainTextEdit()
        self._idea_edit.setPlaceholderText(
            "اكتب فكرة الفيديو هنا…\n"
            "Example: قصة اختفاء غامض حدث منذ 100 عام ولم يعرف أحد الحقيقة حتى اليوم."
        )
        self._idea_edit.setMinimumHeight(96)
        idea_layout.addWidget(self._idea_edit)

        controls = QHBoxLayout()
        self._provider_combo = QComboBox()
        self._provider_combo.setMinimumWidth(200)
        self._image_provider_combo = QComboBox()
        self._image_provider_combo.setMinimumWidth(200)
        self._generate_button = QPushButton("✨  Generate Script")
        self._generate_button.setObjectName("PrimaryButton")
        self._generate_button.clicked.connect(self._generate_script)
        self._prompts_button = QPushButton("🧩  Build Scene Prompts")
        self._prompts_button.setToolTip(
            "Enriches each scene (environment/action/lighting) and writes the full\n"
            "image + video prompts with the Character Bible injected — one prompt.json\n"
            "per scene under scenes/scene_XXX/ (cached; failed scenes can be retried)."
        )
        self._prompts_button.clicked.connect(self._build_scene_prompts)
        self._images_button = QPushButton("🎨  Generate Images")
        self._images_button.setToolTip(
            "Generates scene_XXX/image.png for every scene using the selected image\n"
            "provider (demo = offline placeholder art). Existing images are cached\n"
            "and skipped; failed scenes are isolated and can be retried."
        )
        self._images_button.clicked.connect(self._generate_images)
        self._video_provider_combo = QComboBox()
        self._video_provider_combo.setMinimumWidth(190)
        self._videos_button = QPushButton("🎞  Generate Videos")
        self._videos_button.setToolTip(
            "Animates each scene image into scene_XXX/video.mp4 using the selected\n"
            "image-to-video provider (demo = Ken Burns motion via FFmpeg, offline).\n"
            "Existing clips are cached; scenes without images are skipped."
        )
        self._videos_button.clicked.connect(self._generate_videos)
        self._voice_provider_combo = QComboBox()
        self._voice_provider_combo.setMinimumWidth(180)
        self._voices_button = QPushButton("🔊  Generate Voice")
        self._voices_button.setToolTip(
            "Synthesises each scene's narration into scene_XXX/voice.wav using the\n"
            "selected TTS provider (demo = offline speech-like tones, edge = free\n"
            "Microsoft voices). Cached per scene; scenes without narration are skipped."
        )
        self._voices_button.clicked.connect(self._generate_voices)
        self._mix_button = QPushButton("🎚  Mix Audio")
        self._mix_button.setToolTip(
            "Builds the project music bed + per-scene SFX, then mixes every scene:\n"
            "voice + music (auto-ducked while the narrator speaks) + SFX →\n"
            "scenes/scene_XXX/mix.wav. Cached; failures isolated per scene."
        )
        self._mix_button.clicked.connect(self._mix_audio)
        self._subs_button = QPushButton("💬  Subtitles")
        self._subs_button.setToolTip(
            "Splits every scene's narration into timed cues (real voice.wav durations\n"
            "when available) and writes per-scene subtitle.srt plus a combined\n"
            "subtitles.srt/.ass with the project's styling. Cached per scene."
        )
        self._subs_button.clicked.connect(self._generate_subtitles)
        self._seo_button = QPushButton("📈  SEO")
        self._seo_button.setToolTip(
            "Publication metadata: title / description / tags / hashtags /\n"
            "chapters built from the real timeline — then EDITABLE in a dialog.\n"
            "Cached in seo.json (demo provider builds it fully offline)."
        )
        self._seo_button.clicked.connect(self._open_seo)
        self._thumb_button = QPushButton("🖼  Thumbnail")
        self._thumb_button.setToolTip(
            "Branded 1280x720 thumbnail: a real frame of the final video\n"
            "(or a scene image) + bold editable title/subtitle + duration chip.\n"
            "Uses the bundled Cairo font — full Arabic shaping, fully offline."
        )
        self._thumb_button.clicked.connect(self._open_thumbnail)
        self._generate_all_button = QPushButton("🎬  Generate Everything")
        self._generate_all_button.setToolTip(
            "Runs the WHOLE pipeline in one background task:\n"
            "script → scenes → prompts → images → videos → voice → mixes →\n"
            "subtitles → timeline → FINAL RENDER (output/final.mp4).\n"
            "Every stage is cached — re-running resumes where it stopped."
        )
        self._generate_all_button.clicked.connect(self._generate_everything)
        save_button = QPushButton("💾  Save Project")
        save_button.clicked.connect(self._save_project)
        controls.addWidget(QLabel("LLM:"))
        controls.addWidget(self._provider_combo)
        controls.addWidget(QLabel("Image:"))
        controls.addWidget(self._image_provider_combo)
        controls.addWidget(QLabel("Video:"))
        controls.addWidget(self._video_provider_combo)
        controls.addWidget(QLabel("Voice:"))
        controls.addWidget(self._voice_provider_combo)
        controls.addSpacing(12)
        controls.addWidget(self._generate_button)
        controls.addWidget(self._prompts_button)
        controls.addWidget(self._images_button)
        controls.addWidget(self._videos_button)
        controls.addWidget(self._voices_button)
        controls.addWidget(self._mix_button)
        controls.addWidget(self._subs_button)
        controls.addWidget(self._seo_button)
        controls.addWidget(self._thumb_button)
        controls.addWidget(self._generate_all_button)
        controls.addStretch(1)
        controls.addWidget(save_button)

        # Second row: narrator voice selection (applies to the whole project).
        voice_row = QHBoxLayout()
        voice_row.addWidget(QLabel("Narrator voice:"))
        self._voice_name_combo = QComboBox()
        self._voice_name_combo.setEditable(True)
        for voice, label in (
            ("ar-SA-HamedNeural", "Hamed — العربية (Saudi male)"),
            ("ar-EG-ShakirNeural", "Shakir — العربية (Egyptian male)"),
            ("ar-EG-SalmaNeural", "Salma — العربية (Egyptian female)"),
            ("ar-SA-ZariyahNeural", "Zariyah — العربية (Saudi female)"),
            ("en-US-GuyNeural", "Guy — English (US male)"),
            ("en-US-JennyNeural", "Jenny — English (US female)"),
            ("en-GB-RyanNeural", "Ryan — English (UK male)"),
        ):
            self._voice_name_combo.addItem(label, voice)
        self._voice_name_combo.setToolTip(
            "Edge TTS voice id (editable). For ElevenLabs use a voice id/name; for Piper use the model id."
        )
        self._voice_name_combo.currentIndexChanged.connect(self._apply_voice_selection)
        voice_row.addWidget(self._voice_name_combo, 1)
        voice_row.addStretch(1)
        idea_layout.addLayout(voice_row)
        idea_layout.addLayout(controls)

        self._progress = ProgressPanel(self._ctx.task_manager, self._ctx.bus)
        idea_layout.addWidget(self._progress)
        root.addWidget(idea_box)

        # ---- script result ---------------------------------------------
        script_box = QGroupBox("Generated Script")
        script_layout = QVBoxLayout(script_box)
        summary = QHBoxLayout()
        self._script_title = QLabel("—")
        self._script_title.setObjectName("CardTitle")
        self._script_stats = QLabel("")
        self._script_stats.setObjectName("MutedLabel")
        summary.addWidget(self._script_title, 2)
        summary.addWidget(self._script_stats, 1)
        script_layout.addLayout(summary)
        self._script_hook = QLabel("")
        self._script_hook.setObjectName("MutedLabel")
        self._script_hook.setWordWrap(True)
        script_layout.addWidget(self._script_hook)

        self._scenes_table = QTableWidget(0, 4)
        self._scenes_table.setHorizontalHeaderLabels(["#", "Duration (s)", "Narration", "Status"])
        self._scenes_table.horizontalHeader().setStretchLastSection(True)
        self._scenes_table.setColumnWidth(0, 40)
        self._scenes_table.setColumnWidth(1, 90)
        self._scenes_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._scenes_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._scenes_table.setAlternatingRowColors(True)
        self._scenes_table.verticalHeader().setVisible(False)
        self._scenes_table.setMaximumHeight(240)
        script_layout.addWidget(self._scenes_table)
        root.addWidget(script_box)
        root.addStretch(1)

        self._populate_providers()
        on_event(self, self._ctx.bus, "script.generated", self._on_script_generated)
        on_event(self, self._ctx.bus, "scenes.prompted", self._on_scenes_prompted)
        on_event(self, self._ctx.bus, "images.generated", self._on_images_generated)
        on_event(self, self._ctx.bus, "videos.generated", self._on_videos_generated)
        on_event(self, self._ctx.bus, "voices.voice_generated", self._on_voices_generated)
        on_event(self, self._ctx.bus, "audio.mixed", self._on_audio_mixed)
        on_event(self, self._ctx.bus, "subtitles.generated", self._on_subtitles_generated)
        on_event(self, self._ctx.bus, "render.completed", self._on_render_completed)
        on_event(self, self._ctx.bus, "seo.generated", self._on_seo_generated)
        on_event(self, self._ctx.bus, "thumbnail.generated", self._on_thumbnail_generated)
        on_event(self, self._ctx.bus, "task.succeeded", lambda e: self._on_task_terminal(e))
        on_event(self, self._ctx.bus, "task.failed", lambda e: self._on_task_terminal(e))
        on_event(self, self._ctx.bus, "task.cancelled", lambda e: self._on_task_terminal(e))
        self._update_enabled()

    # --------------------------------------------------------------- providers
    def _populate_providers(self) -> None:
        self._provider_combo.clear()
        for info in providers_for(ProviderKind.LLM):
            label = f"{info.id} — {info.name}" if info.implemented else f"{info.id} — {info.name} (planned PHASE {info.phase})"
            self._provider_combo.addItem(label, info.id)
            if info.id == self._ctx.settings_service.settings.providers.llm:
                self._provider_combo.setCurrentText(label)
        self._image_provider_combo.clear()
        for info in providers_for(ProviderKind.IMAGE):
            label = f"{info.id} — {info.name}" if info.implemented else f"{info.id} — {info.name} (planned PHASE {info.phase})"
            self._image_provider_combo.addItem(label, info.id)
            if info.id == self._ctx.settings_service.settings.providers.image:
                self._image_provider_combo.setCurrentText(label)
        self._video_provider_combo.clear()
        for info in providers_for(ProviderKind.VIDEO):
            label = f"{info.id} — {info.name}" if info.implemented else f"{info.id} — {info.name} (planned PHASE {info.phase})"
            self._video_provider_combo.addItem(label, info.id)
            if info.id == self._ctx.settings_service.settings.providers.video:
                self._video_provider_combo.setCurrentText(label)
        self._voice_provider_combo.clear()
        for info in providers_for(ProviderKind.VOICE):
            label = f"{info.id} — {info.name}" if info.implemented else f"{info.id} — {info.name} (planned PHASE {info.phase})"
            self._voice_provider_combo.addItem(label, info.id)
            if info.id == self._ctx.settings_service.settings.providers.voice:
                self._voice_provider_combo.setCurrentText(label)

    # ---------------------------------------------------------------- project
    def set_project(self, project: Project | None) -> None:
        self._project = project
        self._idea_edit.setPlainText(project.idea if project else "")
        if project is not None:
            # Reflect the project's narrator voice in the selector.
            voice = project.settings.voice.voice
            index = self._voice_name_combo.findData(voice)
            if index >= 0:
                self._voice_name_combo.setCurrentIndex(index)
            else:
                self._voice_name_combo.setEditText(voice)
        self._refresh_ui()

    def _refresh_ui(self) -> None:
        project = self._project
        if project is None:
            self._name_label.setText("No project open")
            self._meta_label.setText("Create or open a project from the Dashboard.")
            self._status_chip.setText("—")
            self._scenes_table.setRowCount(0)
            self._script_title.setText("—")
            self._script_stats.setText("")
            self._script_hook.setText("")
        else:
            self._name_label.setText(project.name)
            self._meta_label.setText(
                f"{project.video_type.value.replace('_', ' ').title()} · {project.aspect_ratio.value} · "
                f"{project.resolution.value.upper()} · {project.fps} FPS · target {project.target_duration:.0f}s"
                f"  →  {project.width}×{project.height}"
            )
            self._status_chip.setText(project.status.value.replace("_", " "))
            self._fill_scenes(project)
            if project.scenes:
                total = sum(scene.duration for scene in project.scenes)
                first = project.scenes[0]
                self._script_title.setText(f"“{project.name}”")
                self._script_stats.setText(f"{len(project.scenes)} scenes · {total:.1f}s total")
                self._script_hook.setText(first.narration[:160])
            else:
                self._script_title.setText("—")
                self._script_stats.setText("")
                self._script_hook.setText("")
        self._update_enabled()

    def _fill_scenes(self, project: Project) -> None:
        self._scenes_table.setRowCount(len(project.scenes))
        for row, scene in enumerate(project.scenes):
            narration = scene.narration if len(scene.narration) <= 110 else scene.narration[:110] + "…"
            for column, value in enumerate((str(scene.scene_id), f"{scene.duration:g}", narration, scene.status.value)):
                self._scenes_table.setItem(row, column, QTableWidgetItem(value))

    def _update_enabled(self) -> None:
        has_project = self._project is not None
        has_scenes = has_project and bool(self._project.scenes)
        busy = self._generating_task_id is not None
        self._idea_edit.setEnabled(has_project)
        self._generate_button.setEnabled(has_project and not busy)
        self._prompts_button.setEnabled(has_scenes and not busy)
        self._images_button.setEnabled(has_scenes and not busy)
        self._videos_button.setEnabled(has_scenes and not busy)
        self._voices_button.setEnabled(has_scenes and not busy)
        self._mix_button.setEnabled(has_scenes and not busy)
        self._subs_button.setEnabled(has_scenes and not busy)
        self._seo_button.setEnabled(has_project and not busy)
        self._thumb_button.setEnabled(has_project and not busy)
        for combo in (self._provider_combo, self._image_provider_combo,
                      self._video_provider_combo, self._voice_provider_combo,
                      self._voice_name_combo):
            combo.setEnabled(has_project)
        idea_ready = has_project and len((self._project.idea or "").strip()) >= 10
        self._generate_all_button.setEnabled((has_scenes or idea_ready) and not busy)

    # -------------------------------------------------------------- generation
    def _generate_script(self) -> None:
        project = self._project
        if project is None:
            QMessageBox.information(self, "No project", "Create or open a project first.")
            return
        idea = self._idea_edit.toPlainText().strip()
        if len(idea) < 10:
            QMessageBox.warning(
                self, "Idea too short",
                "Describe your video idea in at least 10 characters — the script is built from it.",
            )
            return
        project.idea = idea
        provider_id = self._provider_combo.currentData() or "demo"
        project_id = project.id
        model_override = self._ctx.provider_model("llm", provider_id)

        def job(tctx) -> str:
            tctx.report_stage("Generating script…")
            tctx.report_progress(0.2, "calling LLM provider")
            script = generate_script(
                idea=idea,
                language=project.settings.language,
                target_duration=project.target_duration,
                characters=project.characters,
                provider_id=provider_id,
                model=model_override,
            )
            tctx.report_progress(1.0, "script validated")
            # Announce on the bus — the UI (and any listener) reacts in the main thread.
            self._ctx.bus.publish("script.generated", project_id=project_id, script=script, provider=provider_id)
            return script.title

        task = self._ctx.task_manager.submit(
            f"script: {project.name}", job,
            max_retries=self._ctx.settings_service.settings.retry_max_attempts - 1,
            metadata={"project_id": project_id, "kind": "script"},
        )
        self._generating_task_id = task.id
        self._update_enabled()

    def _on_script_generated(self, event: Event) -> None:
        project = self._project
        script: Script = event.payload.get("script")
        if project is None or script is None or event.payload.get("project_id") != project.id:
            return
        project.scenes = script.to_rich_scenes()
        project.status = ProjectStatus.SCRIPT_READY
        self._save(autosave=True)
        self._refresh_ui()
        self.scenesChanged.emit()

    # ------------------------------------------------------- scene prompting
    def _build_scene_prompts(self) -> None:
        """Enrich scenes + write per-scene prompt.json (background, cache-aware)."""
        project = self._project
        if project is None or not project.scenes:
            QMessageBox.information(self, "No scenes", "Generate a script first.")
            return
        from ai_video_factory.services.scene_service import generate_scene_prompts

        provider_id = self._provider_combo.currentData() or "demo"
        model_override = self._ctx.provider_model("llm", provider_id)
        project_id = project.id

        def job(tctx) -> str:
            total = len(project.scenes)
            tctx.report_stage("Building scene prompts…")
            tctx.report_progress(0.1, "starting")
            result = generate_scene_prompts(
                project, self._ctx.project_manager,
                provider_id=provider_id, model=model_override,
            )
            tctx.report_progress(1.0, f"{len(result.generated)} generated, "
                                     f"{result.skipped_cached} cached")
            self._ctx.bus.publish(
                "scenes.prompted", project_id=project_id,
                generated=len(result.generated), cached=result.skipped_cached,
                failed=result.failed_scenes, provider=provider_id,
            )
            return (f"{len(result.generated)} generated, {result.skipped_cached} cached, "
                    f"{len(result.failed_scenes)} failed")

        task = self._ctx.task_manager.submit(
            f"prompts: {project.name}", job,
            max_retries=self._ctx.settings_service.settings.retry_max_attempts - 1,
            metadata={"project_id": project_id, "kind": "scene-prompts"},
        )
        self._generating_task_id = task.id
        self._update_enabled()

    def _on_scenes_prompted(self, event: Event) -> None:
        project = self._project
        if project is None or event.payload.get("project_id") != project.id:
            return
        if project.scenes and all(
            scene.status.value in ("prompted", "image_ready", "video_ready", "audio_ready", "done")
            for scene in project.scenes
        ):
            project.status = ProjectStatus.ASSETS_IN_PROGRESS
            self._save(autosave=True)
        self._refresh_ui()
        self.scenesChanged.emit()

    # ------------------------------------------------------- image generation
    def _generate_images(self) -> None:
        """Generate scene images in the background (cache-aware, isolated failures)."""
        project = self._project
        if project is None or not project.scenes:
            QMessageBox.information(self, "No scenes", "Generate a script first.")
            return
        from ai_video_factory.services.image_service import generate_scene_images

        provider_id = self._image_provider_combo.currentData() or "demo"
        model_override = self._ctx.provider_model("image", provider_id)
        project_id = project.id

        def job(tctx) -> str:
            from ai_video_factory.services.image_service import generate_scene_images as run

            tctx.report_stage("Generating scene images…")
            result = run(
                project, self._ctx.project_manager,
                provider_id=provider_id, model=model_override,
                asset_repo=self._ctx.asset_repo,
                on_progress=lambda done, total, sid: (
                    tctx.report_progress(done / total, f"scene {sid:03d}"),
                    tctx.report_stage(f"Images: scene {sid:03d}/{total:03d}"),
                ),
            )
            self._ctx.bus.publish(
                "images.generated", project_id=project_id,
                generated=len(result.generated), cached=result.skipped_cached,
                failed=result.failed_scenes, provider=provider_id,
            )
            return (f"{len(result.generated)} generated, {result.skipped_cached} cached, "
                    f"{len(result.failed_scenes)} failed")

        task = self._ctx.task_manager.submit(
            f"images: {project.name}", job,
            max_retries=self._ctx.settings_service.settings.retry_max_attempts - 1,
            metadata={"project_id": project_id, "kind": "scene-images"},
        )
        self._generating_task_id = task.id
        self._update_enabled()

    def _on_images_generated(self, event: Event) -> None:
        project = self._project
        if project is None or event.payload.get("project_id") != project.id:
            return
        if project.scenes and any(
            scene.status.value in ("image_ready", "video_ready", "audio_ready", "done")
            for scene in project.scenes
        ):
            project.status = ProjectStatus.ASSETS_IN_PROGRESS
            self._save(autosave=True)
        self._refresh_ui()
        self.scenesChanged.emit()

    # ------------------------------------------------------- video generation
    def _generate_videos(self) -> None:
        """Animate scene images into clips in the background (cache-aware)."""
        project = self._project
        if project is None or not project.scenes:
            QMessageBox.information(self, "No scenes", "Generate a script first.")
            return
        provider_id = self._video_provider_combo.currentData() or "demo"
        model_override = self._ctx.provider_model("video", provider_id)
        project_id = project.id

        def job(tctx) -> str:
            from ai_video_factory.services.video_service import generate_scene_videos as run

            tctx.report_stage("Generating scene videos…")
            result = run(
                project, self._ctx.project_manager,
                provider_id=provider_id, model=model_override,
                asset_repo=self._ctx.asset_repo,
                on_progress=lambda done, total, sid: (
                    tctx.report_progress(done / total, f"scene {sid:03d}"),
                    tctx.report_stage(f"Videos: scene {sid:03d}/{total:03d}"),
                ),
            )
            self._ctx.bus.publish(
                "videos.generated", project_id=project_id,
                generated=len(result.generated), cached=result.skipped_cached,
                no_image=result.skipped_no_image, failed=result.failed_scenes,
                provider=provider_id,
            )
            return (f"{len(result.generated)} generated, {result.skipped_cached} cached, "
                    f"{len(result.failed_scenes)} failed")

        task = self._ctx.task_manager.submit(
            f"videos: {project.name}", job,
            max_retries=self._ctx.settings_service.settings.retry_max_attempts - 1,
            metadata={"project_id": project_id, "kind": "scene-videos"},
        )
        self._generating_task_id = task.id
        self._update_enabled()

    def _on_videos_generated(self, event: Event) -> None:
        project = self._project
        if project is None or event.payload.get("project_id") != project.id:
            return
        self._refresh_ui()
        self.scenesChanged.emit()

    # ------------------------------------------------------- voice generation
    def _apply_voice_selection(self, index: int) -> None:
        """Store the chosen narrator voice on the project (saved on next save)."""
        if self._project is None or index < 0:
            return
        voice = self._voice_name_combo.currentData() or self._voice_name_combo.currentText()
        if voice:
            self._project.settings.voice.voice = str(voice)

    def _generate_voices(self) -> None:
        """Synthesise scene narrations in the background (cache-aware)."""
        project = self._project
        if project is None or not project.scenes:
            QMessageBox.information(self, "No scenes", "Generate a script first.")
            return
        # Persist any manual voice id typed into the editable combo.
        project.settings.voice.voice = (
            self._voice_name_combo.currentData() or self._voice_name_combo.currentText().strip()
            or project.settings.voice.voice
        )
        provider_id = self._voice_provider_combo.currentData() or "demo"
        model_override = self._ctx.provider_model("voice", provider_id)
        project_id = project.id

        def job(tctx) -> str:
            from ai_video_factory.services.voice_service import generate_scene_voices as run

            tctx.report_stage("Generating scene voices…")
            result = run(
                project, self._ctx.project_manager,
                provider_id=provider_id, model=model_override,
                asset_repo=self._ctx.asset_repo,
                on_progress=lambda done, total, sid: (
                    tctx.report_progress(done / total, f"scene {sid:03d}"),
                    tctx.report_stage(f"Voice: scene {sid:03d}/{total:03d}"),
                ),
            )
            self._ctx.bus.publish(
                "voices.voice_generated", project_id=project_id,
                generated=len(result.generated), cached=result.skipped_cached,
                no_narration=result.skipped_no_narration, failed=result.failed_scenes,
                provider=provider_id,
            )
            return (f"{len(result.generated)} generated, {result.skipped_cached} cached, "
                    f"{len(result.failed_scenes)} failed")

        task = self._ctx.task_manager.submit(
            f"voices: {project.name}", job,
            max_retries=self._ctx.settings_service.settings.retry_max_attempts - 1,
            metadata={"project_id": project_id, "kind": "scene-voices"},
        )
        self._generating_task_id = task.id
        self._update_enabled()


    # ---------------------------------------------------------- audio mixing
    def _mix_audio(self) -> None:
        """Music bed + SFX + per-scene voice/music ducked mix (background)."""
        project = self._project
        if project is None or not project.scenes:
            QMessageBox.information(self, "No scenes", "Generate a script first.")
            return
        project_id = project.id

        def job(tctx) -> str:
            from ai_video_factory.services.audio_service import generate_scene_mixes

            tctx.report_stage("Mixing scene audio…")
            result = generate_scene_mixes(
                project, self._ctx.project_manager,
                asset_repo=self._ctx.asset_repo,
                on_progress=lambda done, total, sid: (
                    tctx.report_progress(done / total, f"scene {sid:03d}"),
                    tctx.report_stage(f"Mix: scene {sid:03d}/{total:03d}"),
                ),
            )
            self._ctx.bus.publish(
                "audio.mixed", project_id=project_id,
                mixes=len(result.mixes), cached=result.cached,
                failed=result.failed_scenes,
                music_generated=result.music_generated,
            )
            return f"{len(result.mixes)} mixed, {result.cached} cached, {len(result.failed_scenes)} failed"

        task = self._ctx.task_manager.submit(
            f"mix: {project.name}", job,
            max_retries=self._ctx.settings_service.settings.retry_max_attempts - 1,
            metadata={"project_id": project_id, "kind": "audio-mix"},
        )
        self._generating_task_id = task.id
        self._update_enabled()


    # -------------------------------------------------------------- subtitles
    def _generate_subtitles(self) -> None:
        """Per-scene SRT + combined project subtitles (background)."""
        project = self._project
        if project is None or not project.scenes:
            QMessageBox.information(self, "No scenes", "Generate a script first.")
            return
        project_id = project.id

        def job(tctx) -> str:
            from ai_video_factory.services.subtitle_service import generate_subtitles

            tctx.report_stage("Generating subtitles…")
            result = generate_subtitles(project, self._ctx.project_manager)
            self._ctx.bus.publish(
                "subtitles.generated", project_id=project_id,
                scenes=len(result.scene_files), cached=result.cached,
                cues=result.cue_count, skipped=len(result.skipped_no_narration),
            )
            return f"{len(result.scene_files)} scenes, {result.cue_count} cues"

        task = self._ctx.task_manager.submit(
            f"subtitles: {project.name}", job,
            max_retries=self._ctx.settings_service.settings.retry_max_attempts - 1,
            metadata={"project_id": project_id, "kind": "subtitles"},
        )
        self._generating_task_id = task.id
        self._update_enabled()

    # ---------------------------------------------------- generate everything
    def _generate_everything(self) -> None:
        """The full pipeline in ONE background task (cached stages resume)."""
        project = self._project
        if project is None:
            QMessageBox.information(self, "No project", "Create or open a project first.")
            return
        idea = self._idea_edit.toPlainText().strip()
        if not project.scenes and len(idea) < 10:
            QMessageBox.warning(
                self, "Idea too short",
                "Describe the video idea (10+ characters) or generate a script first.",
            )
            return
        if idea:
            project.idea = idea
        project_id = project.id
        provider_ids = {
            "llm": self._provider_combo.currentData() or "demo",
            "image": self._image_provider_combo.currentData() or "demo",
            "video": self._video_provider_combo.currentData() or "demo",
            "voice": self._voice_provider_combo.currentData() or "demo",
        }
        models = {kind: self._ctx.provider_model(kind, pid)
                  for kind, pid in provider_ids.items()}

        def job(tctx) -> str:
            from ai_video_factory.services.standard_pipeline import (
                build_standard_pipeline, make_context,
            )

            pipeline = build_standard_pipeline(
                self._ctx.project_manager, bus=self._ctx.bus,
                provider_ids=provider_ids, models=models,
                asset_repo=self._ctx.asset_repo,
            )

            def forward(event: Event) -> None:
                percent = min(float(event.payload.get("percent", 0.0)) / 100.0, 1.0)
                tctx.report_progress(percent, event.payload.get("stage", ""))

            unsubscribe = self._ctx.bus.subscribe(forward, event_name="pipeline.progress")
            try:
                tctx.report_stage("Running the full pipeline…")
                result = pipeline.run(make_context(project, self._ctx.project_manager))
            finally:
                unsubscribe()
            if not result.success:
                failed = [r.name for r in result.stage_results if r.outcome == "failed"]
                raise RuntimeError(f"pipeline failed at: {failed or result.error}")
            return f"final video ready ({len(result.completed_stages)} stages)"

        task = self._ctx.task_manager.submit(
            f"everything: {project.name}", job,
            max_retries=self._ctx.settings_service.settings.retry_max_attempts - 1,
            metadata={"project_id": project_id, "kind": "pipeline"},
        )
        self._generating_task_id = task.id
        self._update_enabled()

    # -------------------------------------------------------------------- SEO
    def _open_seo(self) -> None:
        """Cached SEO → edit now; otherwise generate in the background first."""
        project = self._project
        if project is None:
            QMessageBox.information(self, "No project", "Create or open a project first.")
            return
        from ai_video_factory.services.seo_service import load_seo

        if load_seo(project, self._ctx.project_manager) is not None:
            self._show_seo_dialog()
            return
        project_id = project.id
        provider_id = self._provider_combo.currentData() or "demo"
        model_override = self._ctx.provider_model("llm", provider_id)

        def job(tctx) -> str:
            from ai_video_factory.services.seo_service import generate_seo

            tctx.report_stage("Generating SEO metadata…")
            result = generate_seo(project, self._ctx.project_manager,
                                  provider_id=provider_id, model=model_override)
            if not result.ok:
                raise RuntimeError(f"SEO failed: {result.error}")
            self._ctx.bus.publish("seo.generated", project_id=project_id,
                                  title=result.package.title,
                                  used_fallback=result.used_fallback)
            return f"seo: {result.package.title}"

        task = self._ctx.task_manager.submit(
            f"seo: {project.name}", job,
            max_retries=self._ctx.settings_service.settings.retry_max_attempts - 1,
            metadata={"project_id": project_id, "kind": "seo"},
        )
        self._generating_task_id = task.id
        self._update_enabled()

    def _show_seo_dialog(self) -> None:
        from PySide6.QtWidgets import QDialog

        from ai_video_factory.ui.seo_dialog import SeoDialog

        project = self._project
        if project is None or project.seo is None:
            return
        dialog = SeoDialog(project.seo, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.saved_package is not None:
            from ai_video_factory.services.seo_service import save_seo

            save_seo(project, self._ctx.project_manager, dialog.saved_package)
            self._refresh_ui()

    # -------------------------------------------------------------- thumbnail
    def _open_thumbnail(self) -> None:
        """Preview + edit the smart thumbnail recipe, regenerate on Save."""
        project = self._project
        if project is None:
            QMessageBox.information(self, "No project", "Create or open a project first.")
            return
        from PySide6.QtWidgets import QDialog

        from ai_video_factory.services.thumbnail_service import (
            _default_meta, load_thumbnail_meta,
        )
        from ai_video_factory.ui.thumbnail_dialog import ThumbnailDialog

        meta = load_thumbnail_meta(project, self._ctx.project_manager) or _default_meta(project)
        thumb_path = self._ctx.project_manager.project_dir(project) / "output" / "thumbnail.png"
        dialog = ThumbnailDialog(meta, thumb_path, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.saved_meta is None:
            return
        custom = dialog.saved_meta
        project_id = project.id

        def job(tctx) -> str:
            from ai_video_factory.services.thumbnail_service import generate_smart_thumbnail

            tctx.report_stage("Rendering smart thumbnail…")
            result = generate_smart_thumbnail(
                project, self._ctx.project_manager,
                title=custom["title"], subtitle=custom["subtitle"], badge=custom["badge"],
                force=True,
            )
            if not result.ok:
                raise RuntimeError(f"thumbnail failed: {result.error}")
            self._ctx.bus.publish("thumbnail.generated", project_id=project_id,
                                  path=str(result.path),
                                  background=result.background_source)
            return f"thumbnail: {result.background_source}"

        task = self._ctx.task_manager.submit(
            f"thumbnail: {project.name}", job,
            max_retries=0,
            metadata={"project_id": project_id, "kind": "thumbnail"},
        )
        self._generating_task_id = task.id
        self._update_enabled()

    def _on_thumbnail_generated(self, event: Event) -> None:
        project = self._project
        if project is None or event.payload.get("project_id") != project.id:
            return
        self._refresh_ui()
        self.scenesChanged.emit()

    def _on_seo_generated(self, event: Event) -> None:
        project = self._project
        if project is None or event.payload.get("project_id") != project.id:
            return
        self._refresh_ui()
        self._show_seo_dialog()          # generated → let the user edit it now

    def _on_render_completed(self, event: Event) -> None:
        project = self._project
        if project is None or event.payload.get("project_id") != project.id:
            return
        self._refresh_ui()
        self.scenesChanged.emit()

    def _on_subtitles_generated(self, event: Event) -> None:
        project = self._project
        if project is None or event.payload.get("project_id") != project.id:
            return
        self._refresh_ui()
        self.scenesChanged.emit()

    def _on_audio_mixed(self, event: Event) -> None:
        project = self._project
        if project is None or event.payload.get("project_id") != project.id:
            return
        self._refresh_ui()
        self.scenesChanged.emit()

    def _on_voices_generated(self, event: Event) -> None:
        project = self._project
        if project is None or event.payload.get("project_id") != project.id:
            return
        self._refresh_ui()
        self.scenesChanged.emit()

    def _on_task_terminal(self, event: Event) -> None:
        if event.payload.get("task_id") == self._generating_task_id:
            self._generating_task_id = None
            self._update_enabled()

    # ------------------------------------------------------------------ saving
    def _save_project(self) -> None:
        if self._project is None:
            return
        self._project.idea = self._idea_edit.toPlainText().strip()
        path = self._save(autosave=False)
        QMessageBox.information(self, "Saved", f"Project saved to:\n{path}")

    def _save(self, *, autosave: bool) -> object:
        manager: ProjectManager = self._ctx.project_manager
        try:
            return manager.save(self._project, autosave=autosave)  # type: ignore[arg-type]
        except AVFError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return ""
