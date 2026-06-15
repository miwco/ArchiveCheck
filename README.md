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

## Easy install (Windows)

For a one-shot setup, from the repo folder run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

It installs the Python dependencies, installs ffmpeg + Tesseract via `winget`,
best-effort downloads `fpcalc`, creates your `.env`, and prints a capability report.
Then use the double-clickable **`run.bat`** (pick a folder, or drag a file/folder
onto it) — no terminal needed. Add your free `ACOUSTID_API_KEY` to `.env` afterward
for song identification.

## Install (manual / other platforms)

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
- `ANTHROPIC_API_KEY` — structures messy OCR text into clean role/name rows and
  removes duplicate / stylized-font noise. Get one at
  [console.anthropic.com](https://console.anthropic.com) → Settings → API Keys
  (pay-as-you-go, billed separately from any Claude subscription; each user uses
  their own key). Without it, a heuristic parser is used (works, but weaker on
  unusual layouts and noise). Defaults to the cheap `claude-haiku-4-5` (~1¢/film);
  set `ANTHROPIC_MODEL=claude-opus-4-8` in `.env` for maximum quality.

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
py -m archivecheck "https://host/player.php?id=..."   # an online player link (HLS)
py -m archivecheck links.txt -o C:\out        # a "ID URL" links file, one film per line
```

Inputs can be a **local file/folder**, a **direct/HLS stream or player-page URL**,
or a **`.txt` links file** (`ID URL` per line). Player pages are fetched and their
embedded stream extracted automatically; ffmpeg reads the stream directly, so no
full download is needed.

Options: `--no-music`, `--no-credits`, `--no-loudness`, `--credits-window <sec>`
(how far from the end to scan, default 180), `--keep-intermediate`.

Per-film output folder contains `music_cuesheet.{csv,xlsx}`, `credits.{txt,csv,xlsx}`,
`technical_report.txt` (loudness + file info), and `summary.json`. Batch runs also
write `index.csv` / `index.json`.

## Loudness (EBU R128)

Each film's audio is checked against the broadcast spec in one ffmpeg pass:

| Metric | Requirement | Source |
|--------|-------------|--------|
| Program loudness | **-23 LUFS** (pass within ±1.0 LU) | integrated loudness |
| Max variation | **≤ 15 LU** | loudness range (LRA) |
| True peak | **≤ -1 dBTP** | true peak |

Results go to `technical_report.txt` (PASS/FAIL per metric), `summary.json`, the
console line, and the batch `index.csv` (`loudness_lufs`, `true_peak_dbtp`,
`lra_lu`, `loudness_pass`). Tolerances live in `CONFIG` (`loudness_target_lufs`,
`loudness_tolerance_lu`, `lra_max_lu`, `true_peak_max_dbtp`).

**File info is reference-only.** The same report lists resolution / fps / codec /
container / audio config, but these are **not** pass/failed — the checked file is a
proxy, so its codec and container legitimately differ from the master.

## Output schema (matches the Arcada archive)

Columns use the archive's Swedish field names so output maps 1:1 onto a record and
is easy to check or import. CSVs are written UTF-8-with-BOM so Excel renders å/ä/ö.

**`credits.*` → SLUTTEXTER (ALLA):** `Roll` (canonical archive title), `Namn`,
`Roll (original)` (the credit's own wording, for verification), `Kontrolleras`
(`Ja` when the role could not be mapped), and `Tidskod`. Every role is mapped onto
the **controlled title list** in `end_credtis_titles.txt` (one title per line,
typically `Svenska / English`) so the database only ever gets approved titles —
edit that file to update the vocabulary. With `ANTHROPIC_API_KEY` set, Claude does
the mapping semantically (handling abbreviations, synonyms, and the bilingual
form); a fuzzy fallback is used without a key. Roles with no confident match are
kept but flagged `Kontrolleras = Ja` for a human (never dropped, never invented).

**`music_cuesheet.*` → MUSIKINFORMATION (one row per Musikstycke):** `Musikstycke`,
`Namn`, `Stycket börjar`, `Stycket slutar`, `Längd`, `Kompositör`, `Instrumental`,
`Textförfattare`, `Arrangör`, `Artist`, `Musiktyp`,
`Har Arcada alla rättigheter till stycket?`, `Musiklicens`, then recognition
evidence (`Status`, `Säkerhet`, `ISRC`, `Skivbolag`, `Album`, `Kommentar`).

Automation fills the **timing** (`Stycket börjar/slutar`, `Längd`) — the fields the
archive most often leaves as *Information saknas!* — plus `Namn`/`Artist` when a
track is recognised. Columns it cannot determine (composer, lyricist, arranger,
rights, license) are left blank for a human, exactly as the archive shows them.

## Credits OCR on low-res proxies

Web proxies are often **360p**, where credit text is barely legible. The pipeline
compensates:
- **Upscales** credit frames toward ~1080p (lanczos) before OCR — the single
  biggest accuracy gain.
- Reads with **`swe+eng`** Tesseract data so Swedish diacritics (å/ä/ö) come out
  right (`install.ps1` downloads the Swedish data; it falls back to `eng` if absent).
- Uses **word bounding boxes** to detect the two-column `Roll  Namn` layout and
  keep each role paired with its name.
- **Filters by OCR confidence**, so footage that appears in the scan window before
  the credits roll (low-confidence junk) is dropped while real credit text is kept.
- Samples at a higher frame rate and **de-duplicates** so the moving roll is caught.

With an `ANTHROPIC_API_KEY`, a final LLM pass cleans residual OCR noise and maps
roles onto the archive vocabulary; without it, a heuristic parser is used.

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
