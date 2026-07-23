"""Unit tests for the telemetry recorder (no AC needed)."""

import json
import os
import shutil
import sys
import tempfile
import unittest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

from acl_core import telemetry
from acl_core.telemetry import LapRecorder, slug, telemetry_filename


class SlugTests(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(slug("Spa"), "spa")
        self.assertEqual(slug("Ferrari 488 GT3"), "ferrari_488_gt3")
        self.assertEqual(slug("  A/B:C  "), "a_b_c")
        self.assertEqual(slug(""), "")

    def test_filename(self):
        self.assertEqual(
            telemetry_filename("spa", "", "ferrari_488_gt3", "James"),
            "spa____ferrari_488_gt3__james.json")

    def test_filename_time_suffix(self):
        self.assertEqual(
            telemetry_filename("spa", "", "ferrari_488_gt3", "James", 128456),
            "spa____ferrari_488_gt3__james__128456.json")
        self.assertEqual(
            telemetry_filename("spa", "", "ferrari_488_gt3", "James", 128456.0),
            "spa____ferrari_488_gt3__james__128456.json")
        # No time -> legacy name (old records reference these verbatim).
        self.assertEqual(
            telemetry_filename("spa", "", "ferrari_488_gt3", "James", None),
            "spa____ferrari_488_gt3__james.json")


def _drive_lap(rec, seconds, fps=60.0, base_x=0.0):
    """Feed a synthetic lap: nsp 0->~1 with plausible channel values."""
    dt = 1.0 / fps
    frames = int(seconds * fps)
    for i in range(frames):
        frac = i / float(frames)
        nsp = min(frac, 0.9999)
        # a fake oval: x,z trace a loop
        import math
        x = base_x + 100.0 * math.cos(frac * 2 * math.pi)
        z = 100.0 * math.sin(frac * 2 * math.pi)
        gas = 1.0 if (i % 100) < 70 else 0.0
        brake = 0.0 if gas > 0 else 0.8
        speed = 180.0 if gas > 0 else 90.0
        gear = 4
        steer = 0.2 * math.sin(frac * 8 * math.pi)  # radians
        rec.tick(dt, nsp, gas, brake, speed, gear, steer, x, z)


class RecorderTests(unittest.TestCase):
    def test_lap_finalizes_on_wrap(self):
        rec = LapRecorder(hz=30)
        _drive_lap(rec, seconds=6.0)
        self.assertIsNone(rec.last_lap)      # not finalized until S/F crossing
        rec.tick(1 / 60.0, 0.0, 1.0, 0.0, 180.0, 4, 0.0, 100.0, 0.0)  # wrap
        lap = rec.last_lap
        self.assertIsNotNone(lap)
        # ~30 Hz over 6 s -> ~180 samples
        self.assertTrue(170 <= len(lap["nsp"]) <= 185, len(lap["nsp"]))
        # all channel arrays are the same length
        n = len(lap["nsp"])
        for c in telemetry.CHANNELS:
            self.assertEqual(len(lap[c]), n, c)
        self.assertGreater(lap["_len_m"], 0)
        self.assertTrue(5500 <= lap["_dur_ms"] <= 6500, lap["_dur_ms"])
        # values are in expected ranges/types
        self.assertTrue(all(0 <= v <= 100 for v in lap["thr"]))
        self.assertTrue(all(isinstance(v, int) for v in lap["gear"]))
        self.assertTrue(max(lap["nsp"]) <= 1.0)

    def test_reset_clears(self):
        rec = LapRecorder(hz=30)
        _drive_lap(rec, seconds=2.0)
        rec.reset()
        self.assertIsNone(rec.last_lap)
        self.assertEqual(rec._cur["nsp"], [])

    def test_take_last_lap_clears(self):
        rec = LapRecorder(hz=30)
        _drive_lap(rec, seconds=3.0)
        rec.tick(1 / 60.0, 0.0, 1.0, 0.0, 180.0, 4, 0.0, 100.0, 0.0)
        self.assertIsNotNone(rec.take_last_lap())
        self.assertIsNone(rec.take_last_lap())   # cleared


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tel_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_build_and_write_roundtrip(self):
        rec = LapRecorder(hz=30)
        _drive_lap(rec, seconds=4.0)
        rec.tick(1 / 60.0, 0.0, 1.0, 0.0, 180.0, 4, 0.0, 100.0, 0.0)
        lap = rec.take_last_lap()
        payload = telemetry.build_payload(lap, "spa", "", "ferrari_488_gt3",
                                          "James", 128456, "2026-07-22T00:00:00Z", 30)
        relpath = telemetry.write_telemetry(self.dir, payload)
        # write_telemetry always keys the file by the payload's time_ms.
        self.assertEqual(relpath,
                         "telemetry/spa____ferrari_488_gt3__james__128456.json")
        full = os.path.join(self.dir, relpath)
        self.assertTrue(os.path.isfile(full))
        loaded = json.load(open(full))
        self.assertEqual(loaded["driver"], "James")
        self.assertEqual(loaded["time_ms"], 128456)
        self.assertEqual(loaded["n"], len(loaded["nsp"]))
        for c in telemetry.CHANNELS:
            self.assertIn(c, loaded)


if __name__ == "__main__":
    unittest.main(verbosity=2)
