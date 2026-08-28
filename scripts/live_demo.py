#!/usr/bin/env python3
"""Live preview launcher — runs the REAL GUI offscreen and streams it to the
browser (auto-refreshing screenshot), then triggers a real end-to-end
"Generate Everything" run so the viewer watches the whole pipeline live.

    python scripts/live_demo.py [port]
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import queue

from PySide6.QtCore import QEvent, QPoint, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from ai_video_factory.app import AppContext
from ai_video_factory.models.project import Project, ResolutionPreset, VideoType
from ai_video_factory.models.scene import Scene
from ai_video_factory.ui.main_window import MainWindow

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

# ------------------------------------------------------------------ shared state
class State:
    png: bytes = b""
    status: str = "starting…"
    started_at = time.time()


STATE = State()
CLICKS: queue.Queue = queue.Queue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):          # keep the console clean
        pass

    def _send(self, content_type: str, body: bytes, cache: str = "no-store"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/click"):
            from urllib.parse import parse_qs, urlparse
            params = parse_qs(urlparse(self.path).query)
            try:
                CLICKS.put((int(params["x"][0]), int(params["y"][0])))
                self.send_response(204); self.end_headers()
            except Exception:
                self.send_error(400)
            return
        if self.path == "/" or self.path.startswith("/index"):
            self._send("text/html; charset=utf-8", PAGE.encode("utf-8"))
        elif self.path == "/live.png":
            self._send("image/png", STATE.png or b"")
        elif self.path == "/status.json":
            self._send("application/json", json.dumps(
                {"status": STATE.status, "uptime_s": round(time.time() - STATE.started_at)},
                ensure_ascii=False).encode("utf-8"))
        else:
            self.send_error(404)


PAGE = """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>AI Video Factory — عرض حي</title>
<style>
 body{background:#0e1016;color:#e8e8f0;font-family:system-ui,'Segoe UI',Tahoma,sans-serif;
      margin:0;display:flex;flex-direction:column;align-items:center;min-height:100vh}
 h1{font-size:1.05rem;margin:14px 0 4px}
 #status{font-size:.85rem;color:#8fd19e;margin-bottom:10px;direction:rtl}
 img{max-width:100%;border-radius:10px;box-shadow:0 8px 40px rgba(0,0,0,.55);cursor:crosshair;user-select:none}
 footer{font-size:.75rem;color:#777;margin:12px 0}
</style></head><body>
<h1>🎬 AI Video Factory v0.1.0 — يعمل الآن مباشرة</h1>
<div id="status">…</div>
<img id="shot" src="/live.png" alt="live screenshot">
<footer>بث حي للواجهة الفعلية (offscreen Qt) — التحديث كل ثانية · العرض عبر Arena</footer>
<script>
const shot = document.getElementById('shot'), status = document.getElementById('status');
async function tick(){
  shot.src = '/live.png?r=' + Date.now();
  try { const s = await (await fetch('/status.json?r='+Date.now())).json();
        status.textContent = 'الحالة: ' + s.status + ' · منذ ' + s.uptime_s + ' ثانية'; } catch(e){}
}
shot.addEventListener('click', async e => {
  const r = shot.getBoundingClientRect();
  const x = Math.round((e.clientX - r.left) * shot.naturalWidth / r.width);
  const y = Math.round((e.clientY - r.top) * shot.naturalHeight / r.height);
  await fetch('/click?x='+x+'&y='+y);
  setTimeout(()=>{ shot.src = '/live.png?r=' + Date.now(); }, 200);
});
setInterval(tick, 1000); tick();
</script></body></html>"""


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    ctx = AppContext()
    window = MainWindow(ctx)
    window.resize(1400, 900)
    window.show()

    # ------------------------------------------------ capture loop (UI thread)
    import tempfile

    shot_file = Path(tempfile.gettempdir()) / "avf_live_shot.png"

    def capture() -> None:
        try:
            pixmap = window.grab()
            pixmap.save(str(shot_file), "PNG")
            STATE.png = shot_file.read_bytes()
            project = window._project
            if project is not None:
                STATE.status = f"{project.name} — {project.status.value}"
        except Exception:  # noqa: BLE001 — never kill the event loop
            import traceback
            traceback.print_exc()

    # --------------------------------------------------------- the demo project
    def start_demo() -> None:
        try:
            manager = ctx.project_manager
            project = Project(
                name="عرض حي — الصحراء البيضاء",
                idea="رحلة قصيرة عبر الصحراء البيضاء في الفيوم عند الفجر",
                video_type=VideoType.YOUTUBE_VIDEO,
                resolution=ResolutionPreset.P480, fps=12, target_duration=12,
            )
            project_dir = Path(manager._root) / "live-demo"
            (project_dir / "scenes").mkdir(parents=True, exist_ok=True)
            project.file_path = project_dir / "project.json"
            scenes = []
            for i in (1, 2, 3, 4):
                scene = Scene(scene_id=i, duration=3.0,
                              narration=f"تعليق المشهد رقم {i} عن الصحراء البيضاء",
                              visual=f"لقطة سينمائية رقم {i} للكثبان عند الفجر")
                if i == 1:
                    scene.sfx = "wind"
                scenes.append(scene)
            project.scenes = scenes
            manager.save(project)
            window._set_current_project(project)
            window.switch_page("project")
            STATE.status = "المشروع جاهز — تشغيل Generate Everything…"
            window.project_page._generate_everything()
        except Exception as exc:  # noqa: BLE001 — surface in the stream
            STATE.status = f"تعذر بدء العرض: {exc}"

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"live preview on :{PORT}", flush=True)

    QTimer.singleShot(1500, capture)
    QTimer.singleShot(2500, start_demo)
    def dispatch_clicks() -> None:
        """Turn browser clicks into REAL Qt mouse events on the window."""
        from PySide6.QtCore import Qt
        while True:
            try:
                x, y = CLICKS.get_nowait()
            except queue.Empty:
                return
            global_pos = window.mapToGlobal(QPoint(x, y))
            widget = QApplication.widgetAt(global_pos)
            if widget is None:
                STATE.status += " · (نقرة خارج النافذة)"
                continue
            local = widget.mapFromGlobal(global_pos)
            for event_type in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
                QApplication.postEvent(widget, QMouseEvent(
                    event_type, local, global_pos,
                    Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier))
            STATE.status += f" · نقرة على {widget.metaObject().className()}"

    clicker = QTimer()
    clicker.timeout.connect(dispatch_clicks)
    clicker.start(60)

    shooter = QTimer()
    shooter.timeout.connect(capture)
    shooter.start(500)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
