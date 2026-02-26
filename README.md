# vector-smooth-video

Ja — jetzt kannst du **alles im GUI machen**: MP4 hochladen, direkt in VSV umwandeln und anschließend im Player mit variablen Parametern abspielen.

## Was ist `.vsv`?

`.vsv` ist in diesem Projekt ein ZIP-Container mit:
- `manifest.json` (Auflösung, Quell-FPS, Frame-Anzahl)
- `frames/frame_XXXXXX.svg` (vektorisierte Einzelbilder)

## Voraussetzungen

- `ffmpeg` + `ffprobe`
- Für MP4 → VSV: `vtracer`
- Für SVG/VSV → MP4: einer von
  - `rsvg-convert` (empfohlen)
  - `inkscape`
  - oder Python-Paket `cairosvg`

## 1) GUI starten (empfohlen)

```bash
python vector_video.py gui --host 127.0.0.1 --port 8765
```

Dann im Browser öffnen: `http://127.0.0.1:8765`

Im GUI kannst du:
- MP4 hochladen und zu VSV konvertieren (inkl. Download-Link)
- VSV hochladen und direkt im Player abspielen
- Playback-Parameter steuern (`Output FPS`, `Speed`, `Seek`, `Play/Pause/Reset`)

## 2) Optional: MP4 zu VSV per CLI

```bash
python vector_video.py mp4-to-vsv \
  --input input.mp4 \
  --output out/video.vsv
```

## 3) Optional: VSV mit beliebiger FPS nach MP4 rendern

```bash
python vector_video.py vsv-to-mp4 \
  --input out/video.vsv \
  --output out/video_240fps.mp4 \
  --fps 240
```

## 4) Optional: VSV als statisches UI-Paket exportieren

```bash
python vector_video.py vsv-to-ui \
  --input out/video.vsv \
  --output out/ui-player \
  --title "Mein VSV Player"
```

## 5) SVG direkt zu MP4 (bestehender Modus)

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
