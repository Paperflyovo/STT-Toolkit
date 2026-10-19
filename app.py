from __future__ import annotations

import argparse
import logging
import multiprocessing
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path


def main():
    from waitress import create_server
    from stt.engine import JobManager
    from stt.web import create_app

    parser = argparse.ArgumentParser(description="STT Tools — local audio and video transcription")
    parser.add_argument("--port", type=int, default=0, help="Local port; 0 selects an available port")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    assets = Path(getattr(sys, "_MEIPASS", root)) / "web"
    data = root / "data"
    data.mkdir(exist_ok=True)
    (data / "temporary").mkdir(exist_ok=True)
    (root / "models").mkdir(exist_ok=True)
    tempfile.tempdir = str(data / "temporary")
    logging.basicConfig(filename=data / "stt.log", encoding="utf-8", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    manager = JobManager(root)
    shutdown = threading.Event()
    app = create_app(root, assets, manager, shutdown)
    server = create_server(app, host="127.0.0.1", port=args.port, threads=4, max_request_body_size=4 * 1024 * 1024 * 1024, channel_timeout=3600)
    url = f"http://127.0.0.1:{server.effective_port}"
    logging.info("Listening at %s", url)
    if sys.stdout:
        print(f"STT Tools: {url}", flush=True)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    if not args.no_browser:
        webbrowser.open(url)
    try:
        while not shutdown.wait(0.5):
            if not server_thread.is_alive():
                break
    except KeyboardInterrupt:
        pass
    finally:
        manager.close()
        server.close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        main()
    except Exception as error:
        if getattr(sys, "frozen", False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"STT Tools 无法启动：\n{error}\n\n请将完整文件夹放到可写目录后重试。", "STT Tools", 16)
        raise
