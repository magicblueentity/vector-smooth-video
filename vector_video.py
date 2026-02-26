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
from typing import Sequence


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
        return (
            "inkscape",
            str(svg_path),
            f"--export-filename={png_path}",
            f"--export-width={width}",
            f"--export-height={height}",
        )
    if converter == "cairosvg":
        return (
            sys.executable,
            "-m",
            "cairosvg",
            str(svg_path),
            "-o",
            str(png_path),
            "-W",
            str(width),
            "-H",
            str(height),
        )
    raise ValueError(f"Unsupported converter: {converter}")


def encode_video(png_pattern: str, output_path: Path, fps: int, width: int, height: int, dry_run: bool, input_mode: str, duration: float) -> None:
    filters = f"scale={width}:{height}:flags=lanczos,format=yuv420p"
    cmd: list[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"]
    if input_mode == "single":
        cmd.extend(["-loop", "1", "-t", f"{duration:.3f}"])
    cmd.extend([
        "-framerate", str(fps), "-i", png_pattern, "-vf", filters,
        "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-movflags", "+faststart", str(output_path),
    ])
    run(cmd, dry_run)


def probe_video(input_path: Path) -> dict[str, str]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate",
        "-of",
        "json",
        str(input_path),
    ]
    try:
        raw = subprocess.check_output(cmd)
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe not found. Install ffmpeg/ffprobe.") from exc
    data = json.loads(raw)
    stream = data["streams"][0]
    return {
        "width": str(stream["width"]),
        "height": str(stream["height"]),
        "fps": str(float(Fraction(stream["r_frame_rate"]))),
    }


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

        if dry_run:
            frame_count = 1
        else:
            frame_count = len(list(png_dir.glob("frame_*.png")))
        if frame_count == 0 and not dry_run:
            raise RuntimeError("No frames extracted from MP4.")

        for index in range(1, frame_count + 1):
            png = png_dir / f"frame_{index:06d}.png"
            svg = svg_dir / f"frame_{index:06d}.svg"
            run(build_vtracer_command(png, svg), dry_run)

        manifest = {
            "vsv_version": VSV_VERSION,
            "source": str(input_mp4.name),
            "source_fps": fps,
            "width": width,
            "height": height,
            "frame_count": frame_count,
            "vectorizer": vectorizer,
        }

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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
