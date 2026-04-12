# vector-smooth-video

`vector-smooth-video` ist ein leichtgewichtiges Python-Toolkit für Workflows rund um **SVG-Sequenzen**, **MP4-Videos** und ein kompaktes **Vektor-Archivformat (`.vsv`)**.

Der Fokus liegt auf reproduzierbaren Konvertierungen über die Kommandozeile sowie optionaler interaktiver Nutzung über eine Desktop-GUI.

## Was das Projekt bietet

- Konvertierung von SVG-Frames zu MP4.
- Konvertierung von MP4 zu einem `.vsv`-Archiv (SVG-Frame-Sequenz + Metadaten).
- Rückwandlung von `.vsv` zu MP4 mit frei wählbarer Ausgabe-FPS.
- Export eines einfachen statischen UI-Pakets aus `.vsv`.
- Optionaler GUI-Modus (PyQt6) für Konvertierung und Vorschau.

## `.vsv`-Format (kurz erklärt)

Eine `.vsv`-Datei ist ein ZIP-Archiv mit:

- `manifest.json` (z. B. Auflösung, Quell-FPS, Frame-Anzahl)
- `frames/frame_XXXXXX.svg` (vektorisierte Einzelbilder)

Dadurch bleibt der Inhalt gut inspizierbar und leicht weiterverarbeitbar.

## Voraussetzungen

### System-Tools

- `ffmpeg` und `ffprobe`
- Für `mp4-to-vsv`: `vtracer`
- Für SVG-Rasterisierung (`svg-to-mp4` / `vsv-to-mp4`):
  - bevorzugt `rsvg-convert`, alternativ
  - `inkscape` oder
  - Python-Paket `cairosvg`

### Python

- Python 3.10+
- Optional für GUI: `PyQt6`

Beispiel:

```bash
pip install cairosvg PyQt6
```

## Installation / Nutzung

Repository klonen und die CLI direkt per Python aufrufen:

```bash
python vector_video.py --help
```

Subcommands anzeigen:

```bash
python vector_video.py <subcommand> --help
```

## Typische CLI-Aufrufe

### SVG-Sequenz → MP4

```bash
python vector_video.py svg-to-mp4 \
  --input "frames/*.svg" \
  --output out/animation.mp4 \
  --fps 60 --width 1920 --height 1080 --supersample 2
```

### MP4 → VSV

```bash
python vector_video.py mp4-to-vsv \
  --input input.mp4 \
  --output out/video.vsv
```

### VSV → MP4

```bash
python vector_video.py vsv-to-mp4 \
  --input out/video.vsv \
  --output out/video_120fps.mp4 \
  --fps 120
```

### VSV → statisches UI-Paket

```bash
python vector_video.py vsv-to-ui \
  --input out/video.vsv \
  --output out/ui-player \
  --title "VSV Player"
```

### GUI starten

```bash
python vector_video.py gui
```

## Rückwärtskompatibilität

Ein historischer Aufruf ohne Subcommand wird weiterhin unterstützt:

```bash
python vector_video.py --input "frames/*.svg" --output out/animation.mp4
```

Dieser Aufruf wird intern als `svg-to-mp4` behandelt.

## Hinweise

- Viele Befehle unterstützen `--dry-run`, um geplante Schritte zu prüfen.
- Für reproduzierbare Ergebnisse empfiehlt sich ein festes Tool-Setup (gleiche Rasterizer-/Vectorizer-Versionen).

## Lizenz

Siehe `LICENSE`.
