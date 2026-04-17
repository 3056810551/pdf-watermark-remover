from __future__ import annotations

from pathlib import Path
import sys


def main() -> None:
    try:
        from PyInstaller.__main__ import run as pyinstaller_run
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise SystemExit(
            "未安装 PyInstaller，请先执行: pip install -r requirements-build.txt"
        ) from exc

    root = Path(__file__).resolve().parent
    app_entry = root / "app.py"
    app_name = "PDFWatermarkRemover"

    pyinstaller_run(
        [
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            f"--name={app_name}",
            "--collect-all=fitz",
            "--collect-all=PIL",
            str(app_entry),
        ]
    )

    exe_name = f"{app_name}.exe" if sys.platform.startswith("win") else app_name
    output_path = root / "dist" / exe_name
    print(f"Build complete: {output_path}")


if __name__ == "__main__":
    main()
