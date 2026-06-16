# ArchiveCheck — roadmap & status

Context for anyone (including a fresh Claude Code session on web/mobile) picking up
this project. ArchiveCheck extracts archival QC metadata from **proxy** copies of
Arcada student films. Output column names mirror the Arcada archive (Swedish) so
results map 1:1 for manual checking / future import.

## Done (on `main`)
- **Music cue sheet** — `inaSpeechSegmenter` detects & times music regions (one
  region = one *Musikstycke*); AcoustID + MusicBrainz *annotate* recognised tracks.
  Music overlapping dialogue is flagged `Kontrolleras = Ja`.
- **End credits** — ffmpeg frame sampling → Tesseract OCR → scroll de-dup → LLM
  (heuristic fallback) → `Roll` / `Namn`.
- Per-film output folder + batch `index.csv`/`index.json`; UTF-8-BOM CSV + XLSX.
- Graceful degradation; `py -m archivecheck --check` reports capability. Smoke tests.

## Done (merged to `main`)
- **EBU R128 loudness check** — one ffmpeg `loudnorm` pass → integrated loudness
  (-23 LUFS ±1), loudness range (≤15 LU), true peak (≤-1 dBTP); PASS/FAIL in
  `technical_report.txt`, `summary.json`, console, and `index.csv`.
- **Technical file info** — resolution/fps/codec/container/audio, **reference-only**
  (a proxy's codec/container differ from the master, so never failed).
- **Easy install** — `install.ps1` (deps + winget binaries + fpcalc + .env + check)
  and double-clickable `run.bat` (folder picker).

## Done (branch `video-tests`, in PR)
- **Credit OCR for low-res (360p) proxies** — upscale to ~1080p, `swe+eng` data,
  two-column `Roll  Namn` detection via word boxes, OCR-confidence filtering to
  drop footage scanned before the credits roll.
- **Controlled title vocabulary** — roles mapped to `end_credits_titles.txt`
  (~135 `Svenska / English` titles); `Roll` outputs the Swedish side; combined
  roles ("A-Foto & Klipp") split into one row per role; `Roll (original)` kept;
  unmappable flagged `Kontrolleras`. Deterministic structuring (`temperature=0`).
- **URL / links-file input** — player-page URL → embedded HLS stream, or a
  `ID URL` links file; ffmpeg streams directly, no download. Multi-input CLI.
- **Music quick-check** `music_cuesheet.txt`; cheap `claude-haiku-4-5` default.
- Verified online vs local on 6 real films: equivalent credits (run-to-run OCR
  variance only, now reduced by `temperature=0`).

## Next / ideas (not started)
- Auto-detect the credits window (currently the last N seconds) — would speed up
  low-res OCR by skipping non-credit footage, and cut cost.
- Technical QC checks (**format profile first**: resolution/fps/codec vs a target),
  black/freeze-frame detection, letterbox/interlacing, silence at head/tail.
- Cross-check extracted names against the alumni/SSO archive (flag who's missing).
- Local web GUI (Streamlit) for non-technical archivists.

## How to run
See `README.md`. Quick: `py -m archivecheck <file-or-folder>` (or `run.bat`).
Tests: `py tests\test_smoke.py`.

## Notes for contributors
- Secrets only via `.env` (never commit). Each user supplies their **own** API keys.
- Output contains personal names — keep output folders out of public repos
  (`vc_output/`, `example/`, `samples/` are gitignored).
