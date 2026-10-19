from __future__ import annotations

import copy
import logging
import multiprocessing
import os
import queue
import threading
import time
import uuid
import wave
from pathlib import Path


MODELS = {
    "tiny": {"label": "轻巧", "size": "约 75 MB"},
    "base": {"label": "日常", "size": "约 145 MB"},
    "small": {"label": "更准确", "size": "约 485 MB"},
}
LANGUAGES = {"auto", "zh", "en", "ja", "ko", "fr", "de", "es"}
EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".wma", ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
ACTIVE = {"starting", "loading", "downloading", "transcribing", "cancelling"}


def model_ready(folder: Path) -> bool:
    return all((folder / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json")) and any(folder.glob("vocabulary.*"))


def simplify_chinese(text, converter):
    while True:
        converted = converter.convert(text)
        if converted == text:
            return text
        text = converted


def extract_audio(source: Path, destination: Path):
    import av

    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=16000)
    with av.open(str(source)) as container, wave.open(str(destination), "wb") as output:
        if not container.streams.audio:
            raise ValueError("这个文件没有音轨，请选择包含人声的音频或视频。")
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                output.writeframes(converted.to_ndarray().tobytes())
        for converted in resampler.resample(None):
            output.writeframes(converted.to_ndarray().tobytes())


def transcribe_worker(events, source: str, model_dir: str, model_name: str, language: str, offline: bool):
    try:
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["HF_HUB_DISABLE_XET"] = "1"
        import av
        from faster_whisper import WhisperModel
        from faster_whisper.utils import download_model
        from opencc import OpenCC

        source_path = Path(source)
        audio_path = source_path.with_suffix(".wav")
        with av.open(source) as container:
            if not container.streams.audio:
                raise ValueError("这个文件没有音轨，请选择包含人声的音频或视频。")
            if container.duration and container.duration / av.time_base > 4 * 3600:
                raise ValueError("文件超过 4 小时，请分成较短片段后再导入。")
        destination = Path(model_dir) / model_name
        if not model_ready(destination):
            if offline:
                raise ValueError("离线模式下未找到完整模型。请关闭“仅离线”下载一次，或复制完整模型到 models 对应目录。")
            events.put({"status": "downloading", "message": f"首次准备模型（{MODELS[model_name]['size']}），需要网络；之后可离线使用。"})
            download_model(model_name, output_dir=str(destination))
        events.put({"status": "extracting", "message": "正在从视频中分离音频…"})
        extract_audio(source_path, audio_path)
        events.put({"status": "loading", "message": "正在加载模型与音轨…"})
        model = WhisperModel(str(destination), device="cpu", compute_type="int8", cpu_threads=min(8, max(1, (os.cpu_count() or 2) - 1)), local_files_only=True)
        segments, info = model.transcribe(str(audio_path), language=None if language == "auto" else language, beam_size=5, vad_filter=False, condition_on_previous_text=False)
        converter = OpenCC("t2s") if info.language == "zh" else None
        events.put({"status": "transcribing", "message": "正在将声音转为文字…", "duration": info.duration, "language": info.language})
        for segment in segments:
            text = segment.text.strip()
            if converter:
                text = simplify_chinese(text, converter)
            events.put({"segment": {"start": round(segment.start, 2), "end": round(segment.end, 2), "text": text}, "progress": min(99, round(segment.end / max(info.duration, 0.01) * 100))})
        events.put({"status": "completed", "message": "转写完成，可以编辑、复制或导出。", "progress": 100})
    except Exception as error:
        logging.exception("Transcription failed")
        message = str(error)
        if isinstance(error, (ImportError, OSError)):
            message = "引擎或文件无法加载。请检查文件是否有效、便携目录是否完整。详情：" + message
        elif any(word in message.lower() for word in ("connection", "timeout", "connect", "huggingface", "http")):
            message = "模型下载未完成，请检查网络后重试；也可以手动放入模型。详情：" + message
        events.put({"status": "failed", "message": message[:700]})
    finally:
        Path(source).unlink(missing_ok=True)
        Path(source).with_suffix(".wav").unlink(missing_ok=True)


class JobManager:
    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.RLock()
        self.context = multiprocessing.get_context("spawn")
        self.process = None
        self.monitor = None
        self.job = None
        self.reserved = False

    def reserve(self):
        with self.lock:
            if self.reserved or self.process is not None:
                raise ValueError("已有文件正在处理，请先等待完成或停止当前转写。")
            self.reserved = True

    def release(self):
        with self.lock:
            self.reserved = False

    def start(self, source: Path, filename: str, model: str, language: str, offline: bool):
        with self.lock:
            events = self.context.Queue()
            self.job = {"id": uuid.uuid4().hex, "filename": filename, "model": model, "status": "starting", "message": "正在准备识别引擎…", "progress": 0, "duration": 0, "language": language, "segments": [], "started": time.time(), "elapsed": 0}
            process = self.context.Process(target=transcribe_worker, args=(events, str(source), str(self.root / "models"), model, language, offline), daemon=True)
            try:
                process.start()
            except Exception:
                events.close()
                self.job.update(status="failed", message="无法启动识别进程。")
                raise
            self.process = process
            self.reserved = False
            self.monitor = threading.Thread(target=self._watch, args=(process, events, source), daemon=True)
            self.monitor.start()
            return self.job["id"]

    def _watch(self, process, events, source: Path):
        final_event = None
        try:
            while True:
                try:
                    event = events.get(timeout=0.2)
                except queue.Empty:
                    if not process.is_alive():
                        break
                    continue
                if event.get("status") in {"completed", "failed"}:
                    final_event = event
                    continue
                with self.lock:
                    if self.job["status"] == "cancelling":
                        continue
                    segment = event.pop("segment", None)
                    if segment and segment["text"]:
                        self.job["segments"].append(segment)
                    self.job.update(event)
            process.join(timeout=2)
        finally:
            source.unlink(missing_ok=True)
            events.close()
            with self.lock:
                if self.job["status"] == "cancelling":
                    self.job.update(status="cancelled", message="已停止转写，已识别的文字仍可导出。")
                elif final_event:
                    self.job.update(final_event)
                    if self.job["status"] == "completed" and not self.job["segments"]:
                        self.job["message"] = "未检测到清晰人声。可以检查音轨，或指定语言后重试。"
                else:
                    self.job.update(status="failed", message=f"识别进程意外退出（{process.exitcode}）。请尝试较小模型或较短文件。")
                self.job["elapsed"] = round(time.time() - self.job["started"])
                self.process = None

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.job)
            if result and self.process is not None:
                result["elapsed"] = round(time.time() - result["started"])
            return result

    def cancel(self):
        with self.lock:
            if self.process is not None:
                self.job.update(status="cancelling", message="正在停止并释放资源…")
                if self.process.is_alive():
                    self.process.terminate()

    def close(self):
        self.cancel()
        if self.monitor:
            self.monitor.join(timeout=5)
