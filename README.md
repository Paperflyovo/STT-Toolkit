# STT-Toolkit

一个 Windows 优先、完全本地运行的音视频转文字工具。界面在浏览器中打开，识别使用 `faster-whisper` CPU INT8；首次选择模型需要联网下载，模型会保存到 `models/`，之后可断网使用。

## 运行源码

```powershell
.\.venv\Scripts\python.exe app.py
```

没有虚拟环境时，使用 Python 3.12 创建后安装：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

## 便携构建

```powershell
.\.venv\Scripts\python.exe scripts\build_portable.py
```

生成目录为 `dist\STT-Tools\`。将整个目录复制到 U 盘或其他 Windows 电脑，双击 `STT-Tools.exe` 即可。`models\` 应放在 exe 同级目录；默认不把模型打进程序包，便于更换模型和控制体积。

构建先输出到 `build/staged/`，再更新 exe 和 `_internal/`，保留便携目录中已经下载的 `models/` 和用户数据。更新前请从页面右上角退出旧程序。模型首次使用时下载，下载完成后可勾选“仅离线”。GitHub 仓库仅包含源码，模型、便携构建、录音、转写文稿和测试临时文件不会上传。

## 模型与格式

中文转写默认输出简体中文：自动识别为中文或手动指定中文时，使用 OpenCC 在返回每一段文字前转换繁体字。界面、复制和 Markdown 导出使用同一份简体文稿；其他语言不做繁简转换。OpenCC 字典随便携包提供，不需要联网。

可选 `tiny`、`base`、`small`，中文通常从 `small` 开始尝试。支持常见音频和视频容器，单文件上限 4 GB，单次最长 4 小时。识别结果可直接编辑、复制或导出 UTF-8 Markdown。

处理流程：浏览器分块传送到本机服务 → PyAV 提取 16 kHz 单声道 WAV → faster-whisper 识别音频 → 文字输出。模型缺失时会先下载模型。识别完成后清理任务临时媒体；界面资源使用本地文件与系统字体。

默认将完整音轨交给 Whisper，不启用会提前丢弃音频的 Silero VAD 过滤。歌声、伴奏中的人声和轻声可能被面向说话场景的 VAD 误判为非语音，导致漏掉大段内容。此设置也适用于视频；代价是长静音录音可能处理得更慢，纯伴奏中的误识别仍需校对。

## “连接已失效”修复

2026-09-07：浏览器实际复现显示，旧页面通过内联 JavaScript 设置 Token，却被自身 `script-src 'self'` 策略阻止，上传因此携带无效 Token 并返回 403。这一错误与文件大小无关。现在从 HTML meta 元素读取 Token，继续保留 CSP、Token 与同源校验。

已使用完整 MP4 视频和 FLAC 歌曲验证导入、简体输出、复制及 Markdown 导出。首次使用其他模型仍需网络，识别准确率取决于模型和录音质量，自动转写结果应校对。

## 许可证提示

本项目代码未附加第三方代码。主要运行依赖及模型有各自的许可证；分发时应保留依赖许可材料并单独核对模型条款。
