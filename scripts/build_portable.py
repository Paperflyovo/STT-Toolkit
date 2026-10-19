from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--name", "STT-Tools", "--distpath", "build/staged", "--add-data", "web;web", "--collect-data", "faster_whisper", "--collect-data", "opencc", "app.py"]
    subprocess.run(command, cwd=ROOT, check=True)
    staged = ROOT / "build" / "staged" / "STT-Tools"
    output = ROOT / "dist" / "STT-Tools"
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staged / "STT-Tools.exe", output / "STT-Tools.exe")
    shutil.copytree(staged / "_internal", output / "_internal", dirs_exist_ok=True)
    (output / "models").mkdir(exist_ok=True)
    (output / "data" / "temporary").mkdir(parents=True, exist_ok=True)
    print(f"Portable build ready: {output}")


if __name__ == "__main__":
    main()
