"""Lightweight smoke tests (run with `py tests\test_smoke.py`, no pytest needed).

Covers the pure logic (timecodes, credit parsing, line de-dup, cue merging) plus
an integration check of the recognized-cue path using a stub recognizer so it
runs without fpcalc/AcoustID. Requires ffmpeg + samples/clipA.mp4 for the last test.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archivecheck.util import fmt_timecode, slugify  # noqa: E402
from archivecheck.credits.dedup import dedup_lines, CreditLine  # noqa: E402
from archivecheck.credits.ocr import OcrFrame  # noqa: E402
from archivecheck.credits.structure import heuristic_structure, enforce_titles, CreditEntry  # noqa: E402
from archivecheck.credits.titles import map_role, load_titles  # noqa: E402
from archivecheck.report.cuesheet import build_cuesheet, write_cuesheet  # noqa: E402
from archivecheck.audio.segment import Segment  # noqa: E402
from archivecheck.audio.recognize import RecognitionResult, Track  # noqa: E402
from archivecheck.audio.loudness import _parse_loudnorm_json, _evaluate  # noqa: E402
from archivecheck.credits.ocr import _tsv_to_lines, _good_text  # noqa: E402
from archivecheck.input_source import is_url, parse_links_file, _label_from_url  # noqa: E402

passed = 0


def check(name, cond):
    global passed
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        raise SystemExit(f"Test failed: {name}")
    passed += 1


def test_timecode():
    check("timecode formats", fmt_timecode(3661.5) == "01:01:01.500")


def test_loudness_eval():
    blob = (
        'ffmpeg noise...\n{\n  "input_i" : "-23.00",\n  "input_tp" : "-2.00",\n'
        '  "input_lra" : "7.00",\n  "input_thresh" : "-33.0"\n}\n'
    )
    d = _parse_loudnorm_json(blob)
    check("loudnorm json parsed", d["input_i"] == "-23.00" and d["input_tp"] == "-2.00")

    ok = _evaluate(-23.0, -2.0, 7.0)
    check("compliant audio passes", ok.passed and ok.integrated_pass and ok.true_peak_pass and ok.lra_pass)
    check("true-peak too hot fails", not _evaluate(-23.0, -0.5, 7.0).true_peak_pass)
    check("lra too wide fails", not _evaluate(-23.0, -2.0, 20.0).lra_pass)
    check("integrated off-target fails", not _evaluate(-20.0, -2.0, 7.0).integrated_pass)


def test_tsv_columns_and_filter():
    def row(blk, par, ln, word, left, width, conf, text):
        return f"5\t1\t{blk}\t{par}\t{ln}\t{word}\t{left}\t100\t{width}\t40\t{conf}\t{text}"
    tsv = "\n".join([
        "level\tpage\tblock\tpar\tline\tword\tleft\ttop\twidth\theight\tconf\ttext",
        # two-column role/name: wide gap -> tab; intra-name gap -> space
        row(1, 1, 1, 1, 50, 200, 92, "Ljusassistent"),
        row(1, 1, 1, 2, 600, 90, 90, "Oliver"),
        row(1, 1, 1, 3, 700, 80, 88, "Milros"),
        # low-confidence junk line -> dropped
        row(1, 2, 1, 1, 50, 60, 20, "xhzq"),
        # single-column name
        row(1, 3, 1, 1, 300, 100, 85, "Aaro"),
        row(1, 3, 1, 2, 410, 140, 85, "Salmela"),
    ])
    lines = _tsv_to_lines(tsv)
    check("column gap -> tab", "Ljusassistent\tOliver Milros" in lines)
    check("low-confidence dropped", not any("xhzq" in l for l in lines))
    check("single-column name kept", "Aaro Salmela" in lines)
    check("good_text rejects noise", not _good_text("|| , .") and _good_text("Alice Olin"))


def test_input_source(tmp=None):
    check("is_url detects http", is_url("https://x/y") and not is_url("C:/films"))
    check("label from player url", _label_from_url("https://h/player.php?id=abc123") == "abc123")
    p = os.path.join(tempfile.mkdtemp(), "links.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("1162 https://a/player.php?id=x\n\n# comment\n1163 https://b/p?id=y\n")
    pairs = parse_links_file(p)
    check("links file parsed", pairs == [("1162", "https://a/player.php?id=x"),
                                         ("1163", "https://b/p?id=y")])


def test_slugify_safe():
    check("slugify blocks traversal", slugify("..") == "film" and ".." not in slugify("../etc"))
    check("slugify keeps normal names", slugify("My Film 2019") == "My_Film_2019")


def test_heuristic_structure():
    lines = [
        CreditLine(0.0, "Director: Jane Doe"),
        CreditLine(1.0, "CAST"),
        CreditLine(2.0, "John Smith"),
        CreditLine(3.0, "Producer - Bob Lee"),
    ]
    entries = heuristic_structure(lines)
    roles = {(e.role, e.name) for e in entries}
    check("director parsed", ("Director", "Jane Doe") in roles)
    check("cast header applied", ("Cast", "John Smith") in roles)
    check("dash separator parsed", ("Producer", "Bob Lee") in roles)


def test_title_mapping():
    if len(load_titles()) < 20:
        print("[SKIP] title mapping (end_credits_titles.txt missing)")
        return
    check("exact swedish-side match", (map_role("A-foto") or "").startswith("A-foto /"))
    check("fuzzy plural match", map_role("Statister") == "Statist / Extra")
    check("english-side match", (map_role("Editor") or "").startswith("Klipp /"))
    check("no false A->B match", map_role("Zzqqx Nonsense") is None)
    # enforce_titles: canonical role replaces wording; unmappable is flagged
    entries = [
        CreditEntry(role="Statister", name="Aaro Salmela"),
        CreditEntry(role="Blergh", name="Nobody"),
    ]
    enforce_titles(entries)
    check("role mapped to swedish title", entries[0].role == "Statist")
    check("original role kept", entries[0].original_role == "Statister")
    check("unmappable flagged", entries[1].needs_check and entries[1].role == "Blergh")


def test_dedup():
    frames = [
        OcrFrame(0.0, ["Director Jane Doe"]),
        OcrFrame(1.0, ["Director Jane Doe"]),   # scrolled duplicate
        OcrFrame(2.0, ["Director Jane Doo"]),   # OCR noise, still a dup
        OcrFrame(3.0, ["Editor Sam Park"]),
    ]
    lines = dedup_lines(frames)
    check("dedup collapses repeats", len(lines) == 2)


def test_cue_merge():
    class Stub:
        def recognize(self, snip):
            return RecognitionResult(track=Track(
                title="Test Song", artist="The Stubs", album="Demo",
                isrc="USXXX0000001", label="Stub Records", score=0.93,
                recording_id="abc"))

    sample = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "samples", "clipA.mp4")
    if not os.path.isfile(sample):
        print("[SKIP] cue merge (samples/clipA.mp4 missing)")
        return
    # One detected music region -> exactly one cue spanning the whole region,
    # annotated with the recognised track's metadata.
    segs = [Segment(0.0, 40.0, "music")]
    cues = build_cuesheet(sample, segs, Stub(), tempfile.mkdtemp())
    check("one region -> one cue", len(cues) == 1)
    check("cue spans the region", abs(cues[0].start) < 0.01 and abs(cues[0].end - 40.0) < 0.01)
    check("cue carries metadata", cues[0].title == "Test Song" and cues[0].isrc == "USXXX0000001")
    out = write_cuesheet(cues, tempfile.mkdtemp())
    check("cuesheet writes csv+xlsx", len(out) == 2)


def test_needs_check():
    class Stub:
        def recognize(self, snip):
            return RecognitionResult(reason="no match")  # force unidentified

    sample = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "samples", "clipA.mp4")
    if not os.path.isfile(sample):
        print("[SKIP] needs_check (samples/clipA.mp4 missing)")
        return
    music = [Segment(0.0, 20.0, "music")]
    # Speech overlapping the music region -> music under dialogue -> flag.
    speech = [Segment(8.0, 14.0, "speech")]
    cues = build_cuesheet(sample, music, Stub(), tempfile.mkdtemp(), speech_segments=speech)
    check("overlap flags needs_check", len(cues) == 1 and cues[0].needs_check)

    # No overlapping speech -> not flagged.
    cues2 = build_cuesheet(sample, music, Stub(), tempfile.mkdtemp(),
                           speech_segments=[Segment(100.0, 110.0, "speech")])
    check("no overlap -> no flag", len(cues2) == 1 and not cues2[0].needs_check)


if __name__ == "__main__":
    test_timecode()
    test_loudness_eval()
    test_tsv_columns_and_filter()
    test_input_source()
    test_slugify_safe()
    test_heuristic_structure()
    test_title_mapping()
    test_dedup()
    test_cue_merge()
    test_needs_check()
    print(f"\n{passed} checks passed.")
