# vector-smooth-video

Ja — jetzt kannst du **MP4 → VSV (vector-smooth-video)** umwandeln und später wieder mit beliebiger Ziel-FPS ausgeben.

## Was ist `.vsv`?

`.vsv` ist in diesem Projekt ein ZIP-Container mit:
- `manifest.json` (Auflösung, Quell-FPS, Frame-Anzahl)
- `frames/frame_XXXXXX.svg` (vektorisierte Einzelbilder)

Damit kann ein Renderer auf jede gewünschte Ausgabe-FPS resamplen (z. B. 120, 240, 1000 FPS theoretisch), weil die Inhalte als Vektorframes vorliegen.

## Voraussetzungen

- `ffmpeg` + `ffprobe`
- Für MP4 → VSV: `vtracer`
- Für SVG/VSV → MP4: einer von
  - `rsvg-convert` (empfohlen)
  - `inkscape`
  - oder Python-Paket `cairosvg`

## 1) MP4 zu VSV konvertieren

```bash
python vector_video.py mp4-to-vsv \
  --input input.mp4 \
  --output out/video.vsv
```

## 2) VSV mit beliebiger FPS nach MP4 rendern

```bash
python vector_video.py vsv-to-mp4 \
  --input out/video.vsv \
  --output out/video_240fps.mp4 \
  --fps 240
```

## 3) SVG direkt zu MP4 (bestehender Modus)

```bash
python vector_video.py svg-to-mp4 \
  --input "frames/*.svg" \
  --output out/animation.mp4 \
  --fps 60 \
  --width 1920 \
  --height 1080 \
  --supersample 2
```

Backward-Compatibility: Der alte Aufruf ohne Subcommand funktioniert weiterhin (`--input ... --output ...` wird als `svg-to-mp4` interpretiert).

## Dry Run

```bash
python vector_video.py mp4-to-vsv --input input.mp4 --output out/video.vsv --dry-run
```
