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
from archivecheck.credits.structure import heuristic_structure  # noqa: E402
from archivecheck.report.cuesheet import build_cuesheet, write_cuesheet  # noqa: E402
from archivecheck.audio.segment import Segment  # noqa: E402
from archivecheck.audio.recognize import RecognitionResult, Track  # noqa: E402

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
    test_slugify_safe()
    test_heuristic_structure()
    test_dedup()
    test_cue_merge()
    test_needs_check()
    print(f"\n{passed} checks passed.")
