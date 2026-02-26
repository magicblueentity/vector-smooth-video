#!/usr/bin/env python3
"""Tools for converting between SVG sequences, MP4 and VSV archives."""

from __future__ import annotations

import argparse
import cgi
import glob
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from fractions import Fraction
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse
from uuid import uuid4


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

    gui = sub.add_parser("gui", help="Start GUI web app for MP4 -> VSV conversion and playback")
    gui.add_argument("--host", default="127.0.0.1")
    gui.add_argument("--port", type=int, default=8765)
    gui.add_argument("--workspace", default="out/gui-workspace", help="Storage for uploads and generated files")

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


def build_ui_html(title: str) -> str:
    html = """<!doctype html><html lang='de'><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/><title>__TITLE__</title>
<style>body{font-family:system-ui,sans-serif;margin:0;background:#111;color:#eee}.app{max-width:1100px;margin:auto;padding:16px}.card{background:#1b1b1b;border:1px solid #333;border-radius:10px;padding:12px;margin-bottom:12px}.video{background:#fff;min-height:360px;display:flex;justify-content:center;align-items:center;overflow:hidden}#frame{width:100%;max-height:70vh}label{display:block;margin:6px 0}button{padding:8px 10px}</style></head><body>
<div class='app'><h1>__TITLE__</h1>
<div class='card'><h2>1) MP4 → VSV (im GUI)</h2><input id='mp4' type='file' accept='video/mp4'/><button id='convert'>Konvertieren</button><p id='convertStatus'></p><a id='download' style='display:none'>VSV herunterladen</a></div>
<div class='card'><h2>2) VSV laden & abspielen</h2><input id='vsv' type='file' accept='.vsv'/><button id='load'>VSV laden</button><p id='loadStatus'></p><div class='video'><img id='frame' alt='frame'/></div>
<label>Output FPS <input id='fps' type='number' min='1' value='120'/></label><label>Speed <input id='speed' type='number' min='0.1' step='0.1' value='1'/></label><label>Seek <input id='seek' type='range' min='1' max='1' value='1'/></label>
<button id='play'>Play</button><button id='pause'>Pause</button><button id='reset'>Reset</button><p id='status'></p></div></div>
<script>
let manifest=null,session=null;const state={playing:false,frame:1,elapsed:0,lastTs:null};
const frameEl=document.getElementById('frame'),fpsEl=document.getElementById('fps'),speedEl=document.getElementById('speed'),seekEl=document.getElementById('seek'),statusEl=document.getElementById('status');
function framePath(i){return `/session/${session}/frames/frame_${String(i).padStart(6,'0')}.svg`;}
function render(){if(!manifest)return;frameEl.src=framePath(state.frame);seekEl.value=String(state.frame);statusEl.textContent=`frame ${state.frame}/${manifest.frame_count}`;}
function tick(ts){if(!state.playing||!manifest)return; if(state.lastTs===null)state.lastTs=ts; const dt=(ts-state.lastTs)/1000; state.lastTs=ts; state.elapsed+=dt*Number(speedEl.value||1); const tfps=Math.max(1,Number(fpsEl.value||1)); const out=Math.floor(state.elapsed*tfps)+1; state.frame=Math.min(manifest.frame_count,Math.max(1,Math.round(((out-1)/tfps)*manifest.source_fps)+1)); render(); if(state.frame>=manifest.frame_count)state.playing=false; requestAnimationFrame(tick);}
document.getElementById('play').onclick=()=>{if(!state.playing){state.playing=true;state.lastTs=null;requestAnimationFrame(tick);}};document.getElementById('pause').onclick=()=>state.playing=false;document.getElementById('reset').onclick=()=>{state.playing=false;state.frame=1;state.elapsed=0;render();};seekEl.oninput=()=>{state.frame=Number(seekEl.value);render();};
async function postFile(url,input){const file=input.files[0]; if(!file) throw new Error('Bitte Datei wählen'); const fd=new FormData(); fd.append('file',file,file.name); const r=await fetch(url,{method:'POST',body:fd}); if(!r.ok) throw new Error(await r.text()); return r.json();}
document.getElementById('convert').onclick=async()=>{const s=document.getElementById('convertStatus'); try{s.textContent='Konvertiere...'; const data=await postFile('/api/mp4-to-vsv',document.getElementById('mp4')); s.textContent=`Fertig: ${data.filename}`; const a=document.getElementById('download'); a.href=data.download_url; a.textContent='Download VSV'; a.style.display='inline';}catch(e){s.textContent=e.message;}};
document.getElementById('load').onclick=async()=>{const s=document.getElementById('loadStatus'); try{s.textContent='Lade...'; const data=await postFile('/api/load-vsv',document.getElementById('vsv')); manifest=data.manifest; session=data.session_id; seekEl.max=String(manifest.frame_count); fpsEl.value=String(Math.max(1,Math.round(manifest.source_fps))); state.frame=1; state.elapsed=0; render(); s.textContent='Bereit'; }catch(e){s.textContent=e.message;}};
</script></body></html>"""
    return html.replace("__TITLE__", title)


def vsv_to_ui(input_vsv: Path, output_dir: Path, title: str, dry_run: bool) -> None:
    print(f"$ generate ui player in {output_dir}")
    if dry_run:
        print(f"$ unzip {input_vsv} -> {output_dir}")
        print(f"$ write {output_dir / 'index.html'}")
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(input_vsv) as archive:
        archive.extractall(output_dir)
    (output_dir / "index.html").write_text(build_ui_html(title), encoding="utf-8")


def run_gui(host: str, port: int, workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def _json(self, payload: dict, status: int = 200) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                body = build_ui_html("VSV GUI").encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path.startswith("/downloads/") or parsed.path.startswith("/session/"):
                rel = parsed.path.lstrip("/")
                target = workspace / rel
                if target.is_file():
                    data = target.read_bytes()
                    ctype = "application/octet-stream"
                    if target.suffix == ".svg":
                        ctype = "image/svg+xml"
                    elif target.suffix == ".json":
                        ctype = "application/json"
                    elif target.suffix == ".vsv":
                        ctype = "application/zip"
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            ctype, _ = cgi.parse_header(self.headers.get("Content-Type", ""))
            if ctype != "multipart/form-data":
                self._json({"error": "multipart/form-data erwartet"}, 400)
                return
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"]})
            upload = form["file"] if "file" in form else None
            if upload is None or not upload.file:
                self._json({"error": "file fehlt"}, 400)
                return

            if parsed.path == "/api/mp4-to-vsv":
                uid = uuid4().hex
                in_path = workspace / f"upload-{uid}.mp4"
                out_path = workspace / "downloads" / f"video-{uid}.vsv"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                in_path.write_bytes(upload.file.read())
                try:
                    mp4_to_vsv(in_path, out_path, pick_vectorizer("auto"), dry_run=False)
                except Exception as exc:  # noqa: BLE001
                    self._json({"error": str(exc)}, 500)
                    return
                self._json({"filename": out_path.name, "download_url": f"/downloads/{out_path.name}"})
                return

            if parsed.path == "/api/load-vsv":
                uid = uuid4().hex
                session_dir = workspace / "session" / uid
                session_dir.mkdir(parents=True, exist_ok=True)
                vsv_path = session_dir / "upload.vsv"
                vsv_path.write_bytes(upload.file.read())
                try:
                    with zipfile.ZipFile(vsv_path) as archive:
                        archive.extractall(session_dir)
                    manifest = json.loads((session_dir / "manifest.json").read_text())
                except Exception as exc:  # noqa: BLE001
                    self._json({"error": str(exc)}, 400)
                    return
                self._json({"session_id": uid, "manifest": manifest})
                return

            self.send_error(HTTPStatus.NOT_FOUND)

    print(f"GUI running on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


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
        run_gui(args.host, args.port, Path(args.workspace))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
