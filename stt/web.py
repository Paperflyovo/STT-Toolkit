from __future__ import annotations

import secrets
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from stt.engine import EXTENSIONS, LANGUAGES, MODELS, model_ready


MAX_UPLOAD = 4 * 1024 * 1024 * 1024


def create_app(root: Path, assets: Path, manager, shutdown):
    app = Flask(__name__, static_folder=str(assets), static_url_path="/static", template_folder=str(assets))
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD
    token = secrets.token_urlsafe(32)
    app.config["STT_TOKEN"] = token
    upload_dir = root / "data" / "temporary"
    upload_dir.mkdir(parents=True, exist_ok=True)

    @app.before_request
    def protect_local_app():
        if request.host.split(":")[0] not in {"127.0.0.1", "localhost"}:
            abort(403)
        if request.path.startswith("/api/"):
            if not secrets.compare_digest(request.headers.get("X-STT-Token", ""), token):
                abort(403)
            origin = request.headers.get("Origin")
            if origin and origin != request.host_url.rstrip("/"):
                abort(403)

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        messages = {400: "请求无效，请重新选择文件。", 403: "连接已失效，请刷新页面。", 404: "内容不存在。", 413: "文件超过 4 GB，请分段后导入。"}
        return jsonify(error=messages.get(error.code, error.description)), error.code

    @app.get("/")
    def index():
        return render_template("index.html", token=token)

    @app.get("/api/state")
    def state():
        return jsonify(job=manager.snapshot(), models={name: {**details, "ready": model_ready(root / "models" / name)} for name, details in MODELS.items()})

    @app.post("/api/transcribe")
    def transcribe():
        filename = request.args.get("filename", "").replace("\\", "/").rsplit("/", 1)[-1]
        upload_id = request.args.get("upload_id", "")
        model = request.args.get("model", "base")
        language = request.args.get("language", "auto")
        offline = request.args.get("offline", "false") == "true"
        if not filename or len(filename) > 250 or Path(filename).suffix.lower() not in EXTENSIONS:
            return jsonify(error="不支持此文件类型，请选择常见音频或视频文件。"), 400
        if model not in MODELS or language not in LANGUAGES:
            return jsonify(error="模型或语言选项无效，请刷新后重试。"), 400
        if offline and not model_ready(root / "models" / model):
            return jsonify(error="所选模型尚未下载。请关闭“仅离线”完成首次下载，或将模型放入 models 对应目录。"), 400
        try:
            manager.reserve()
        except ValueError as error:
            return jsonify(error=str(error)), 409
        source = upload_dir / f"{upload_id}.upload" if upload_id else None
        try:
            if not source or not source.is_file() or source.stat().st_size == 0:
                return jsonify(error="上传文件不存在或为空，请重新选择。"), 400
            job_id = manager.start(source, filename, model, language, offline)
            source = None
            return jsonify(id=job_id), 202
        except HTTPException:
            raise
        except OSError:
            app.logger.exception("Unable to save media")
            return jsonify(error="无法写入临时文件，请检查剩余空间及文件夹写入权限。"), 500
        finally:
            manager.release()
            if source:
                source.unlink(missing_ok=True)

    @app.post("/api/upload")
    def upload_chunk():
        filename = request.args.get("filename", "").replace("\\", "/").rsplit("/", 1)[-1]
        upload_id = request.args.get("upload_id") or uuid.uuid4().hex
        chunk = request.stream.read(1 * 1024 * 1024)
        target = upload_dir / f"{upload_id}.upload"
        if not filename or Path(filename).suffix.lower() not in EXTENSIONS:
            return jsonify(error="不支持此文件类型。"), 400
        if target.exists() and target.stat().st_size + len(chunk) > MAX_UPLOAD:
            target.unlink(missing_ok=True)
            return jsonify(error="文件超过 4 GB。"), 413
        try:
            with target.open("ab") as stream:
                stream.write(chunk)
        except OSError:
            app.logger.exception("Unable to append upload chunk")
            return jsonify(error="无法写入上传文件，请检查磁盘空间和文件夹权限。"), 507
        return jsonify(upload_id=upload_id, bytes=target.stat().st_size)

    @app.post("/api/cancel")
    def cancel():
        manager.cancel()
        return jsonify(ok=True)

    @app.post("/api/shutdown")
    def quit_app():
        shutdown.set()
        return jsonify(ok=True)

    return app
