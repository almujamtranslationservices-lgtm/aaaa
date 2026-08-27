"""UI package (PySide6) — delivered in PHASE 3.

Pages: dashboard (new/open/recent), project (idea → Generate Script),
scene editor, AI providers, settings, logs — wired to the core layers
through the thread-safe Qt event bridge. The GUI never blocks: all heavy
work runs in the TaskManager's worker pool.
"""
