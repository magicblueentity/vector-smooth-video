# vector-smooth-video

`vector-smooth-video` ist ein Python-basiertes Toolset zur Konvertierung zwischen rasterbasiertem Video (MP4) und einem vektorbasierten Archivformat (`.vsv`).

Das Projekt unterstützt sowohl eine **CLI** für reproduzierbare Workflows als auch eine **PyQt6-Desktop-Oberfläche** für eine einfache, geführte Bedienung.

---

## Kernfunktionen

- **SVG-Sequenz → MP4** (`svg-to-mp4`)
- **MP4 → VSV** (`mp4-to-vsv`)
- **VSV → MP4** mit frei wählbarer Ziel-FPS (`vsv-to-mp4`)
- **VSV → statisches UI-Paket** (`vsv-to-ui`)
- **Desktop-GUI mit PyQt6** (`gui`) für Konvertierung und Playback

---

## Formatübersicht: `.vsv`

Eine `.vsv`-Datei ist ein ZIP-Archiv mit:

- `manifest.json` (z. B. Auflösung, Frame-Anzahl, Quell-FPS)
- `frames/frame_XXXXXX.svg` (vektorisierte Einzelbilder)

---

## Voraussetzungen

### Systemabhängigkeiten

- `ffmpeg` und `ffprobe`
- Für MP4 → VSV: `vtracer`
- Für SVG/VSV → MP4: einer der folgenden Rasterizer
  - `rsvg-convert` (empfohlen)
  - `inkscape`
  - oder das Python-Paket `cairosvg`

### Python

- Python 3.10+
- Für die Desktop-GUI: `PyQt6`

Beispielinstallation:

```bash
pip install PyQt6 cairosvg
```

---

## Schnellstart

### 1) Desktop-GUI starten (empfohlen)

```bash
python vector_video.py gui
```

In der GUI können Sie:

- ein MP4 auswählen und direkt in `.vsv` umwandeln,
- `.vsv`-Dateien laden,
- Playback mit `Output FPS`, `Speed`, `Seek`, `Play/Pause/Reset` steuern.

### 2) CLI-Beispiele

**MP4 → VSV**

```bash
python vector_video.py mp4-to-vsv --input input.mp4 --output out/video.vsv
```

**VSV → MP4 (z. B. 240 FPS)**

```bash
python vector_video.py vsv-to-mp4 --input out/video.vsv --output out/video_240fps.mp4 --fps 240
```

**SVG-Sequenz → MP4**

```bash
python vector_video.py svg-to-mp4 --input "frames/*.svg" --output out/animation.mp4 --fps 60 --width 1920 --height 1080 --supersample 2
```

**VSV → statisches UI-Paket**

```bash
python vector_video.py vsv-to-ui --input out/video.vsv --output out/ui-player --title "VSV Player"
```

---

## Kompatibilität

Der historische Aufruf ohne Subcommand bleibt weiterhin verfügbar:

```bash
python vector_video.py --input frames/*.svg --output out/animation.mp4
```

Dieser Aufruf wird automatisch als `svg-to-mp4` interpretiert.
