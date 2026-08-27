"""Command-line interface for AI Video Factory.

Currently available commands (PHASE 1):

* ``doctor``   — inspect the environment (Python, FFmpeg, GPU, dependencies).
* ``selftest`` — verify that all core modules import correctly.
* ``gui``      — launch the desktop GUI (honest placeholder until PHASE 3).
* ``version``  — print the application version.
"""

from __future__ import annotations

import importlib.util
import platform
import shutil
import sys
from typing import Any

from ai_video_factory import APP_NAME, __version__
from ai_video_factory.config.providers import ProviderKind, providers_for
from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine

_OK = "[OK]  "
_FAIL = "[FAIL]"
_WARN = "[WARN]"
_TODO = "[TODO]"


def _check_module(name: str) -> tuple[bool, str | None]:
    """Return (installed, version) for an optional dependency."""
    spec = importlib.util.find_spec(name)
    if spec is None:
        return False, None
    try:
        module = importlib.import_module(name)
        version = getattr(module, "__version__", None) or getattr(module, "VERSION", "?")
        return True, str(version)
    except Exception:  # pragma: no cover - defensive
        return True, "?"


def _section(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(1, 60 - len(title)))


def cmd_doctor() -> int:
    """Print a full environment report and return 0 (always informational)."""
    print(f"{APP_NAME} v{__version__} — environment doctor")

    _section("Python")
    print(f"{_OK}Python       : {platform.python_version()} ({sys.executable})")
    if sys.version_info < (3, 11):
        print(f"{_FAIL}Python >= 3.11 required")
    elif sys.version_info < (3, 12):
        print(f"{_WARN}Python 3.12+ recommended (running 3.11 — supported)")

    _section("System")
    print(f"{_OK}OS           : {platform.system()} {platform.release()}")
    print(f"{_OK}Machine      : {platform.machine()}")
    gpu = shutil.which("nvidia-smi")
    print(f"{_OK}GPU          : {'nvidia-smi found' if gpu else 'not detected (CPU-only; cloud/local-CPU providers still work)'}")

    _section("FFmpeg")
    engine = FFmpegEngine()
    if engine.available:
        print(f"{_OK}ffmpeg       : {engine.ffmpeg_path}")
        print(f"{_OK}version      : {engine.version()}")
        if engine._ffprobe:
            print(f"{_OK}ffprobe      : {engine._ffprobe}")
        elif engine.probe_available:
            print(f"{_OK}ffprobe      : via PyAV fallback (av package — no binary needed)")
        else:
            print(f"{_WARN}ffprobe      : not found (pip install av for metadata probing)")
    else:
        print(f"{_FAIL}ffmpeg       : not found — install FFmpeg or `pip install imageio-ffmpeg`")

    _section("Python dependencies")
    for dep, purpose in [
        ("pydantic", "data models & validation"),
        ("dotenv", "python-dotenv — .env management"),
        ("httpx", "async HTTP client for providers"),
        ("PIL", "Pillow — image processing"),
        ("PySide6", "GUI (PHASE 3)"),
        ("cv2", "OpenCV — media processing (PHASE 10+)"),
        ("edge_tts", "free TTS voice provider (PHASE 9)"),
        ("moviepy", "optional video helper"),
    ]:
        installed, version = _check_module(dep)
        marker = _OK if installed else (_TODO if dep in {"PySide6", "cv2", "edge_tts", "moviepy"} else _FAIL)
        print(f"{marker}{dep:<12}: {'v' + version if installed else 'not installed'} — {purpose}")

    _section("AI providers (registry)")
    for kind in ProviderKind:
        print(f"  {kind.value.upper()}:")
        for info in providers_for(kind):
            state = "implemented" if info.implemented else f"planned (PHASE {info.phase})"
            print(f"    - {info.id:<12} [{info.tier.value:<5}] {state:<20} {info.name}")

    _section("Conclusion")
    gui_ready = importlib.util.find_spec("PySide6") is not None
    print(f"Core architecture: OPERATIONAL (PHASE 1-15 complete — render + SEO + smart thumbnail live).")
    print(f"GUI: {'READY — run `python app.py gui`' if gui_ready else 'install PySide6 to enable'}")
    print("Live: script + prompts + images + videos + voice + mixes + SUBTITLES per scene")
    print("      (auto-ducked music, fades, SFX — all cached & isolated).")
    print("Final video: Generate Everything in the UI → output/final.mp4")
    return 0


def cmd_selftest() -> int:
    """Import every core module to catch broken wiring early."""
    modules = [
        "ai_video_factory.config.settings",
        "ai_video_factory.config.providers",
        "ai_video_factory.core.event_bus",
        "ai_video_factory.core.logger",
        "ai_video_factory.core.task_manager",
        "ai_video_factory.core.pipeline",
        "ai_video_factory.core.project_manager",
        "ai_video_factory.models.project",
        "ai_video_factory.models.scene",
        "ai_video_factory.models.character",
        "ai_video_factory.models.prompt",
        "ai_video_factory.models.audio",
        "ai_video_factory.models.video",
        "ai_video_factory.utils.file_utils",
        "ai_video_factory.utils.ffmpeg_utils",
        "ai_video_factory.utils.time_utils",
        "ai_video_factory.utils.validation",
        "ai_video_factory.prompts.script_prompt",
        "ai_video_factory.prompts.image_prompt",
        "ai_video_factory.prompts.video_prompt",
        "ai_video_factory.prompts.seo_prompt",
        "ai_video_factory.prompts.scene_prompt",
        "ai_video_factory.database.database",
        "ai_video_factory.database.repositories",
        "ai_video_factory.services.script_service",
        "ai_video_factory.ai.factory",
        "ai_video_factory.ai.llm.demo",
        "ai_video_factory.app",
    ]
    if importlib.util.find_spec("PySide6") is not None:
        modules += [
            "ai_video_factory.ui.main_window",
            "ai_video_factory.ui.dashboard",
            "ai_video_factory.ui.project_view",
            "ai_video_factory.ui.scene_editor",
            "ai_video_factory.ui.settings_view",
            "ai_video_factory.ui.provider_view",
            "ai_video_factory.ui.logs_view",
        ]
    failures: list[str] = []
    for mod in modules:
        try:
            __import__(mod)
            print(f"{_OK}{mod}")
        except Exception as exc:  # pragma: no cover
            failures.append(mod)
            print(f"{_FAIL}{mod}: {exc}")
    if failures:
        print(f"\n{len(failures)} module(s) failed to import.")
        return 1
    print(f"\nAll {len(modules)} core modules imported successfully.")
    return 0


def cmd_gui() -> int:
    """Launch the PySide6 desktop GUI (PHASE 3)."""
    from ai_video_factory.app import launch_gui

    return launch_gui()


def main(argv: list[str] | None = None) -> int:
    """CLI dispatcher."""
    import argparse

    parser = argparse.ArgumentParser(prog="ai_video_factory", description=f"{APP_NAME} v{__version__}")
    parser.add_argument("command", nargs="?", default="doctor",
                        choices=["doctor", "selftest", "gui", "version"],
                        help="doctor: environment check | selftest: import check | gui: launch UI | version")
    args = parser.parse_args(argv)

    commands: dict[str, Any] = {
        "doctor": cmd_doctor,
        "selftest": cmd_selftest,
        "gui": cmd_gui,
        "version": lambda: (print(f"{APP_NAME} v{__version__}"), 0)[1],
    }
    return commands[args.command]()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
