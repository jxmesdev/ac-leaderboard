"""Unit tests for the AC AI-line parser and the edge geometry it builds.

The second half drives ailine against COMPLETE fast_lane.ai images assembled
byte by byte with struct, from layout constants transcribed from the AiSpline
v7 format spec rather than from ailine.py. That duplication is the point: a
drifted offset, stride or field index in the parser fails here even though the
module stays perfectly self-consistent, and every documented way a real file
goes wrong (the missing extraCount int32, the AssettoServer v-1 traffic
variant, a .aip ZIP, a lying header) can be built and refused without an AC
install.

The circle fixture exists so the answer can be computed by hand: for a
constant-width circular track every stage of build_edges is exact, so the
tests assert specific coordinates, not merely that something parsed.
"""

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


def make_apex_hugging_ai(n=2000, R=100.0, half_w=5.5, left_is_outer=True):
    """Racing line on a circle that hugs the inside through 'corners' --
    the physical behaviour detect_left_sign votes on. CCW travel, so the
    driver's-left (up x forward) direction points OUTWARD."""
    xs, zs, sl, sr = [], [], [], []
    for i in range(n):
        a = 2 * math.pi * i / n
        hug = -2.0 - 1.5 * abs(math.sin(4 * a))   # always inside of centre
        r = R + hug
        xs.append(r * math.cos(a))
        zs.append(r * math.sin(a))
        outer, inner = (R + half_w) - r, r - (R - half_w)
        if left_is_outer:
            sl.append(outer)
            sr.append(inner)
        else:
            sl.append(inner)
            sr.append(outer)
    return {"x": xs, "z": zs, "side_l": sl, "side_r": sr}


class TestSignDetection(unittest.TestCase):
    def test_detects_left_outward_labeling(self):
        ai = make_apex_hugging_ai(left_is_outer=True)
        # CCW: driver's left = outward = (tz, -tx) = sign -1 in our lat basis
        self.assertEqual(ailine.detect_left_sign(ai), -1)

    def test_detects_flipped_labeling(self):
        ai = make_apex_hugging_ai(left_is_outer=False)
        self.assertEqual(ailine.detect_left_sign(ai), 1)

    def test_band_correct_under_both_labelings(self):
        # Whatever the file's labeling, the band must land on the true track.
        for flag in (True, False):
            ai = make_apex_hugging_ai(left_is_outer=flag)
            e = ailine.build_edges(ai)
            radii = sorted([
                sum(math.hypot(x, z) for x, z in zip(e["lx"], e["lz"])) / len(e["lx"]),
                sum(math.hypot(x, z) for x, z in zip(e["rx"], e["rz"])) / len(e["rx"]),
            ])
            self.assertAlmostEqual(radii[0], 94.5, delta=0.6)
            self.assertAlmostEqual(radii[1], 105.5, delta=0.6)


class TestInvalidSideGaps(unittest.TestCase):
    def test_zeroed_runs_do_not_pinch_the_band(self):
        ai = make_apex_hugging_ai()
        n = len(ai["x"])
        # zero out ~30% of samples in runs (the parser's invalid sentinel)
        for start in range(0, n, 200):
            for i in range(start, min(start + 60, n)):
                ai["side_l"][i] = 0.0
                ai["side_r"][i] = 0.0
        e = ailine.build_edges(ai)
        self.assertIsNotNone(e)
        # band half-width must stay near 5.5m everywhere -- never pinched
        m = min(len(e["lx"]), len(e["rx"]))
        widths = [math.hypot(e["lx"][k]-e["rx"][k], e["lz"][k]-e["rz"][k]) / 2.0
                  for k in range(m)]
        self.assertGreater(min(widths), 4.5, "band pinched to %.2f m" % min(widths))
        self.assertLess(max(widths), 6.5)
        radii = sorted([
            sum(math.hypot(x, z) for x, z in zip(e["lx"], e["lz"])) / len(e["lx"]),
            sum(math.hypot(x, z) for x, z in zip(e["rx"], e["rz"])) / len(e["rx"]),
        ])
        self.assertAlmostEqual(radii[0], 94.5, delta=0.7)
        self.assertAlmostEqual(radii[1], 105.5, delta=0.7)


class TestDecimation(unittest.TestCase):
    def test_dense_spline_is_thinned_and_fast(self):
        import time
        ai = make_apex_hugging_ai(n=60000)   # ~1cm spacing: pathological
        t0 = time.time()
        e = ailine.build_edges(ai)
        took = time.time() - t0
        self.assertIsNotNone(e)
        self.assertLess(took, 5.0, "build_edges too slow: %.1fs" % took)
        radii = sorted([
            sum(math.hypot(x, z) for x, z in zip(e["lx"], e["lz"])) / len(e["lx"]),
            sum(math.hypot(x, z) for x, z in zip(e["rx"], e["rz"])) / len(e["rx"]),
        ])
        self.assertAlmostEqual(radii[0], 94.5, delta=0.6)
        self.assertAlmostEqual(radii[1], 105.5, delta=0.6)


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
            with open(path) as f:
                edges = json.load(f)
            for k in ("lx", "lz", "rx", "rz"):
                self.assertIn(k, edges)
                self.assertEqual(len(edges[k]), len(edges["lx"]))
            # The written file must satisfy the publisher's own regeneration
            # gate (stored ver >= ailine.EDGES_VER in ac_leaderboard.py), or
            # every session would rebuild the same track forever.
            self.assertEqual(edges["ver"], ailine.EDGES_VER)
            self.assertEqual(edges["src"], "ai")
            # ver 4 is the elevation-aware build: the synthetic circle sits at
            # y = 12 with no usable normals, so heights are present and level
            # and the band says so ("flat" = elevation known, cross-slope not).
            self.assertEqual(ailine.EDGES_VER, 4)
            self.assertEqual(edges["bank"], "flat")
            for k in ("ly", "ry"):
                self.assertEqual(len(edges[k]), len(edges["lx"]))
                self.assertAlmostEqual(min(edges[k]), 12.0, delta=0.01)
                self.assertAlmostEqual(max(edges[k]), 12.0, delta=0.01)
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


# =========================================================================
# Whole-file tests: synthesised fast_lane.ai images through parse_ai_line
# =========================================================================

# -- the AiSpline v7 layout, transcribed from the format spec --------------
# Little-endian throughout, no padding anywhere (every member is 4 bytes).
#
#   header  16 bytes : int32 version(=7), pointCount, lapTime, sampleCount
#   points  20 bytes each : float32 x, y, z, length ; int32 id
#   int32   extraCount -- MUST equal pointCount
#   extras  72 bytes each : 18 float32
#   tail    optional int32 hasGrid + a spatial lookup grid
#
# lapTime/sampleCount are a zero hole in practice (CSP writes an int64 0 over
# both), so sampleCount is NOT a usable cross-check on pointCount -- these
# fixtures deliberately vary it.
V7 = 7
HEADER_FMT = "<iiii"
POINT_FMT = "<ffffi"
EXTRA_FMT = "<18f"
HEADER_SIZE = 16
POINT_SIZE = 20
EXTRA_SIZE = 72

# Field indices within the 18-float extra record. SIDE_LEFT is index 5, i.e.
# byte +20 within the record, and SIDE_RIGHT index 6 (+24). Their neighbours
# are named because the classic parsing bug lands on them: skip the
# extraCount int32 and index 5 reads `radius`, which is 1000+ on a straight.
E_SPEED, E_GAS, E_BRAKE, E_OBSOLETE_LATG, E_RADIUS = 0, 1, 2, 3, 4
E_SIDE_LEFT, E_SIDE_RIGHT = 5, 6
E_CAMBER, E_DIRECTION, E_NORMAL_X = 7, 8, 9
E_LENGTH, E_FORWARD_X, E_TAG, E_GRADE = 12, 13, 16, 17

# The strides the fixtures rely on. A hand-rolled offset would drift silently.
assert struct.calcsize(HEADER_FMT) == HEADER_SIZE
assert struct.calcsize(POINT_FMT) == POINT_SIZE
assert struct.calcsize(EXTRA_FMT) == EXTRA_SIZE
assert E_SIDE_LEFT * 4 == 20 and E_SIDE_RIGHT * 4 == 24


def make_extra(side_l, side_r, normal=(0.0, 1.0, 0.0)):
    """One 18-float extra record with plausible junk in every other column.

    The neighbours are filled with DISTINCTIVE values, not zeros: a parser
    reading one slot early or late would then pick up 1000.0 (radius) or 0.35
    (camber) instead of a side distance, and the tests below would see it.
    The same trap is set around the normal: `camber` and `direction` sit
    immediately before it and `length` immediately after, all non-zero.
    """
    vals = [0.0] * 18
    vals[E_SPEED] = 61.5
    vals[E_GAS] = 1.0
    vals[E_BRAKE] = 0.0
    vals[E_OBSOLETE_LATG] = 0.0
    vals[E_RADIUS] = 1000.0
    vals[E_SIDE_LEFT] = side_l
    vals[E_SIDE_RIGHT] = side_r
    vals[E_CAMBER] = 0.35
    vals[E_DIRECTION] = 1.0
    vals[E_NORMAL_X] = normal[0]
    vals[E_NORMAL_X + 1] = normal[1]    # normal.y ~ +1 on flat track
    vals[E_NORMAL_X + 2] = normal[2]
    vals[E_LENGTH] = 0.75
    vals[E_FORWARD_X] = 1.0
    vals[E_TAG] = 0.0
    vals[E_GRADE] = 0.0
    return vals


def pack_ai(points, sides, version=V7, count=None, extra_count=None,
            omit_extra_count=False, ids=None, extras=None, grid=False,
            sample_count=0, truncate=None, normals=None):
    """Assemble a complete fast_lane.ai image from the layout above.

    `points` is [(x, y, z), ...] in AC world metres (Y up) and `sides` the
    matching [(side_l, side_r), ...]. Every keyword builds one specific
    real-world malformation:

      version           a format that never carried side data (6, or -1)
      count             a header that LIES about how many points follow
      extra_count       the extras counter disagreeing with the header
      omit_extra_count  the missing int32 -- the single most common
                        third-party bug, which shifts every extra field by one
      ids               a non-sequential id column (CSP's `payloadIndex`)
      extras            hand-built extra records, for column-level checks
      grid              the optional lookup-grid tail, so trailing bytes past
                        the extras are exercised as NORMAL rather than damage
      truncate          keep only this many bytes
      normals           per-point surface normals, one (nx, ny, nz) each;
                        default is straight up, i.e. no cross-slope
    """
    n = len(points)
    buf = struct.pack(HEADER_FMT, version, n if count is None else count,
                      0, sample_count)
    for i, (x, y, z) in enumerate(points):
        pid = i if ids is None else ids[i]
        # The 4th float is cumulative arc length; nothing reads it, but a real
        # file has it, so the fixture does too.
        buf += struct.pack(POINT_FMT, x, y, z, float(i), pid)
    if not omit_extra_count:
        buf += struct.pack("<i", n if extra_count is None else extra_count)
    if extras is not None:
        rows = extras
    elif normals is not None:
        rows = [make_extra(sl, sr, normals[i])
                for i, (sl, sr) in enumerate(sides)]
    else:
        rows = [make_extra(sl, sr) for (sl, sr) in sides]
    for vals in rows:
        buf += struct.pack(EXTRA_FMT, *vals)
    if grid:
        # hasGrid = 0: the minimal legal tail, and enough to prove trailing
        # bytes are tolerated.
        buf += struct.pack("<i", 0)
    if truncate is not None:
        buf = buf[:truncate]
    return buf


def circle_points(n=360, radius=100.0, y=12.0):
    """A CCW circle in the X/Z plane. AC world is Y-up and the track lies in
    X/Z, so the elevation is a constant that must not reach the output."""
    return [(radius * math.cos(2 * math.pi * i / n), y,
             radius * math.sin(2 * math.pi * i / n)) for i in range(n)]


def apex_track(n=1200, R=120.0, half_w=6.0, left_is_outer=True):
    """A circular track of half-width `half_w` whose AI line hugs the inside.

    The apex-hugging is the physical invariant the sign detector votes on, and
    `left_is_outer` flips which column the file calls SIDE_LEFT -- the very
    thing AcTools and CSP disagree about. The TRUE track is the same annulus
    either way, so the built band must be too.
    """
    pts, sides = [], []
    for i in range(n):
        a = 2 * math.pi * i / n
        r = R - 1.5 - 2.0 * abs(math.sin(3 * a))    # always inside centre
        pts.append((r * math.cos(a), 5.0, r * math.sin(a)))
        outer, inner = (R + half_w) - r, r - (R - half_w)
        sides.append((outer, inner) if left_is_outer else (inner, outer))
    return pts, sides


def driven_lap(n=800, R=120.0, weave=3.5):
    """A recorded lap on the apex_track above -- a DIFFERENT line from the AI
    line, which is the whole point. The racing line lies between the
    boundaries under BOTH signs, so it proves nothing; a real lap does not."""
    return [((R + weave * math.sin(7 * a)) * math.cos(a),
             (R + weave * math.sin(7 * a)) * math.sin(a))
            for a in [2 * math.pi * i / n for i in range(n)]]


def _inside(px, pz, xs, zs):
    """Ray casting: is (px, pz) inside the closed polygon xs/zs?"""
    hit = False
    for i in range(len(xs)):
        j = i - 1
        if (zs[i] > pz) != (zs[j] > pz):
            cross = xs[i] + (pz - zs[i]) * (xs[j] - xs[i]) / (zs[j] - zs[i])
            if px < cross:
                hit = not hit
    return hit


def _ring_area(xs, zs):
    s = 0.0
    for i in range(len(xs)):
        j = (i + 1) % len(xs)
        s += xs[i] * zs[j] - xs[j] * zs[i]
    return abs(s) / 2.0


def in_band(band, px, pz):
    """Is the point on the track -- i.e. between the two boundaries?

    The band is an annulus, so containment is "inside the larger ring and
    outside the smaller". Which of lx/rx is the outer one depends on the
    track's winding and on the file's labelling, so it is decided by area
    rather than assumed.
    """
    if _ring_area(band["lx"], band["lz"]) >= _ring_area(band["rx"], band["rz"]):
        outer, inner = ("lx", "lz"), ("rx", "rz")
    else:
        outer, inner = ("rx", "rz"), ("lx", "lz")
    return (_inside(px, pz, band[outer[0]], band[outer[1]])
            and not _inside(px, pz, band[inner[0]], band[inner[1]]))


class TestKnownGeometry(unittest.TestCase):
    """A constant-width circular track is the one case where every stage of
    build_edges is exact, so the expected coordinates can be derived on paper.

    R = 100 m CCW circle, side_l = 5 m, side_r = 6 m at every point. At point
    0 the AI line is at (100, 0) travelling +Z, so the unit tangent is (0, 1)
    and the parser's lateral basis is lat = sign * (-tz, tx) = sign * (-1, 0).
    side_l is the SMALLER gap and the circle turns toward the (-tz, tx) side,
    so SIDE_LEFT is the inside one: sign = +1 and lat = (-1, 0), pointing at
    the circle's centre. Then

        centreline = P + lat * (side_l - side_r) / 2 = (100.5, 0)
        half width = (side_l + side_r) / 2            = 5.5
        left edge  = centre + lat * w                 = ( 95.0, 0)
        right edge = centre - lat * w                 = (106.0, 0)

    -- the left edge 5 m inside the AI line and the right edge 6 m outside it,
    which is exactly what the file says. The closing Laplacian smoothing pulls
    a discretised circle in by <0.1 m, which is what the deltas allow for.
    """

    def setUp(self):
        pts = circle_points()
        self.band = ailine.parse_ai_line(
            pack_ai(pts, [(5.0, 6.0)] * len(pts)))
        self.assertIsNotNone(self.band, "well-formed v7 file must parse")

    def test_start_point_is_where_it_was_computed_to_be(self):
        self.assertAlmostEqual(self.band["lx"][0], 95.0, delta=0.15)
        self.assertAlmostEqual(self.band["rx"][0], 106.0, delta=0.15)
        # Point 0 sits on the X axis and the fixture is symmetric about it, so
        # both Z coordinates are exactly zero -- no tolerance needed.
        self.assertEqual(self.band["lz"][0], 0.0)
        self.assertEqual(self.band["rz"][0], 0.0)

    def test_both_edges_hold_their_radius_all_the_way_round(self):
        for key, want in (("l", 95.0), ("r", 106.0)):
            radii = [math.hypot(x, z) for x, z in
                     zip(self.band[key + "x"], self.band[key + "z"])]
            self.assertAlmostEqual(min(radii), want, delta=0.15)
            self.assertAlmostEqual(max(radii), want, delta=0.15)

    def test_track_width_is_side_l_plus_side_r(self):
        widths = [math.hypot(self.band["lx"][i] - self.band["rx"][i],
                             self.band["lz"][i] - self.band["rz"][i])
                  for i in range(self.band["n"])]
        self.assertAlmostEqual(min(widths), 11.0, delta=0.1)
        self.assertAlmostEqual(max(widths), 11.0, delta=0.1)

    def test_length_is_the_centreline_not_the_racing_line(self):
        # The centreline sits at radius 100.5 (half a metre outside the AI
        # line, because side_r is 1 m longer than side_l), so the lap length
        # is 2*pi*100.5. The racing line's own 2*pi*100 would be the wrong
        # answer: track length is a property of the track, not of a line.
        self.assertAlmostEqual(self.band["length_m"], 2 * math.pi * 100.5,
                               delta=0.5)

    def test_polylines_are_closed_and_index_aligned(self):
        n = self.band["n"]
        for k in ("lx", "lz", "rx", "rz"):
            self.assertEqual(len(self.band[k]), n)
            self.assertEqual(self.band[k][0], self.band[k][-1])

    def test_elevation_never_reaches_the_PLAN_view(self):
        # AC world is Y-up and the track lies in X/Z, so a hilly circuit and a
        # flat one with the same plan must produce byte-identical lx/lz/rx/rz.
        # A parser that unpacked (x, z, y) -- a real mistake in one community
        # importer -- would fail this immediately. What must change is ly/ry,
        # and only ly/ry.
        n = 360
        hilly = [(x, 40.0 * math.sin(6 * math.pi * i / n), z)
                 for i, (x, _y, z) in enumerate(circle_points(n=n))]
        band = ailine.parse_ai_line(pack_ai(hilly, [(5.0, 6.0)] * n))
        self.assertIsNotNone(band)
        for k in ("lx", "lz", "rx", "rz"):
            self.assertEqual(band[k], self.band[k],
                             "%s changed when only the elevation did" % k)
        self.assertNotEqual(band["ly"], self.band["ly"])
        # The hills survive the smoothing. A 12 m moving average against a
        # 209 m wavelength (three humps round a 628 m circle) takes 0.6% off
        # the amplitude, so anything under a couple of per cent is the
        # discretisation and not a flattened circuit.
        for k in ("ly", "ry"):
            self.assertAlmostEqual(max(band[k]) - min(band[k]), 80.0,
                                   delta=2.0)

    def test_a_flat_track_gets_flat_edges_at_its_own_height(self):
        # circle_points sits at y = 12 and make_extra's normal points
        # straight up, so both edges are at 12 everywhere -- the elevation is
        # real and the cross-slope is genuinely zero.
        for k in ("ly", "ry"):
            self.assertEqual(len(self.band[k]), self.band["n"])
            self.assertAlmostEqual(min(self.band[k]), 12.0, delta=0.01)
            self.assertAlmostEqual(max(self.band[k]), 12.0, delta=0.01)
        # Normals present and usable, so this is a MEASURED zero, not a
        # missing column.
        self.assertEqual(self.band["bank"], "normal")


def banked_circle(n=360, radius=100.0, y=12.0, bank_deg=10.0):
    """The TestKnownGeometry circle, tilted by a constant angle with its
    OUTSIDE edge high -- an oval's banking, and the one banked case whose
    answer can be written down.

    The surface normal leans toward the circle's centre by `bank_deg`, so
    height rises by tan(bank_deg) per metre travelled outward. Returns
    (points, normals) for pack_ai.
    """
    b = math.radians(bank_deg)
    pts, normals = [], []
    for i in range(n):
        a = 2 * math.pi * i / n
        pts.append((radius * math.cos(a), y, radius * math.sin(a)))
        normals.append((-math.sin(b) * math.cos(a), math.cos(b),
                        -math.sin(b) * math.sin(a)))
    return pts, normals


class TestBankedGeometry(unittest.TestCase):
    """Edge HEIGHTS, on the one fixture where they can be derived on paper.

    Same R = 100 m circle as TestKnownGeometry, so the plan view is already
    known: the left edge lands 5 m INSIDE the AI line and the right edge 6 m
    OUTSIDE it. Bank it by 10 degrees with the outside high and the heights
    follow from that alone, because the surface is a plane through the AI
    line rising tan(10) = 0.1763 per metre outward:

        left  edge = y - side_l * tan(bank) = 12 - 5 * 0.1763 = 11.118
        right edge = y + side_r * tan(bank) = 12 + 6 * 0.1763 = 13.058

    Note what those two numbers are NOT: 12 -/+ 5.5 * tan(bank), which is
    what a build that offset both edges from the RACING line's height would
    give. The AI line here sits half a metre inside the centreline, and on a
    cross-slope half a metre of lateral offset is 9 cm of height -- three
    times the tolerance below. So this is also the test that the centreline's
    own height gets recovered before the edges are offset from it.
    """

    def setUp(self):
        pts, normals = banked_circle()
        self.band = ailine.parse_ai_line(
            pack_ai(pts, [(5.0, 6.0)] * len(pts), normals=normals))
        self.assertIsNotNone(self.band)
        self.tan = math.tan(math.radians(10.0))

    def test_each_edge_sits_at_its_own_computed_height(self):
        self.assertEqual(self.band["bank"], "normal")
        for k, want in (("ly", 12.0 - 5.0 * self.tan),
                        ("ry", 12.0 + 6.0 * self.tan)):
            self.assertAlmostEqual(min(self.band[k]), want, delta=0.03)
            self.assertAlmostEqual(max(self.band[k]), want, delta=0.03)

    def test_the_outside_edge_is_the_high_one(self):
        # The whole point, and the assertion a mirrored cross-slope fails.
        # lx is the inside edge here (radius 95 against the right edge's 106
        # -- TestKnownGeometry pins that), so ly must be BELOW ry.
        for i in range(self.band["n"]):
            self.assertLess(self.band["ly"][i], self.band["ry"][i])

    def test_negative_banking_swaps_the_high_edge(self):
        pts, normals = banked_circle(bank_deg=-10.0)
        band = ailine.parse_ai_line(
            pack_ai(pts, [(5.0, 6.0)] * len(pts), normals=normals))
        self.assertIsNotNone(band)
        for i in range(band["n"]):
            self.assertGreater(band["ly"][i], band["ry"][i])

    def test_the_drop_across_the_track_is_the_full_width_times_the_slope(self):
        # 11 m of track at 10 degrees is 1.94 m of drop -- the thing a flat
        # band renders as zero.
        for i in range(self.band["n"]):
            drop = self.band["ry"][i] - self.band["ly"][i]
            self.assertAlmostEqual(drop, 11.0 * self.tan, delta=0.05)

    def test_heights_are_closed_and_index_aligned_with_the_plan_view(self):
        n = self.band["n"]
        for k in ("ly", "ry"):
            self.assertEqual(len(self.band[k]), n)
            self.assertEqual(self.band[k][0], self.band[k][-1])

    def test_banking_does_not_disturb_the_plan_view(self):
        # The plan view of a banked circuit is the plan view of a flat one:
        # a cross-slope that leaked into lx/lz would narrow the band by
        # cos(bank) and nobody would see it as anything but a slightly thin
        # track.
        flat = ailine.parse_ai_line(
            pack_ai(circle_points(), [(5.0, 6.0)] * 360))
        for k in ("lx", "lz", "rx", "rz"):
            self.assertEqual(self.band[k], flat[k])


class TestNormalColumn(unittest.TestCase):
    """Which floats the cross-slope is read from, and when it is refused.

    Banking is optional in a way the side distances are not: no normals means
    flat cross-sections, never a missing band. But a MISREAD normal would tilt
    every corner by a plausible-looking wrong amount, so the column has to
    prove itself first.
    """

    def setUp(self):
        self.pts = circle_points(n=120)
        self.sides = [(5.0, 6.0)] * len(self.pts)

    def _decode(self, normals):
        return ailine.decode_v7(pack_ai(self.pts, self.sides, normals=normals))

    def test_normals_are_read_from_columns_9_10_11(self):
        # camber (0.35) and direction (1.0) sit immediately before, length
        # (0.75) immediately after: a parser off by one slot in either
        # direction picks up a value that is here and would fail.
        want = (0.2, 0.96, -0.1959)
        ai = self._decode([want] * len(self.pts))
        self.assertIsNotNone(ai)
        for i in range(len(self.pts)):
            self.assertAlmostEqual(ai["nx"][i], want[0], places=4)
            self.assertAlmostEqual(ai["ny"][i], want[1], places=4)
            self.assertAlmostEqual(ai["nz"][i], want[2], places=4)

    def test_elevation_is_decoded_even_with_no_normals(self):
        ai = self._decode([(0.0, 0.0, 0.0)] * len(self.pts))
        self.assertIsNotNone(ai)
        self.assertNotIn("nx", ai)
        self.assertEqual(len(ai["y"]), len(self.pts))
        self.assertAlmostEqual(ai["y"][0], 12.0, places=3)

    def test_an_unpopulated_normal_column_means_flat_not_missing(self):
        band = ailine.parse_ai_line(
            pack_ai(self.pts, self.sides,
                    normals=[(0.0, 0.0, 0.0)] * len(self.pts)))
        self.assertIsNotNone(band, "no normals must not cost the band")
        self.assertEqual(band["bank"], "flat")
        self.assertEqual(band["ly"], band["ry"])
        self.assertAlmostEqual(band["ly"][0], 12.0, delta=0.01)

    def test_a_column_that_is_not_unit_vectors_is_refused(self):
        # Half-length, double-length, and three unrelated floats: all say the
        # column is not what we think it is.
        for bad in ((0.0, 0.5, 0.0), (0.0, 2.0, 0.0), (61.5, 1000.0, 0.35)):
            ai = self._decode([bad] * len(self.pts))
            self.assertNotIn("nx", ai, "accepted %r as a surface normal" % (bad,))

    def test_a_normal_too_far_from_vertical_is_not_a_road(self):
        # 60 degrees is the floor. A wall's normal is a unit vector too, and
        # a wall in the normal column would tilt the band by a factor of two.
        wall = (math.sin(math.radians(75.0)), math.cos(math.radians(75.0)), 0.0)
        self.assertNotIn("nx", self._decode([wall] * len(self.pts)))
        # ...but real banking passes: Bristol is 36 degrees.
        ok = (math.sin(math.radians(36.0)), math.cos(math.radians(36.0)), 0.0)
        self.assertIn("nx", self._decode([ok] * len(self.pts)))

    def test_a_minority_of_good_normals_is_all_or_nothing(self):
        normals = [(0.0, 0.0, 0.0)] * len(self.pts)
        for i in range(0, len(normals), 4):
            normals[i] = (0.0, 1.0, 0.0)
        self.assertNotIn("nx", self._decode(normals))

    def test_a_few_bad_normals_are_interpolated_across(self):
        # The same treatment a few bad side samples get: a gap must not pull
        # the banking toward zero around it.
        b = math.radians(10.0)
        pts, normals = banked_circle(n=360)
        for i in (17, 18, 19, 200):
            normals[i] = (0.0, 0.0, 0.0)
        band = ailine.parse_ai_line(
            pack_ai(pts, [(5.0, 6.0)] * len(pts), normals=normals))
        self.assertIsNotNone(band)
        self.assertEqual(band["bank"], "normal")
        for i in range(band["n"]):
            self.assertAlmostEqual(band["ry"][i] - band["ly"][i],
                                   11.0 * math.tan(b), delta=0.05)

    def test_a_non_finite_normal_does_not_take_the_track_down(self):
        normals = [(0.0, 1.0, 0.0)] * len(self.pts)
        normals[3] = (float("nan"), float("inf"), 0.0)
        ai = self._decode(normals)
        self.assertIsNotNone(ai)
        self.assertIn("nx", ai)
        self.assertEqual(ai["ny"][3], 0.0)      # the invalid sentinel

    def test_camber_is_deliberately_not_read(self):
        # make_extra writes camber = 0.35 into every record, which as a
        # radian tilt would be 20 degrees of banking. The band must stay flat:
        # a scalar with no documented sign convention is not something to
        # guess at.
        band = ailine.parse_ai_line(
            pack_ai(self.pts, self.sides,
                    normals=[(0.0, 0.0, 0.0)] * len(self.pts)))
        self.assertEqual(band["ly"], band["ry"])


class TestSplineWithoutElevation(unittest.TestCase):
    """Callers hand-build {x, z, side_l, side_r} dicts -- the sign detectors
    only ever needed those four. Heights are optional all the way through, and
    a dict with no y must still produce a band, silently."""

    def test_build_edges_on_a_dict_with_no_y(self):
        ai = make_apex_hugging_ai()
        self.assertNotIn("y", ai)
        e = ailine.build_edges(ai)
        self.assertIsNotNone(e)
        for k in ("ly", "ry", "bank"):
            self.assertNotIn(k, e, "invented %s out of nothing" % k)


class TestSignConvention(unittest.TestCase):
    """The lateral sign is contested between AcTools and CSP, so ailine
    decides it per file from the data. These tests check the consequence that
    actually matters: the band lands on the real track either way, and a
    recorded lap falls BETWEEN the edges."""

    def _band(self, left_is_outer):
        pts, sides = apex_track(left_is_outer=left_is_outer)
        band = ailine.parse_ai_line(pack_ai(pts, sides))
        self.assertIsNotNone(band)
        return band

    def test_recorded_lap_falls_between_the_edges(self):
        lap = driven_lap()
        for left_is_outer in (True, False):
            band = self._band(left_is_outer)
            outside = [(x, z) for (x, z) in lap if not in_band(band, x, z)]
            self.assertEqual(
                outside, [],
                "%d of %d lap samples fell outside the band (left_is_outer=%s)"
                % (len(outside), len(lap), left_is_outer))

    def test_a_mirrored_band_would_fail_that_test(self):
        # The negative control. Without it, the test above could pass on a
        # band that was merely wide enough. Forcing the opposite sign doubles
        # the racing line's weave instead of cancelling it, and the same lap
        # then pokes out in hundreds of places.
        pts, sides = apex_track()
        raw = pack_ai(pts, sides)
        ai = ailine.decode_v7(raw)
        wrong = ailine._build_band(ai, -ailine.confirm_left_sign(ai))
        lap = driven_lap()
        outside = [1 for (x, z) in lap if not in_band(wrong, x, z)]
        self.assertGreater(len(outside), len(lap) // 4)

    def test_lx_really_is_the_side_l_side(self):
        # Not just "the band is right": the key names have to mean something,
        # because the viewer draws its start line lx[0] -> rx[0].
        outer_named_left = self._band(left_is_outer=True)
        outer_named_right = self._band(left_is_outer=False)
        rad = lambda b, k: (sum(math.hypot(x, z) for x, z in
                                zip(b[k + "x"], b[k + "z"])) / b["n"])
        self.assertGreater(rad(outer_named_left, "l"),
                           rad(outer_named_left, "r"))
        self.assertLess(rad(outer_named_right, "l"),
                        rad(outer_named_right, "r"))
        # ...and the two describe the SAME annulus, ~114 m to ~126 m.
        for band in (outer_named_left, outer_named_right):
            radii = sorted([rad(band, "l"), rad(band, "r")])
            self.assertAlmostEqual(radii[0], 114.0, delta=0.2)
            self.assertAlmostEqual(radii[1], 126.0, delta=0.2)


class TestSideColumns(unittest.TestCase):
    def test_sides_are_read_from_offsets_20_and_24(self):
        # Every other column in the record carries a distinctive value, so a
        # parser reading one slot early would return radius (1000.0) and one
        # slot late would return camber (0.35).
        pts = circle_points(n=64)
        ai = ailine.decode_v7(pack_ai(pts, [(4.25, 7.75)] * len(pts)))
        self.assertIsNotNone(ai)
        for i in range(len(pts)):
            self.assertAlmostEqual(ai["side_l"][i], 4.25, places=4)
            self.assertAlmostEqual(ai["side_r"][i], 7.75, places=4)

    def test_sample_count_is_not_a_cross_check(self):
        # CSP writes zeros over lapTime/sampleCount, so a file whose
        # sampleCount disagrees with pointCount is perfectly normal.
        pts = circle_points()
        sides = [(5.0, 6.0)] * len(pts)
        for sc in (0, len(pts), 12345):
            self.assertIsNotNone(
                ailine.parse_ai_line(pack_ai(pts, sides, sample_count=sc)),
                "sampleCount=%d must not affect the parse" % sc)


class TestRejections(unittest.TestCase):
    """Every one of these is a file that exists in the wild, or a bug a
    third-party writer really has. None may raise, and none may produce
    geometry -- fabricated edges are worse than no edges."""

    def setUp(self):
        self.pts = circle_points()
        self.sides = [(5.0, 6.0)] * len(self.pts)

    def _raw(self, **kw):
        return pack_ai(self.pts, self.sides, **kw)

    def test_version_6_is_refused(self):
        self.assertIsNone(ailine.parse_ai_line(self._raw(version=6)))

    def test_traffic_spline_version_minus_one_has_no_side_data(self):
        # AssettoServer's variant: int32 -1, int32 count, then 20-byte records
        # of {vec3 position, float radius, float camber} and the file ends.
        # The record is coincidentally 20 bytes too, so a parser that skipped
        # the version check would read plausible-looking garbage.
        buf = struct.pack("<ii", -1, len(self.pts))
        for (x, y, z) in self.pts:
            buf += struct.pack("<fffff", x, y, z, 250.0, 0.0)
        self.assertIsNone(ailine.parse_ai_line(buf))

    def test_aip_zip_container_is_refused(self):
        # fast_lane.aip is a ZIP of .ai entries, not a version. Its PK\x03\x04
        # magic reads as version 0x04034b50, which the version check catches.
        self.assertIsNone(ailine.parse_ai_line(b"PK\x03\x04" + b"\x00" * 4096))

    def test_file_with_no_extras_block_at_all(self):
        # Header and points, then nothing: no extraCount, no side distances.
        buf = struct.pack(HEADER_FMT, V7, len(self.pts), 0, 0)
        for i, (x, y, z) in enumerate(self.pts):
            buf += struct.pack(POINT_FMT, x, y, z, float(i), i)
        self.assertIsNone(ailine.parse_ai_line(buf))

    def test_truncated_midway_through_the_extras(self):
        whole = self._raw()
        self.assertIsNone(ailine.parse_ai_line(whole[:len(whole) // 2]))
        self.assertIsNone(ailine.parse_ai_line(whole[:HEADER_SIZE + 4]))
        self.assertIsNone(ailine.parse_ai_line(b""))
        self.assertIsNone(ailine.parse_ai_line(None))

    def test_missing_extra_count_int32(self):
        # THE classic bug, from the writer's side: leave out the 4-byte
        # counter and every extra field shifts by one, so SIDE_LEFT reads
        # `radius`. It must not be read as "one extra record short".
        self.assertIsNone(ailine.parse_ai_line(self._raw(omit_extra_count=True)))

    def test_extra_count_disagreeing_with_point_count(self):
        for bad in (0, 1, len(self.pts) - 1, len(self.pts) + 1):
            self.assertIsNone(ailine.parse_ai_line(self._raw(extra_count=bad)))

    def test_header_lying_about_point_count(self):
        self.assertIsNone(ailine.parse_ai_line(self._raw(count=50000)))

    def test_empty_and_tiny_point_counts(self):
        self.assertIsNone(ailine.parse_ai_line(self._raw(count=0)))
        self.assertIsNone(ailine.parse_ai_line(
            struct.pack(HEADER_FMT, V7, 0, 0, 0)))
        tiny = circle_points(n=4)
        self.assertIsNone(ailine.parse_ai_line(
            pack_ai(tiny, [(5.0, 6.0)] * 4)))

    def test_non_finite_position(self):
        # struct hands back NaN/Inf from junk bytes without complaint, and NaN
        # propagates silently into the drawn polygon.
        for bad in (float("nan"), float("inf"), float("-inf")):
            pts = list(self.pts)
            pts[100] = (bad, 12.0, pts[100][2])
            self.assertIsNone(ailine.parse_ai_line(pack_ai(pts, self.sides)))
            pts[100] = (pts[100][0], 12.0, bad)
            self.assertIsNone(ailine.parse_ai_line(pack_ai(pts, self.sides)))

    def test_non_finite_side_distance(self):
        for bad in (float("nan"), float("inf")):
            sides = list(self.sides)
            sides[7] = (bad, 6.0)
            self.assertIsNone(ailine.parse_ai_line(pack_ai(self.pts, sides)))

    def test_absurd_track_width(self):
        # The off-by-four's signature: SIDE_LEFT reading the radius column.
        self.assertIsNone(ailine.parse_ai_line(
            pack_ai(self.pts, [(1000.0, 6.0)] * len(self.pts))))
        # ...and a width that is merely implausible rather than insane.
        self.assertIsNone(ailine.parse_ai_line(
            pack_ai(self.pts, [(40.0, 45.0)] * len(self.pts))))
        # Narrower than a car is wide: the side columns are junk.
        self.assertIsNone(ailine.parse_ai_line(
            pack_ai(self.pts, [(0.9, 1.1)] * len(self.pts))))

    def test_unpopulated_sides_are_a_clean_no(self):
        # The COMMON case, not a corruption: AC only merges the borders into
        # fast_lane.ai when the line was recorded with side_l/side_r present.
        self.assertIsNone(ailine.parse_ai_line(
            pack_ai(self.pts, [(0.0, 0.0)] * len(self.pts))))
        # A minority of populated samples is still a no.
        sides = [(0.0, 0.0)] * len(self.pts)
        for i in range(0, len(sides), 4):
            sides[i] = (5.0, 6.0)
        self.assertIsNone(ailine.parse_ai_line(pack_ai(self.pts, sides)))

    def test_symmetric_sides_refuse_rather_than_guess(self):
        # A line running exactly down the middle gives neither the apex vote
        # nor the smoothness test anything to work with. None costs the track
        # its outline; a guess would give it a MIRRORED one, which looks
        # plausible and is wrong at every apex.
        self.assertIsNone(ailine.parse_ai_line(
            pack_ai(self.pts, [(5.5, 5.5)] * len(self.pts))))

    def test_scrambled_point_ids(self):
        # CSP dereferences the id as an index into the extras; everyone else
        # pairs positionally. A genuine permutation is followed, but ids that
        # are not a permutation mean we are misreading the file, and
        # mis-paired side distances are invisible in the output.
        ids = list(range(len(self.pts)))
        ids[5] = 999999
        self.assertIsNone(ailine.parse_ai_line(pack_ai(self.pts, self.sides,
                                                       ids=ids)))
        ids = [0] * len(self.pts)
        self.assertIsNone(ailine.parse_ai_line(pack_ai(self.pts, self.sides,
                                                       ids=ids)))

    def test_random_junk_never_raises(self):
        import random
        rng = random.Random(20260804)
        for _ in range(200):
            n = rng.randrange(0, 4096)
            raw = bytes(bytearray(rng.randrange(256) for _ in range(n)))
            self.assertIsNone(ailine.parse_ai_line(raw))
        # ...and neither does a real file cut at every plausible boundary.
        whole = self._raw()
        for cut in range(0, len(whole), 977):
            ailine.parse_ai_line(whole[:cut])


class TestTolerated(unittest.TestCase):
    def test_optional_grid_tail_is_not_corruption(self):
        pts = circle_points()
        sides = [(5.0, 6.0)] * len(pts)
        plain = ailine.parse_ai_line(pack_ai(pts, sides))
        gridded = ailine.parse_ai_line(pack_ai(pts, sides, grid=True))
        self.assertIsNotNone(gridded)
        self.assertEqual(gridded["lx"], plain["lx"])
        self.assertEqual(gridded["rz"], plain["rz"])

    def test_permuted_ids_are_followed_not_refused(self):
        # CSP's payloadIndex reading: a genuine permutation means the extras
        # are indexed BY the id, so following it keeps each point paired with
        # its own side distances.
        n = 360
        pts = circle_points(n=n)
        sides = [(5.0, 6.0)] * n
        ids = list(range(1, n)) + [0]      # rotate by one: still a permutation
        band = ailine.parse_ai_line(pack_ai(pts, sides, ids=ids))
        self.assertIsNotNone(band)
        self.assertAlmostEqual(band["lx"][0], 95.0, delta=0.15)

    def test_a_few_bad_side_samples_do_not_cost_the_track(self):
        # Out-of-range samples are clamped to the invalid sentinel and
        # interpolated across; only a wrong MEDIAN condemns a file.
        pts = circle_points()
        sides = [(5.0, 6.0)] * len(pts)
        for i in (3, 4, 5, 100, 200, 201):
            sides[i] = (999.0, -3.0)
        band = ailine.parse_ai_line(pack_ai(pts, sides))
        self.assertIsNotNone(band)
        self.assertAlmostEqual(band["lx"][0], 95.0, delta=0.2)


# =========================================================================
# The real surface: Brands Hatch Indy, measured by the sim itself
# =========================================================================
#
# Everything above is synthetic, and synthetic fixtures cannot catch a
# cross-slope that is right in the small and mirrored in the large -- a
# circle is symmetric enough to hide it. This section drives the parser with
# REAL geometry: __fixtures__/brands_indy_surface.json is the road surface of
# ks_brands_hatch/indy as AC's own physics reported it during the first rig
# session, one sample every ~2.5 m round the lap.
#
# The fixture holds two INDEPENDENT descriptions of the same surface, which
# is what makes it a test rather than a recording:
#
#   nx/ny/nz  the contact normal AC reports under the car, and
#   ax/ay/az  the vector between the two front contact patches -- where the
#             wheels actually were, 1.5 m apart, measured, no model.
#
# A plane fits both to a 4 mm median (test_the_fixture_is_self_consistent),
# so the surface really is locally flat across a car's width and the normals
# really do describe it. That earns the right to build a band from the
# normals and check it against the ground.
#
# No real fast_lane.ai ships with this repo (AC is not installed on the
# machines that run these tests), so the spline is assembled here from the
# fixture: the driven line becomes the AI line, and the side distances
# describe a 6 m track whose centreline the line hugs on the inside at every
# corner, which is what a recorded AI line looks like.

SURFACE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "__fixtures__", "brands_indy_surface.json")


def _surface():
    with open(SURFACE) as f:
        return json.load(f)


def surface_spline(S, half_w=3.0, hug=1.2, with_normals=True):
    """A fast_lane.ai image over the measured Brands Hatch Indy surface."""
    n = S["n"]
    xs, ys, zs = S["x"], S["y"], S["z"]
    curv = []
    for i in range(n):
        a, b = xs[i - 3], zs[i - 3]
        c, d = xs[i], zs[i]
        e, f = xs[(i + 3) % n], zs[(i + 3) % n]
        dth = (math.atan2(f - d, e - c) - math.atan2(d - b, c - a)
               + math.pi) % (2 * math.pi) - math.pi
        ds = math.hypot(c - a, d - b) + math.hypot(e - c, f - d)
        curv.append(dth / (0.5 * ds) if ds > 1e-6 else 0.0)
    pts, sides, normals = [], [], []
    for i in range(n):
        # The AI line sits `hug` metres inside the centreline through
        # corners and on it down the straights -- the apex invariant
        # confirm_left_sign votes on, and the reason side_l != side_r.
        k = sum(curv[(i + j) % n] for j in range(-5, 6)) / 11.0
        off = -max(-1.0, min(1.0, k / 0.05)) * hug
        pts.append((xs[i], ys[i], zs[i]))
        sides.append((half_w - off, half_w + off))
        normals.append((S["nx"][i], S["ny"][i], S["nz"][i]) if with_normals
                       else (0.0, 0.0, 0.0))
    return pack_ai(pts, sides, normals=normals)


@unittest.skipUnless(os.path.exists(SURFACE), "Brands surface fixture absent")
class TestRealBrandsSurface(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.S = _surface()
        cls.band = ailine.parse_ai_line(surface_spline(cls.S))
        cls.flat = ailine.parse_ai_line(
            surface_spline(cls.S, with_normals=False))
        # nearest fixture sample to an arbitrary (x, z), via a coarse grid
        cls.grid = {}
        for i in range(cls.S["n"]):
            cls.grid.setdefault((int(cls.S["x"][i] // 8.0),
                                 int(cls.S["z"][i] // 8.0)), []).append(i)

    def nearest(self, x, z):
        best, bd = None, 1e18
        cx, cz = int(x // 8.0), int(z // 8.0)
        for a in range(cx - 1, cx + 2):
            for b in range(cz - 1, cz + 2):
                for i in self.grid.get((a, b), ()):
                    d = ((self.S["x"][i] - x) ** 2
                         + (self.S["z"][i] - z) ** 2)
                    if d < bd:
                        bd, best = d, i
        return best, math.sqrt(bd)

    def height_at(self, x, z):
        """The measured surface's height at (x, z): the nearest sample's own
        plane, stepped the last metre or two. Owes nothing to ailine."""
        i, d = self.nearest(x, z)
        if i is None or d > 4.0:
            return None
        return self.S["y"][i] - (self.S["nx"][i] * (x - self.S["x"][i])
                                 + self.S["nz"][i] * (z - self.S["z"][i])
                                 ) / self.S["ny"][i]

    def test_the_fixture_is_self_consistent(self):
        # The claim the rest of this class rests on, and the one the module's
        # header comment cites: a plane through the measured normal predicts
        # where the OTHER front wheel sits, to millimetres.
        errs = []
        for i in range(self.S["n"]):
            pred = -(self.S["nx"][i] * self.S["ax"][i]
                     + self.S["nz"][i] * self.S["az"][i]) / self.S["ny"][i]
            errs.append(abs(pred - self.S["ay"][i]))
        errs.sort()
        self.assertLess(errs[len(errs) // 2], 0.006)
        self.assertLess(errs[int(len(errs) * 0.9)], 0.02)

    def test_a_real_racing_line_still_settles_the_labelling(self):
        ai = ailine.decode_v7(surface_spline(self.S))
        self.assertIn("nx", ai)
        # The fixture writes side_l as the driver's-left distance, so the
        # module must land on -1 in its own lateral basis.
        self.assertEqual(ailine.confirm_left_sign(ai), -1)

    def test_the_lap_is_the_length_ac_says_it_is(self):
        self.assertAlmostEqual(self.band["length_m"], self.S["track_len_m"],
                               delta=0.03 * self.S["track_len_m"])

    def test_edges_land_on_the_measured_road(self):
        # The whole change, in one number. Each edge is 3 m from the driven
        # line, so a flat band misses the road by the cross-slope times 3 m.
        got, level = [], []
        for k in range(self.band["n"] - 1):
            for b, acc in ((self.band, got), (self.flat, level)):
                for xx, zz, yy in ((b["lx"][k], b["lz"][k], b["ly"][k]),
                                   (b["rx"][k], b["rz"][k], b["ry"][k])):
                    want = self.height_at(xx, zz)
                    if want is not None:
                        acc.append(abs(yy - want))
        got.sort()
        level.sort()
        self.assertGreater(len(got), 700)
        self.assertLess(got[len(got) // 2], 0.05,
                        "banked edges miss the measured road by %.3f m"
                        % got[len(got) // 2])
        self.assertLess(got[int(len(got) * 0.9)], 0.10)
        # The negative control, and the size of the bug being fixed: the same
        # band with the normals withheld is an order of magnitude worse.
        self.assertGreater(level[len(level) // 2], 5 * got[len(got) // 2])

    def test_the_cross_slope_never_comes_out_mirrored(self):
        # The failure this file fears most: a band that is banked by the
        # right amount the wrong way round looks entirely plausible. Compare
        # the band's own cross-slope against the surface's at every station
        # -- gated on stations that are actually sloped, because a level one
        # carries no information.
        agree = mirrored = total = 0
        for k in range(self.band["n"] - 1):
            dx = self.band["rx"][k] - self.band["lx"][k]
            dz = self.band["rz"][k] - self.band["lz"][k]
            w = math.hypot(dx, dz)
            i, d = self.nearest((self.band["lx"][k] + self.band["rx"][k]) / 2.0,
                                (self.band["lz"][k] + self.band["rz"][k]) / 2.0)
            if i is None or d > 4.0 or w < 1.0:
                continue
            got = (self.band["ry"][k] - self.band["ly"][k]) / w
            want = -(self.S["nx"][i] * dx + self.S["nz"][i] * dz) / (
                self.S["ny"][i] * w)
            if abs(want) < 0.02:
                continue
            total += 1
            agree += (got > 0) == (want > 0)
            mirrored += (-got > 0) == (want > 0)
        self.assertGreater(total, 300)
        self.assertGreater(agree, 0.98 * total,
                           "cross-slope sign agreed only %d/%d" % (agree, total))
        self.assertLess(mirrored, 0.02 * total)

    def test_the_banking_is_the_size_brands_actually_is(self):
        # Measured across this 6 m band: a 0.32 m median drop from one edge
        # to the other, 0.83 m at the worst of it -- 5 to 8 degrees. On the
        # real 10 m-wide circuit that is well over a metre, which is what
        # made "banked corners render flat" worth fixing rather than noting.
        drops = sorted(abs(self.band["ly"][k] - self.band["ry"][k])
                       for k in range(self.band["n"] - 1))
        self.assertGreater(drops[len(drops) // 2], 0.20)
        self.assertGreater(drops[-1], 0.60)
        self.assertLess(drops[-1], 1.20)
        # ...and withholding the normals really does flatten every one of it.
        self.assertEqual(self.flat["bank"], "flat")
        self.assertEqual(self.flat["ly"], self.flat["ry"])

    def test_paddock_hill_and_clearways_are_banked_the_measured_way(self):
        # Two named corners, so a future reader can check the claim against
        # the circuit rather than against this file. Both are banked with the
        # OUTSIDE high (2.8 degrees at Paddock, 7.1 at Clearways) -- which is
        # not what a plausible-sounding "the outside falls away at Paddock"
        # would predict, and is what AC's own surface says.
        for nsp, least in ((0.15, 0.15), (0.86, 0.50)):
            j = min(range(self.S["n"]),
                    key=lambda i: abs(self.S["nsp"][i] - nsp))
            k = min(range(self.band["n"] - 1),
                    key=lambda q: (self.band["lx"][q] - self.S["x"][j]) ** 2
                    + (self.band["lz"][q] - self.S["z"][j]) ** 2)
            drop = self.band["ly"][k] - self.band["ry"][k]
            want_l = self.height_at(self.band["lx"][k], self.band["lz"][k])
            want_r = self.height_at(self.band["rx"][k], self.band["rz"][k])
            self.assertIsNotNone(want_l)
            self.assertGreater(abs(drop), least,
                               "nsp %.2f came out flat (%.3f m)" % (nsp, drop))
            self.assertEqual(drop > 0, want_l - want_r > 0,
                             "nsp %.2f is banked the wrong way" % nsp)

    def test_the_band_climbs_the_hill_the_lap_climbs(self):
        # Brands Indy drops 23.5 m from Paddock to Graham Hill and climbs it
        # all back: an elevation series that came out flat, or attenuated by
        # the smoothing, would show here.
        lo = min(min(self.band["ly"]), min(self.band["ry"]))
        hi = max(max(self.band["ly"]), max(self.band["ry"]))
        self.assertAlmostEqual(hi - lo, max(self.S["y"]) - min(self.S["y"]),
                               delta=0.6)


if __name__ == "__main__":
    unittest.main()
