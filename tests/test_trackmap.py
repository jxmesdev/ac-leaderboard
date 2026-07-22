"""Unit tests for the track-map grabber (fake AC install, no AC needed)."""

import io
import os
import shutil
import sys
import tempfile
import unittest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

from acl_core import trackmap

MAP_INI = ("[PARAMETERS]\nWIDTH=500\nHEIGHT=400\nMARGIN=20\n"
           "SCALE_FACTOR=0.5\nX_OFFSET=250\nZ_OFFSET=200\nDRAWING_SIZE=600\n")


def _write(path, text):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TrackMapTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="actrack_")
        self.ac = os.path.join(self.root, "assettocorsa")
        self.app_dir = os.path.join(self.ac, "apps", "python", "ac_leaderboard")
        os.makedirs(self.app_dir)
        # multi-layout track: ks_brands_hatch/indy/
        tb = os.path.join(self.ac, "content", "tracks", "ks_brands_hatch", "indy")
        _write(os.path.join(tb, "map.png"), "PNGDATA-brands-indy")
        _write(os.path.join(tb, "data", "map.ini"), MAP_INI)
        # single-layout track: ks_monza/
        tm = os.path.join(self.ac, "content", "tracks", "ks_monza")
        _write(os.path.join(tm, "map.png"), "PNGDATA-monza")
        _write(os.path.join(tm, "data", "map.ini"), MAP_INI)
        self.data = tempfile.mkdtemp(prefix="acdata_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)

    def test_find_ac_root(self):
        self.assertEqual(trackmap.find_ac_root(self.app_dir), self.ac)

    def test_find_ac_root_bad(self):
        self.assertIsNone(trackmap.find_ac_root("/nope/apps/python/x"))

    def test_parse_map_ini(self):
        p = trackmap.parse_map_ini(
            os.path.join(self.ac, "content", "tracks", "ks_monza", "data", "map.ini"))
        self.assertEqual(p["scale"], 0.5)
        self.assertEqual(p["xoff"], 250.0)
        self.assertEqual(p["zoff"], 200.0)
        self.assertEqual(p["width"], 500.0)

    def test_grab_multilayout(self):
        res = trackmap.grab(self.ac, "ks_brands_hatch", "indy", self.data)
        self.assertIsNotNone(res)
        tm, dst = res
        self.assertEqual(tm["url"], "trackmaps/ks_brands_hatch__indy.png")
        self.assertEqual(tm["scale"], 0.5)
        self.assertEqual(tm["xoff"], 250.0)
        self.assertTrue(os.path.isfile(dst))
        self.assertEqual(io.open(dst).read(), "PNGDATA-brands-indy")

    def test_grab_singlelayout(self):
        res = trackmap.grab(self.ac, "ks_monza", "", self.data)
        self.assertIsNotNone(res)
        tm, dst = res
        self.assertEqual(tm["url"], "trackmaps/ks_monza__.png")
        self.assertEqual(io.open(dst).read(), "PNGDATA-monza")

    def test_grab_missing(self):
        self.assertIsNone(trackmap.grab(self.ac, "no_such_track", "", self.data))

    def test_grab_no_root(self):
        self.assertIsNone(trackmap.grab(None, "ks_monza", "", self.data))


if __name__ == "__main__":
    unittest.main(verbosity=2)
