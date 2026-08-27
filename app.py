#!/usr/bin/env python3
"""AI Video Factory — desktop application entry point.

Run with:
    python app.py                # same as: python app.py doctor
    python app.py doctor         # environment diagnostics
    python app.py selftest       # quick sanity check of core modules
    python app.py gui            # launch the GUI (PHASE 3 — not yet available)

Or as a module:
    python -m ai_video_factory <command>
"""

from ai_video_factory.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
