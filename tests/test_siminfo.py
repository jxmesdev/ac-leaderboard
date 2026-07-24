"""Unit tests for the shared-memory conditions reader (no AC needed)."""

import ctypes
import os
import sys
import unittest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

from acl_core import siminfo


class TestSimInfo(unittest.TestCase):
    def test_never_raises_off_rig(self):
        # No AC shared memory here (and on macOS the mmap tag arg is not
        # even valid) -- must return None, never raise.
        self.assertIsNone(siminfo.read_conditions())

    def test_struct_layouts_match_ac(self):
        # Physics offsets are platform-independent (no wchar fields before
        # the temps); a drifted field order would silently read garbage on
        # the rig. Expected values derive from the community sim_info.py
        # (pack=4): airTemp at 288, roadTemp at 292, sizeof 296.
        self.assertEqual(_off(siminfo._PhysicsHead, "airTemp"), 288)
        self.assertEqual(_off(siminfo._PhysicsHead, "roadTemp"), 292)
        self.assertEqual(ctypes.sizeof(siminfo._PhysicsHead), 296)
        # Graphics offsets shift with wchar size (2 on Windows, 4 here),
        # so pin the TAIL layout instead: ...surfaceGrip, mandatoryPitDone,
        # windSpeed, windDirection ends the struct.
        size = ctypes.sizeof(siminfo._Graphics)
        self.assertEqual(_off(siminfo._Graphics, "windDirection"), size - 4)
        self.assertEqual(_off(siminfo._Graphics, "windSpeed"), size - 8)
        self.assertEqual(_off(siminfo._Graphics, "mandatoryPitDone"), size - 12)
        self.assertEqual(_off(siminfo._Graphics, "surfaceGrip"), size - 16)

    def test_dead_page_treated_as_unavailable(self):
        ph = siminfo._PhysicsHead()          # all zeros
        gr = siminfo._Graphics()
        orig = siminfo._read_page
        try:
            siminfo._read_page = lambda tag, cls: \
                ph if cls is siminfo._PhysicsHead else gr
            self.assertIsNone(siminfo.read_conditions())
            ph.airTemp = 22.5
            ph.roadTemp = 31.25
            gr.surfaceGrip = 0.98
            gr.windSpeed = 11.96
            gr.windDirection = 210.4
            out = siminfo.read_conditions()
            self.assertEqual(out, {"air": 22.5, "road": 31.2, "grip": 0.98,
                                   "wind_kmh": 12.0, "wind_deg": 210})
        finally:
            siminfo._read_page = orig


def _off(cls, field):
    return getattr(cls, field).offset


if __name__ == "__main__":
    unittest.main()
