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

## In progress (branch `LUFS-check`)
- **EBU R128 loudness check** — one ffmpeg `loudnorm` pass → integrated loudness
  (-23 LUFS ±1), loudness range (≤15 LU), true peak (≤-1 dBTP); PASS/FAIL in
  `technical_report.txt`, `summary.json`, console, and `index.csv`.
- **Technical file info** — resolution/fps/codec/container/audio, **reference-only**
  (a proxy's codec/container differ from the master, so never failed).
- **Easy install** — `install.ps1` (deps + winget binaries + fpcalc + .env + check)
  and double-clickable `run.bat` (folder picker).

## Next / ideas (not started)
- Technical QC checks (**format profile first**: resolution/fps/codec vs a target),
  black/freeze-frame detection, letterbox/interlacing, silence at head/tail.
- Auto-detect the credits window (currently the last N seconds).
- Local web GUI (Streamlit) for non-technical archivists.
- Push structured output into the SSO-protected archive.

## How to run
See `README.md`. Quick: `py -m archivecheck <file-or-folder>` (or `run.bat`).
Tests: `py tests\test_smoke.py`.

## Notes for contributors
- Secrets only via `.env` (never commit). Each user supplies their **own** API keys.
- Output contains personal names — keep output folders out of public repos
  (`vc_output/`, `example/`, `samples/` are gitignored).
