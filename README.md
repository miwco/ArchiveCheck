# ArchiveCheck

Extracts archival metadata from student films:

1. **Music cue sheet** — timed music segments, and for recognizable commercial
   recordings the title / artist / album / ISRC / label. Output: `music_cuesheet.csv`
   and `.xlsx`.
2. **End-credits list** — role → name pairs as `credits.txt` plus `credits.csv` /
   `.xlsx`, ready for manual checking against (or future import into) the archive.

Designed to run on **small web/proxy files**, not masters — it only needs the audio
track and the credit frames, so a proxy gives the same results as long as credit
text stays legible (≥720p recommended). Codec is irrelevant; ffmpeg decodes it.

> **What "copyrighted" means here:** fingerprinting identifies *specific commercial
> recordings*. A hit means "this is a released track (almost certainly needs
> clearing)". A miss means "original score, library music, or simply not in the
> database — needs a human check". It is not a legal rights oracle.

## Install

Requires **Python 3.10+** and a few external binaries. Commands below use the
Windows `py` launcher; on macOS/Linux use `python3` instead (and install the
binaries with your package manager, e.g. `brew install ffmpeg tesseract chromaprint`
or `apt install ffmpeg tesseract-ocr libchromaprint-tools`).

```powershell
py -m pip install --upgrade pip                 # avoids a pip 23 build-tracker bug
py -m pip install -r requirements.txt           # openpyxl + inaSpeechSegmenter (TensorFlow)
```

> The music detector pulls in TensorFlow, which **requires NumPy 1.x** (pinned in
> `requirements.txt`). If you see a `numpy.core._multiarray_umath failed to import`
> error, run `py -m pip install "numpy<2"`.

External tools (not pip packages):

| Tool        | Needed for                    | Install (Windows)                                   |
|-------------|-------------------------------|-----------------------------------------------------|
| ffmpeg/ffprobe | everything (required)      | already at `C:\ffmpeg\bin`, or `winget install Gyan.FFmpeg` |
| fpcalc (Chromaprint) | song identification   | https://acoustid.org/chromaprint (unzip, add to PATH) |
| tesseract   | credits OCR                   | `winget install -e --id UB-Mannheim.TesseractOCR`   |

API keys (optional but recommended):

- `ACOUSTID_API_KEY` — free, register at https://acoustid.org/new-application. Without
  it, music timing still works but nothing gets identified.
- `ANTHROPIC_API_KEY` — used to structure messy OCR text into clean role/name rows.
  Without it, a heuristic parser is used (works, but weaker on unusual layouts).

The tool finds binaries on `PATH`, or via env overrides `FFMPEG`, `FFPROBE`,
`FPCALC`, `TESSERACT` (each may point at the binary or its folder). Keys and
overrides can also live in a `.env` file at the project root:

```
ACOUSTID_API_KEY=xxxx
ANTHROPIC_API_KEY=sk-ant-xxxx
TESSERACT=C:\Program Files\Tesseract-OCR\tesseract.exe
FPCALC=C:\tools\chromaprint\fpcalc.exe
```

## Usage

```powershell
py -m archivecheck --check                    # show what's installed / capable

py -m archivecheck film.mp4                   # one file  -> vc_output\film\
py -m archivecheck C:\proxies -o C:\out       # a folder  -> one subfolder each + index
```

Options: `--no-music`, `--no-credits`, `--credits-window <sec>` (how far from the
end to scan, default 180), `--keep-intermediate` (keep extracted audio/frames).

Per-film output folder contains `music_cuesheet.{csv,xlsx}`, `credits.{txt,csv,xlsx}`,
and `summary.json`. Batch runs also write `index.csv` / `index.json`.

## Output schema (matches the Arcada archive)

Columns use the archive's Swedish field names so output maps 1:1 onto a record and
is easy to check or import. CSVs are written UTF-8-with-BOM so Excel renders å/ä/ö.

**`credits.*` → SLUTTEXTER (ALLA):** `Roll`, `Namn` (+ `Tidskod`, evidence of where
the line was seen). With `ANTHROPIC_API_KEY` set, roles that clearly match the
archive vocabulary (A-foto, Editerare, Manus&Regi, Producent, Tack till, …; see
`CONFIG.archive_roles`) are normalised to that exact spelling.

**`music_cuesheet.*` → MUSIKINFORMATION (one row per Musikstycke):** `Musikstycke`,
`Namn`, `Stycket börjar`, `Stycket slutar`, `Längd`, `Kompositör`, `Instrumental`,
`Textförfattare`, `Arrangör`, `Artist`, `Musiktyp`,
`Har Arcada alla rättigheter till stycket?`, `Musiklicens`, then recognition
evidence (`Status`, `Säkerhet`, `ISRC`, `Skivbolag`, `Album`, `Kommentar`).

Automation fills the **timing** (`Stycket börjar/slutar`, `Längd`) — the fields the
archive most often leaves as *Information saknas!* — plus `Namn`/`Artist` when a
track is recognised. Columns it cannot determine (composer, lyricist, arranger,
rights, license) are left blank for a human, exactly as the archive shows them.

## How it works

```
proxy.mp4
  ├─ ffmpeg → mono 16kHz wav → detect music regions (inaSpeechSegmenter)
  │     → one region = one Musikstycke (start/stop/length from the detector)
  │     → probe each region with fpcalc → AcoustID + MusicBrainz to ANNOTATE it
  │     → music_cuesheet
  └─ ffmpeg → credit-window frames → OCR (tesseract) → de-dup scrolled lines
        → structure to role/name (LLM, heuristic fallback) → credits
```

**Timing is the priority.** Each detected music region becomes one cue with an
accurate `Stycket börjar / slutar / Längd`. Recognition only *annotates* the cue:

- `Status = recognized` → a known released recording (likely a commercial track to
  clear); `Namn` / `Artist` filled in.
- `Status = unidentified music` → not in the database (likely student-made or free
  music). Still fully timed — you just type the details in manually.

Each engine fails independently: a problem in one still lets the other produce
output, and `summary.json` records warnings (missing tools, low resolution, etc.).

**Music under dialogue is flagged, not hidden.** When a detected music region
overlaps speech, its boundaries are unreliable, so the cue is marked
`Kontrolleras = Ja` (with a note in `Kommentar`), counted in `summary.json`, and
surfaced as a `music_to_check` column in the batch `index.csv`.

> **Limitation:** clean foreground music (intro/outro, montage) is detected and
> timed well. Background music *underneath dialogue* is hard for any automatic
> detector — those cues are flagged for a human to verify. Music buried under
> *continuous* dialogue for its whole length may not be detected at all, so a
> human listen-through is still recommended for a complete cue sheet.

## Recognition / segmentation backends are swappable

- `archivecheck/audio/recognize.py` — implement the `Recognizer` protocol and
  return it from `get_recognizer()` to drop in a paid service (ACRCloud/AudD) if
  free AcoustID coverage proves too thin.
- `archivecheck/audio/segment.py` — uses `inaSpeechSegmenter` if installed
  (**recommended** — this is what detects and times *unidentified* music and gives
  a total-music metric). Without it, falls back to ffmpeg silence detection, which
  cannot tell music from speech, so only *recognised* tracks get timed.
- `archivecheck/credits/ocr.py` — implement `OcrEngine` to use a cloud OCR service
  instead of Tesseract.

## Tests

```powershell
py tests\test_smoke.py
```

## Not yet built (future)

- Auto-detect the credits window (currently the last N seconds).
- Local web GUI (Streamlit) for non-technical archivists.
- Push structured output into the SSO-protected archive.

## Privacy

Output files contain **personal names** (cast, crew, credited people) extracted
from the films. Treat the contents of any output folder as personal data — keep it
out of public repositories and share it only as your archive's data policy allows.
This repository ignores the local `example/`, `samples/`, and `vc_output/` folders
for that reason.

## License

[MIT](LICENSE) — no warranty. Music identification and rights status are advisory;
always confirm licensing with a human before relying on it.
