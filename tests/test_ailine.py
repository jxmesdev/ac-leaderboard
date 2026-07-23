import json
import math
import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from acl_core import ailine, trackmap


def make_fast_lane(path, count=360, radius=100.0, side_l=5.0, side_r=6.0,
                   version=7, extra_count=None, truncate=False):
    """Synthesize a circular-track fast_lane.ai in the Kunos v7 layout."""
    buf = struct.pack("<iiii", version, count, 0, count)
    for i in range(count):
        a = 2 * math.pi * i / count
        x, z = radius * math.cos(a), radius * math.sin(a)
        buf += struct.pack("<ffffi", x, 12.0, z, radius * a, i)
    buf += struct.pack("<i", count if extra_count is None else extra_count)
    for i in range(count):
        vals = [0.0] * 18
        vals[5], vals[6] = side_l, side_r
        buf += struct.pack("<18f", *vals)
    if truncate:
        buf = buf[:len(buf) // 2]
    with open(path, "wb") as f:
        f.write(buf)
    return path


class TestParse(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ai = os.path.join(self.dir, "fast_lane.ai")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_parses_circle(self):
        make_fast_lane(self.ai)
        ai = ailine.parse_fast_lane(self.ai)
        self.assertIsNotNone(ai)
        self.assertEqual(len(ai["x"]), 360)
        self.assertAlmostEqual(ai["x"][0], 100.0, places=3)
        self.assertAlmostEqual(ai["side_l"][7], 5.0, places=3)
        self.assertAlmostEqual(ai["side_r"][7], 6.0, places=3)

    def test_rejects_bad_version(self):
        make_fast_lane(self.ai, version=6)
        self.assertIsNone(ailine.parse_fast_lane(self.ai))

    def test_rejects_truncated(self):
        make_fast_lane(self.ai, truncate=True)
        self.assertIsNone(ailine.parse_fast_lane(self.ai))

    def test_rejects_extra_count_mismatch(self):
        make_fast_lane(self.ai, extra_count=99)
        self.assertIsNone(ailine.parse_fast_lane(self.ai))

    def test_rejects_unpopulated_sides(self):
        make_fast_lane(self.ai, side_l=0.0, side_r=0.0)
        self.assertIsNone(ailine.parse_fast_lane(self.ai))

    def test_missing_file(self):
        self.assertIsNone(ailine.parse_fast_lane(os.path.join(self.dir, "nope.ai")))


class TestEdges(unittest.TestCase):
    def test_circle_edges_have_correct_radii(self):
        d = tempfile.mkdtemp()
        try:
            ai = ailine.parse_fast_lane(make_fast_lane(os.path.join(d, "f.ai")))
            edges = ailine.build_edges(ai, step_m=3.0)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertIsNotNone(edges)
        # closed polylines
        self.assertEqual((edges["lx"][0], edges["lz"][0]),
                         (edges["lx"][-1], edges["lz"][-1]))
        # one edge offset by side_l=5, the other by side_r=6 -- opposite sides
        # of the radius-100 centerline (winding decides which is inner/outer).
        rl = sum(math.hypot(x, z) for x, z in zip(edges["lx"], edges["lz"])) / len(edges["lx"])
        rr = sum(math.hypot(x, z) for x, z in zip(edges["rx"], edges["rz"])) / len(edges["rx"])
        pair = sorted([round(rl), round(rr)])
        self.assertIn(pair, ([94, 105], [95, 106]))
        # ~3m spacing around a 628m circle -> on the order of 200 points
        self.assertTrue(150 < len(edges["lx"]) < 260, len(edges["lx"]))


class TestGrabEdges(unittest.TestCase):
    def test_grab_writes_json(self):
        root = tempfile.mkdtemp()
        data = tempfile.mkdtemp()
        try:
            ai_dir = os.path.join(root, "content", "tracks", "spa", "gp", "ai")
            os.makedirs(ai_dir)
            make_fast_lane(os.path.join(ai_dir, "fast_lane.ai"))
            got = trackmap.grab_edges(root, "spa", "gp", data)
            self.assertIsNotNone(got)
            rel, path = got
            self.assertEqual(rel, "trackmaps/spa__gp__edges.json")
            edges = json.load(open(path))
            for k in ("lx", "lz", "rx", "rz"):
                self.assertIn(k, edges)
                self.assertEqual(len(edges[k]), len(edges["lx"]))
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(data, ignore_errors=True)

    def test_grab_missing_returns_none(self):
        data = tempfile.mkdtemp()
        try:
            self.assertIsNone(trackmap.grab_edges(tempfile.mkdtemp(), "x", "", data))
            self.assertIsNone(trackmap.grab_edges(None, "x", "", data))
        finally:
            shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
