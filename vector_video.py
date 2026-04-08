#!/usr/bin/env python3
"""Tools for converting between SVG sequences, MP4 and VSV archives."""

from __future__ import annotations

import argparse
import glob
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from fractions import Fraction
from pathlib import Path
from typing import Callable, Sequence


VSV_VERSION = 1


def _normalize_argv(argv: Sequence[str]) -> list[str]:
    """Backward compatibility: old usage had no subcommand and started with --input."""
    if not argv:
        return ["svg-to-mp4"]
    if argv[0].startswith("-"):
        return ["svg-to-mp4", *argv]
    return list(argv)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    argv = _normalize_argv(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(description="vector-smooth-video tooling")
    sub = parser.add_subparsers(dest="command", required=True)

    svg_parser = sub.add_parser("svg-to-mp4", help="Render SVG file(s) to MP4")
    svg_parser.add_argument("--input", required=True, help="SVG file, directory, or glob pattern")
    svg_parser.add_argument("--output", required=True, help="Target video path (e.g. output.mp4)")
    svg_parser.add_argument("--fps", type=int, default=60, help="Frames per second (default: 60)")
    svg_parser.add_argument("--duration", type=float, default=3.0, help="Duration for single SVG")
    svg_parser.add_argument("--width", type=int, default=1920)
    svg_parser.add_argument("--height", type=int, default=1080)
    svg_parser.add_argument("--supersample", type=int, default=2)
    svg_parser.add_argument(
        "--converter",
        choices=("auto", "rsvg-convert", "inkscape", "cairosvg"),
        default="auto",
        help="SVG rasterizer backend",
    )
    svg_parser.add_argument("--dry-run", action="store_true")

    mp4_to_vsv = sub.add_parser("mp4-to-vsv", help="Convert MP4 to .vsv archive")
    mp4_to_vsv.add_argument("--input", required=True, help="Source MP4 file")
    mp4_to_vsv.add_argument("--output", required=True, help="Target .vsv file")
    mp4_to_vsv.add_argument("--vectorizer", choices=("auto", "vtracer"), default="auto")
    mp4_to_vsv.add_argument("--dry-run", action="store_true")

    vsv_to_mp4 = sub.add_parser(
        "vsv-to-mp4",
        help="Render .vsv back to MP4 at arbitrary output fps (resampling vector frames)",
    )
    vsv_to_mp4.add_argument("--input", required=True, help="Source .vsv file")
    vsv_to_mp4.add_argument("--output", required=True, help="Target MP4")
    vsv_to_mp4.add_argument("--fps", type=int, default=120, help="Target fps")
    vsv_to_mp4.add_argument("--converter", choices=("auto", "rsvg-convert", "inkscape", "cairosvg"), default="auto")
    vsv_to_mp4.add_argument("--dry-run", action="store_true")

    vsv_to_ui = sub.add_parser("vsv-to-ui", help="Extract .vsv and generate a simple browser player UI")
    vsv_to_ui.add_argument("--input", required=True, help="Source .vsv file")
    vsv_to_ui.add_argument("--output", required=True, help="Target directory for player assets")
    vsv_to_ui.add_argument("--title", default="VSV Player", help="HTML page title")
    vsv_to_ui.add_argument("--dry-run", action="store_true")

    gui = sub.add_parser("gui", help="Start a PyQt6 desktop app for conversion and playback")
    gui.add_argument("--workspace", default="out/gui-workspace", help="Storage for temporary and generated files")

    return parser.parse_args(argv)


def discover_inputs(user_input: str) -> list[Path]:
    path = Path(user_input)
    if path.is_file() and path.suffix.lower() == ".svg":
        return [path]
    if path.is_dir():
        return sorted(p for p in path.iterdir() if p.suffix.lower() == ".svg")
    return sorted(Path(p) for p in glob.glob(user_input) if p.lower().endswith(".svg"))


def pick_svg_converter(choice: str, dry_run: bool = False) -> str:
    if choice != "auto":
        return choice
    if shutil.which("rsvg-convert"):
        return "rsvg-convert"
    if shutil.which("inkscape"):
        return "inkscape"
    try:
        import cairosvg  # noqa: F401

        return "cairosvg"
    except ImportError as exc:
        if dry_run:
            return "rsvg-convert"
        raise RuntimeError("Install rsvg-convert, inkscape, or cairosvg.") from exc


def pick_vectorizer(choice: str, dry_run: bool = False) -> str:
    if choice != "auto":
        return choice
    if shutil.which("vtracer"):
        return "vtracer"
    if dry_run:
        return "vtracer"
    raise RuntimeError("No vectorizer found. Install vtracer for mp4-to-vsv.")


def run(cmd: Sequence[str], dry_run: bool) -> None:
    print("$", " ".join(cmd))
    if not dry_run:
        subprocess.run(cmd, check=True)


def build_raster_command(converter: str, svg_path: Path, png_path: Path, width: int, height: int) -> Sequence[str]:
    if converter == "rsvg-convert":
        return ("rsvg-convert", "-w", str(width), "-h", str(height), "-o", str(png_path), str(svg_path))
    if converter == "inkscape":
        return ("inkscape", str(svg_path), f"--export-filename={png_path}", f"--export-width={width}", f"--export-height={height}")
    if converter == "cairosvg":
        return (sys.executable, "-m", "cairosvg", str(svg_path), "-o", str(png_path), "-W", str(width), "-H", str(height))
    raise ValueError(f"Unsupported converter: {converter}")


def encode_video(png_pattern: str, output_path: Path, fps: int, width: int, height: int, dry_run: bool, input_mode: str, duration: float) -> None:
    filters = f"scale={width}:{height}:flags=lanczos,format=yuv420p"
    cmd: list[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"]
    if input_mode == "single":
        cmd.extend(["-loop", "1", "-t", f"{duration:.3f}"])
    cmd.extend(["-framerate", str(fps), "-i", png_pattern, "-vf", filters, "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-movflags", "+faststart", str(output_path)])
    run(cmd, dry_run)


def probe_video(input_path: Path) -> dict[str, str]:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate", "-of", "json", str(input_path)]
    try:
        raw = subprocess.check_output(cmd)
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe not found. Install ffmpeg/ffprobe.") from exc
    data = json.loads(raw)
    stream = data["streams"][0]
    return {"width": str(stream["width"]), "height": str(stream["height"]), "fps": str(float(Fraction(stream["r_frame_rate"])))}


def build_vtracer_command(input_png: Path, output_svg: Path) -> list[str]:
    return ["vtracer", "--input", str(input_png), "--output", str(output_svg), "--colormode", "color"]


def mp4_to_vsv(input_mp4: Path, output_vsv: Path, vectorizer: str, dry_run: bool) -> None:
    if dry_run:
        fps = 24.0
        width, height = 1920, 1080
    else:
        meta = probe_video(input_mp4)
        fps = float(meta["fps"])
        width = int(meta["width"])
        height = int(meta["height"])

    with tempfile.TemporaryDirectory(prefix="vsv-build-") as tmp:
        tmp_dir = Path(tmp)
        png_dir = tmp_dir / "png"
        svg_dir = tmp_dir / "svg"
        png_dir.mkdir()
        svg_dir.mkdir()

        run(["ffmpeg", "-y", "-i", str(input_mp4), str(png_dir / "frame_%06d.png")], dry_run)

        frame_count = 1 if dry_run else len(list(png_dir.glob("frame_*.png")))
        if frame_count == 0 and not dry_run:
            raise RuntimeError("No frames extracted from MP4.")

        for index in range(1, frame_count + 1):
            png = png_dir / f"frame_{index:06d}.png"
            svg = svg_dir / f"frame_{index:06d}.svg"
            run(build_vtracer_command(png, svg), dry_run)

        manifest = {"vsv_version": VSV_VERSION, "source": str(input_mp4.name), "source_fps": fps, "width": width, "height": height, "frame_count": frame_count, "vectorizer": vectorizer}

        print(f"$ write archive {output_vsv}")
        if not dry_run:
            output_vsv.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(output_vsv, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))
                for svg in sorted(svg_dir.glob("frame_*.svg")):
                    archive.write(svg, f"frames/{svg.name}")


def vsv_to_mp4(input_vsv: Path, output_mp4: Path, fps: int, converter: str, dry_run: bool) -> None:
    if fps < 1:
        raise ValueError("Target fps must be >= 1.")
    converter = pick_svg_converter(converter, dry_run=dry_run)

    with tempfile.TemporaryDirectory(prefix="vsv-render-") as tmp:
        tmp_dir = Path(tmp)
        extract_dir = tmp_dir / "extract"
        frames_dir = tmp_dir / "png"
        extract_dir.mkdir()
        frames_dir.mkdir()

        print(f"$ unzip {input_vsv}")
        if not dry_run:
            with zipfile.ZipFile(input_vsv) as archive:
                archive.extractall(extract_dir)
            manifest = json.loads((extract_dir / "manifest.json").read_text())
            source_fps = float(manifest["source_fps"])
            width = int(manifest["width"])
            height = int(manifest["height"])
            frame_count = int(manifest["frame_count"])
        else:
            source_fps = 24.0
            width, height, frame_count = 1920, 1080, 1

        if source_fps <= 0:
            raise RuntimeError("Invalid source_fps in VSV manifest; must be > 0.")

        total_seconds = frame_count / source_fps
        out_frames = max(1, round(total_seconds * fps))

        for out_index in range(1, out_frames + 1):
            t = (out_index - 1) / fps
            src_index = min(frame_count, max(1, round(t * source_fps) + 1))
            svg_path = extract_dir / "frames" / f"frame_{src_index:06d}.svg"
            png_path = frames_dir / f"frame_{out_index:06d}.png"
            run(build_raster_command(converter, svg_path, png_path, width, height), dry_run)

        encode_video(str(frames_dir / "frame_%06d.png"), output_mp4, fps, width, height, dry_run, "sequence", 0)


def vsv_to_ui(input_vsv: Path, output_dir: Path, title: str, dry_run: bool) -> None:
    print(f"$ generate ui player in {output_dir}")
    if dry_run:
        print(f"$ unzip {input_vsv} -> {output_dir}")
        print(f"$ write {output_dir / 'index.html'}")
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(input_vsv) as archive:
        archive.extractall(output_dir)
    (output_dir / "index.html").write_text(
        f"""<!doctype html><html><head><meta charset='utf-8'><title>{title}</title></head><body><h1>{title}</h1><p>Use any static file server to open this folder.</p></body></html>""",
        encoding="utf-8",
    )


def run_gui(workspace: Path) -> None:
    try:
        from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, pyqtSignal
        from PyQt6.QtWidgets import (
            QApplication,
            QFileDialog,
            QFormLayout,
            QGridLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QSlider,
            QSpinBox,
            QDoubleSpinBox,
            QVBoxLayout,
            QWidget,
        )
        from PyQt6.QtSvgWidgets import QSvgWidget
    except ImportError as exc:
        raise RuntimeError("PyQt6 is required for GUI mode. Install with: pip install PyQt6") from exc

    workspace.mkdir(parents=True, exist_ok=True)

    class WorkerSignals(QObject):
        finished = pyqtSignal(object)
        error = pyqtSignal(str)

    class TaskWorker(QRunnable):
        def __init__(self, task: Callable[[], object]):
            super().__init__()
            self.task = task
            self.signals = WorkerSignals()

        def run(self) -> None:
            try:
                result = self.task()
            except Exception as exc:  # noqa: BLE001
                self.signals.error.emit(str(exc))
                return
            self.signals.finished.emit(result)

    class VsvMainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Vector Smooth Video")
            self.resize(1100, 760)
            self.thread_pool = QThreadPool.globalInstance()
            self.player_timer = QTimer()
            self.player_timer.timeout.connect(self._tick)

            self.manifest: dict[str, float | int] | None = None
            self.frame_paths: list[Path] = []
            self.current_frame = 1
            self.elapsed = 0.0
            self.last_source_index = 1

            root = QWidget()
            self.setCentralWidget(root)
            layout = QVBoxLayout(root)

            convert_box = QGroupBox("MP4 → VSV")
            convert_form = QFormLayout(convert_box)
            mp4_row = QHBoxLayout()
            self.mp4_input = QLineEdit()
            self.mp4_browse = QPushButton("Browse…")
            self.mp4_browse.clicked.connect(self._pick_mp4)
            mp4_row.addWidget(self.mp4_input)
            mp4_row.addWidget(self.mp4_browse)
            convert_form.addRow("Input MP4", mp4_row)

            out_row = QHBoxLayout()
            self.vsv_output = QLineEdit(str(workspace / "output.vsv"))
            self.vsv_browse = QPushButton("Save as…")
            self.vsv_browse.clicked.connect(self._pick_output)
            out_row.addWidget(self.vsv_output)
            out_row.addWidget(self.vsv_browse)
            convert_form.addRow("Output VSV", out_row)

            self.convert_button = QPushButton("Convert")
            self.convert_button.clicked.connect(self._convert_mp4_to_vsv)
            self.convert_status = QLabel("Ready")
            convert_form.addRow(self.convert_button, self.convert_status)

            player_box = QGroupBox("VSV Player")
            player_layout = QVBoxLayout(player_box)
            top_row = QGridLayout()
            self.vsv_input = QLineEdit()
            self.vsv_load = QPushButton("Open VSV…")
            self.vsv_load.clicked.connect(self._pick_vsv)
            self.vsv_load_button = QPushButton("Load")
            self.vsv_load_button.clicked.connect(self._load_vsv)
            top_row.addWidget(QLabel("VSV file"), 0, 0)
            top_row.addWidget(self.vsv_input, 0, 1)
            top_row.addWidget(self.vsv_load, 0, 2)
            top_row.addWidget(self.vsv_load_button, 0, 3)

            self.fps_spin = QSpinBox()
            self.fps_spin.setRange(1, 1000)
            self.fps_spin.setValue(120)
            self.speed_spin = QDoubleSpinBox()
            self.speed_spin.setRange(0.1, 10.0)
            self.speed_spin.setSingleStep(0.1)
            self.speed_spin.setValue(1.0)
            top_row.addWidget(QLabel("Output FPS"), 1, 0)
            top_row.addWidget(self.fps_spin, 1, 1)
            top_row.addWidget(QLabel("Speed"), 1, 2)
            top_row.addWidget(self.speed_spin, 1, 3)

            player_layout.addLayout(top_row)

            self.svg_view = QSvgWidget()
            self.svg_view.setMinimumHeight(420)
            player_layout.addWidget(self.svg_view)

            seek_row = QHBoxLayout()
            self.seek = QSlider()
            self.seek.setOrientation(Qt.Orientation.Horizontal)
            self.seek.setMinimum(1)
            self.seek.setMaximum(1)
            self.seek.valueChanged.connect(self._seek_frame)
            seek_row.addWidget(QLabel("Seek"))
            seek_row.addWidget(self.seek)
            player_layout.addLayout(seek_row)

            controls = QHBoxLayout()
            self.play_button = QPushButton("Play")
            self.pause_button = QPushButton("Pause")
            self.reset_button = QPushButton("Reset")
            self.play_button.clicked.connect(self._play)
            self.pause_button.clicked.connect(self._pause)
            self.reset_button.clicked.connect(self._reset)
            controls.addWidget(self.play_button)
            controls.addWidget(self.pause_button)
            controls.addWidget(self.reset_button)
            player_layout.addLayout(controls)

            self.player_status = QLabel("No VSV loaded")
            player_layout.addWidget(self.player_status)

            layout.addWidget(convert_box)
            layout.addWidget(player_box)

        def _pick_mp4(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, "Select MP4", str(workspace), "MP4 Files (*.mp4)")
            if filename:
                self.mp4_input.setText(filename)

        def _pick_output(self) -> None:
            filename, _ = QFileDialog.getSaveFileName(self, "Save VSV", str(workspace / "output.vsv"), "VSV Files (*.vsv)")
            if filename:
                self.vsv_output.setText(filename)

        def _pick_vsv(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, "Select VSV", str(workspace), "VSV Files (*.vsv)")
            if filename:
                self.vsv_input.setText(filename)

        def _convert_mp4_to_vsv(self) -> None:
            src = Path(self.mp4_input.text().strip())
            dst = Path(self.vsv_output.text().strip())
            if not src.is_file():
                QMessageBox.warning(self, "Invalid input", "Please select a valid MP4 file.")
                return
            if dst.suffix.lower() != ".vsv":
                QMessageBox.warning(self, "Invalid output", "Output file must end with .vsv")
                return

            self.convert_button.setEnabled(False)
            self.convert_status.setText("Converting…")

            worker = TaskWorker(lambda: mp4_to_vsv(src, dst, pick_vectorizer("auto"), dry_run=False))
            worker.signals.finished.connect(lambda _result: self._conversion_done(dst))
            worker.signals.error.connect(self._conversion_error)
            self.thread_pool.start(worker)

        def _conversion_done(self, output_path: Path) -> None:
            self.convert_button.setEnabled(True)
            self.convert_status.setText(f"Created: {output_path}")

        def _conversion_error(self, message: str) -> None:
            self.convert_button.setEnabled(True)
            self.convert_status.setText("Conversion failed")
            QMessageBox.critical(self, "Conversion failed", message)

        def _load_vsv(self) -> None:
            file_path = Path(self.vsv_input.text().strip())
            if not file_path.is_file():
                QMessageBox.warning(self, "Invalid input", "Please select a valid VSV file.")
                return
            session_dir = workspace / f"session-{file_path.stem}"
            if session_dir.exists():
                shutil.rmtree(session_dir)
            session_dir.mkdir(parents=True)

            with zipfile.ZipFile(file_path) as archive:
                archive.extractall(session_dir)

            manifest_path = session_dir / "manifest.json"
            if not manifest_path.exists():
                QMessageBox.warning(self, "Invalid VSV", "manifest.json is missing.")
                return

            self.manifest = json.loads(manifest_path.read_text())
            frame_count = int(self.manifest.get("frame_count", 0))
            if frame_count < 1:
                QMessageBox.warning(self, "Invalid VSV", "No frames found in archive.")
                return
            self.frame_paths = [session_dir / "frames" / f"frame_{index:06d}.svg" for index in range(1, frame_count + 1)]
            self.seek.setMaximum(frame_count)
            self.seek.setValue(1)
            self.fps_spin.setValue(max(1, round(float(self.manifest.get("source_fps", 24)))))
            self.current_frame = 1
            self.elapsed = 0.0
            self.last_source_index = 1
            self._render_frame(1)
            self.player_status.setText(f"Loaded {frame_count} frames")

        def _render_frame(self, frame_index: int) -> None:
            if not self.frame_paths:
                return
            bounded = min(len(self.frame_paths), max(1, frame_index))
            frame_path = self.frame_paths[bounded - 1]
            if frame_path.exists():
                self.svg_view.load(str(frame_path))
            self.current_frame = bounded
            if self.seek.value() != bounded:
                self.seek.blockSignals(True)
                self.seek.setValue(bounded)
                self.seek.blockSignals(False)
            self.player_status.setText(f"Frame {bounded}/{len(self.frame_paths)}")

        def _seek_frame(self, frame_index: int) -> None:
            self._render_frame(frame_index)

        def _play(self) -> None:
            if not self.manifest:
                return
            self.player_timer.start(16)

        def _pause(self) -> None:
            self.player_timer.stop()

        def _reset(self) -> None:
            self.player_timer.stop()
            self.elapsed = 0.0
            self._render_frame(1)

        def _tick(self) -> None:
            if not self.manifest:
                return
            source_fps = float(self.manifest.get("source_fps", 24.0))
            target_fps = float(self.fps_spin.value())
            speed = float(self.speed_spin.value())
            self.elapsed += (1.0 / 60.0) * speed
            output_frame = max(1, int(self.elapsed * target_fps) + 1)
            source_index = min(len(self.frame_paths), max(1, round(((output_frame - 1) / target_fps) * source_fps) + 1))
            if source_index != self.last_source_index:
                self._render_frame(source_index)
                self.last_source_index = source_index
            if source_index >= len(self.frame_paths):
                self.player_timer.stop()

    app = QApplication(sys.argv)
    window = VsvMainWindow()
    window.show()
    raise SystemExit(app.exec())


def svg_to_mp4(args: argparse.Namespace) -> int:
    if args.fps < 1:
        print("--fps must be >= 1", file=sys.stderr)
        return 2

    if args.supersample < 1:
        print("--supersample must be >= 1", file=sys.stderr)
        return 2

    inputs = discover_inputs(args.input)
    if not inputs:
        print("No SVG inputs found.", file=sys.stderr)
        return 2

    converter = pick_svg_converter(args.converter, dry_run=args.dry_run)
    scale_w = args.width * args.supersample
    scale_h = args.height * args.supersample
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="vector-video-") as tmp_dir:
        frame_dir = Path(tmp_dir)
        for index, svg_path in enumerate(inputs, start=1):
            png_path = frame_dir / f"frame_{index:06d}.png"
            run(build_raster_command(converter, svg_path, png_path, scale_w, scale_h), args.dry_run)

        if len(inputs) == 1:
            encode_video(str(frame_dir / "frame_000001.png"), output, args.fps, args.width, args.height, args.dry_run, "single", args.duration)
        else:
            encode_video(str(frame_dir / "frame_%06d.png"), output, args.fps, args.width, args.height, args.dry_run, "sequence", args.duration)

    print(f"Done: {output}")
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "svg-to-mp4":
        return svg_to_mp4(args)
    if args.command == "mp4-to-vsv":
        vectorizer = pick_vectorizer(args.vectorizer, dry_run=args.dry_run)
        mp4_to_vsv(Path(args.input), Path(args.output), vectorizer, args.dry_run)
        return 0
    if args.command == "vsv-to-mp4":
        vsv_to_mp4(Path(args.input), Path(args.output), args.fps, args.converter, args.dry_run)
        return 0
    if args.command == "vsv-to-ui":
        vsv_to_ui(Path(args.input), Path(args.output), args.title, args.dry_run)
        return 0
    if args.command == "gui":
        run_gui(Path(args.workspace))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
