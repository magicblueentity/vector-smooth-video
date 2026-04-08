from pathlib import Path

import vector_video


def test_discover_inputs_glob(tmp_path: Path) -> None:
    (tmp_path / "a.svg").write_text("<svg/>")
    (tmp_path / "b.svg").write_text("<svg/>")
    (tmp_path / "note.txt").write_text("x")

    files = vector_video.discover_inputs(str(tmp_path / "*.svg"))
    assert [p.name for p in files] == ["a.svg", "b.svg"]


def test_build_raster_command_rsvg() -> None:
    cmd = vector_video.build_raster_command(
        "rsvg-convert", Path("in.svg"), Path("out.png"), 3840, 2160
    )
    assert cmd[0] == "rsvg-convert"
    assert "in.svg" in cmd


def test_build_vtracer_command() -> None:
    cmd = vector_video.build_vtracer_command(Path("in.png"), Path("out.svg"))
    assert cmd[0] == "vtracer"
    assert "--input" in cmd
    assert "--output" in cmd


def test_normalize_argv_backcompat() -> None:
    normalized = vector_video._normalize_argv(["--input", "foo.svg", "--output", "bar.mp4"])
    assert normalized[0] == "svg-to-mp4"


def test_normalize_argv_empty_defaults_to_svg_to_mp4() -> None:
    assert vector_video._normalize_argv([]) == ["svg-to-mp4"]


def test_vsv_to_mp4_rejects_invalid_fps() -> None:
    try:
        vector_video.vsv_to_mp4(Path("x.vsv"), Path("x.mp4"), 0, "auto", True)
    except ValueError as exc:
        assert "fps" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError for fps=0")


def test_parse_args_vsv_to_ui() -> None:
    args = vector_video.parse_args(["vsv-to-ui", "--input", "clip.vsv", "--output", "ui"])
    assert args.command == "vsv-to-ui"
    assert args.title == "VSV Player"


def test_parse_args_gui() -> None:
    args = vector_video.parse_args(["gui", "--workspace", "tmp/work"])
    assert args.command == "gui"
    assert args.workspace == "tmp/work"


def test_vsv_to_ui_extracts_archive_and_writes_index(tmp_path: Path) -> None:
    vsv_path = tmp_path / "sample.vsv"
    out_dir = tmp_path / "ui"

    import zipfile

    with zipfile.ZipFile(vsv_path, "w") as archive:
        archive.writestr("manifest.json", '{"source_fps":24,"frame_count":1,"width":1,"height":1}')
        archive.writestr("frames/frame_000001.svg", "<svg/>")

    vector_video.vsv_to_ui(vsv_path, out_dir, "Demo Player", False)

    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "frames" / "frame_000001.svg").exists()
    index_html = (out_dir / "index.html").read_text()
    assert "Demo Player" in index_html
