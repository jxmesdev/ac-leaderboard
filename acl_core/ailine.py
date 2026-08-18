# Parse Assetto Corsa's ai/fast_lane.ai (AiSpline version 7) and build the
# TRUE track boundary. Python 3.3 compatible; decoding is pure (bytes in,
# lists out) so it is unit-testable without an AC install.
#
# Why: map.png is a stylized minimap -- its ribbon is drawn at roughly 60% of
# the real track width and its map.ini offsets can be a couple of pixels off.
# fast_lane.ai stores the ideal-line points in WORLD coordinates (the same
# coordinate system telemetry world positions use) plus per-point distances to
# the left/right track edges, so edges built from it align with recorded laps
# exactly, by construction.
#
# THE FRAME IS AC's WORLD FRAME -- +x right, +z DOWN seen from above --
# because these are the same AC world metres telemetry world positions
# carry, read straight off disk. Two consequences worth knowing before
# touching a sign in this file:
#   * the left/right labels below come from a CROSS PRODUCT, so they are
#     handedness-dependent. Negating z on the OUTPUT alone silently swaps
#     `lx` and `rx`; negating it consistently through the module is
#     self-cancelling and changes nothing.
#   * the band and the lap must stay in the SAME frame. Moving one without
#     the other does not mirror the drawing, it tears it -- the lap pokes
#     out of its own track edges.
#
# ELEVATION AND CROSS-SLOPE. The points carry `y` and every extra record
# carries a surface `normal`, so the band is built in 3D: each edge sits at
# ITS OWN height instead of inheriting the centreline's, and a banked corner
# renders banked. Both fields were already being decoded and thrown away.
#
#   * The datum is AC's `pos_y` -- the same quantity a recorded lap stores as
#     its `y` channel, because the AI line was recorded by driving. So the
#     band and the lap share a vertical origin by construction, exactly as
#     they already share a horizontal one, and there is nothing to register.
#     Measured on the real Brands Hatch Indy laps: `pos_y` sits 3 cm below the
#     mean of the four contact patches (-0.138 m to +0.070 m over a lap), so
#     reading the driven line's height AS the road's costs centimetres.
#   * Cross-slope comes from the `normal` VECTOR, not from the `camber`
#     scalar beside it. A vector carries its own convention: project it onto
#     the lateral and both the sign and the units fall out. `camber` is one
#     number whose sign convention is undocumented and whose units (radians?
#     ratio? per cent?) no two readers agree on -- the same class of ambiguity
#     that already costs this module detect_left_sign, and a banking mirrored
#     left-for-right would look plausible and be wrong at every corner. So
#     `camber` stays unread, and a file whose normals are unusable gets flat
#     cross-sections rather than a guess.
#   * The plane model is verified against the rig's own laps, not assumed.
#     AC's contact normals predict the measured height difference across the
#     front axle -- 1.5 m of it -- to a 4 mm median, so the road really is
#     locally planar across a car's width and the normals really do describe
#     it. That is pinned in tests/test_ailine.py against
#     tests/__fixtures__/brands_indy_surface.json, and it held a second way
#     off-line: the cross-slope fitted from eight DIFFERENT driven lines
#     agrees with the normals to 0.001 m/m over 120 stations round the lap.
#     Brands Hatch Indy runs to 0.14 m/m of cross-slope, which is 1.4 m
#     across a 10 m track -- flat edges are not a small error there.
#
# Binary layout (little-endian, per Kunos AiSpline v7):
#   header : int32 version(=7), int32 count, int32 lapTime, int32 sampleCount
#   points : count * { float x, y, z, length; int32 id }           (20 bytes)
#   extra  : int32 extraCount(=count), then count * 18 floats      (72 bytes)
#            [speed, gas, brake, obsoleteLatG, radius, SIDE_LEFT, SIDE_RIGHT,
#             camber, direction, normal xyz, length, forward xyz, tag, grade]
#   tail   : optional int32 hasGrid + spatial lookup grid. Ignored here, so
#            trailing bytes past the extras are NORMAL, not corruption.
#
# lapTime/sampleCount are a zero hole in practice (CSP writes int64 0 over
# both), so sampleCount must NOT be used to cross-check count.
#
# Only version 7 carries side distances. The AssettoServer traffic variant
# (version -1) stores {vec3, radius, camber} and stops -- no edge data at all
# -- and a fast_lane.aip is a ZIP whose "PK\x03\x04" magic reads as version
# 0x04034b50. Both are rejected by the version check, which is the honest
# outcome: no edges, so the viewer falls back. Fabricated edges would be worse
# than none.
#
# The single most common third-party parsing bug is skipping the int32
# extraCount between the points and the extras: every extra field then shifts
# by one, SIDE_LEFT reads the `radius` column (hundreds of metres), and the
# result is a plausible-looking but wildly wrong band. The width bounds below
# exist to catch exactly that.

import math
import struct

_HEADER = struct.Struct("<iiii")
_POINT = struct.Struct("<ffffi")
_EXTRA = struct.Struct("<18f")

# A hand-rolled offset would silently drift; assert the strides we rely on.
assert _POINT.size == 20 and _EXTRA.size == 72

# Sanity bounds: AC world coords are metres from track origin.
_MAX_COORD = 100000.0
_MAX_SIDE = 80.0          # no real track is wider than this per side

# A surface normal is only believable as one if it is a UNIT vector pointing
# broadly upward. Both halves matter: the magnitude test is what catches an
# unpopulated or misaligned column (zeros, or three unrelated floats), and the
# upward test is what keeps a wall out of the road surface. 0.5 is cos(60 deg)
# -- the steepest banking in any real content is Bristol's 36 deg (ny 0.81)
# and Daytona's 31 (0.86), so the floor rejects nonsense without curating.
_NORMAL_TOL = 0.02
_MIN_NORMAL_Y = 0.5

# Real splines run ~1 point per 0.5-3 m: a 7 km circuit is 2k-15k points and
# the Nordschleife reaches ~60k. Under 8 there is no polygon to draw.
_MIN_COUNT = 8
_MAX_COUNT = 500000

# Plausible TOTAL track width (side_l + side_r), metres. Bounds are deliberately
# wide -- they reject misparsed files, they do not curate content:
#   3.0  a modern F1 car is ~2 m wide; anything under 3 m cannot be a driveable
#        track, so the side columns are junk (or a near-zero sentinel run).
#   60.0 the widest real AC content -- Daytona's tri-oval, drag strips, airfield
#        and rallycross layouts -- stays under ~50 m. Past 60 m the likeliest
#        explanation is the extraCount off-by-one above, where SIDE_LEFT is
#        actually `radius` and reads 1000+ on straights.
_MIN_TRACK_WIDTH = 3.0
_MAX_TRACK_WIDTH = 60.0

# Output precision, decimal places on metres. 2 dp = 1 cm.
# The viewer draws a whole circuit (a ~1-5 km extent) into ~1000 px, so one
# screen pixel is on the order of a metre: 1 cm is ~1/100 of a pixel and can
# never be seen, even zoomed. It is also an order of magnitude below the
# spline's own sample noise, so it discards nothing real. Going coarser is
# what would show: at 1 dp (10 cm) the two edges of a 5 m-wide track would
# visibly stair-step against each other under zoom, and the quantisation
# would be 2% of the width itself.
_ROUND_DP = 2


def decode_v7(raw):
    """Decode fast_lane.ai bytes to {"x", "y", "z", "side_l", "side_r"} lists
    (plus "nx"/"ny"/"nz" when the file carries usable surface normals), or
    None if `raw` is not a usable v7 spline. Pure: no I/O, never raises.

    None covers three genuinely different situations, all of which mean the
    same thing to the caller -- this track has no edge data:
      * not a v7 AiSpline (wrong version, a .aip ZIP, truncated, junk);
      * structurally inconsistent (extraCount != count, non-finite values,
        implausible width -- i.e. we are misreading it);
      * a valid v7 file whose side columns were never populated.
    The last is extremely common and not an error: AC only merges the track
    borders into fast_lane.ai when the AI line was recorded with the track's
    data/side_l.csv + side_r.csv present AND shift held, so plenty of tracks
    (mods especially) ship all-zero sides.

    Missing NORMALS are softer than missing sides: they cost the band its
    cross-slope, not its existence, so the keys are simply absent and the
    caller builds flat cross-sections. Sides are load-bearing; banking is not.
    """
    if raw is None or len(raw) < _HEADER.size:
        return None
    try:
        version, count, _laptime, _samples = _HEADER.unpack_from(raw, 0)
        if version != 7 or count < _MIN_COUNT or count > _MAX_COUNT:
            return None
        # Size arithmetic: a spline is 20 + 92*count bytes plus an optional
        # grid tail. Fewer bytes than that means the header is lying about
        # count, whatever the per-section checks would say later.
        if (len(raw) - _HEADER.size - 4) // (_POINT.size + _EXTRA.size) < count:
            return None

        off = _HEADER.size
        xs = []
        ys = []
        zs = []
        seq = True
        ids = []
        for i in range(count):
            x, y, z, _ln, pid = _POINT.unpack_from(raw, off + i * _POINT.size)
            # struct hands back NaN/Inf from junk bytes quite happily, and NaN
            # propagates silently all the way into the drawn polygon. Test for
            # finiteness explicitly rather than relying on a comparison that
            # happens to be False for NaN.
            if not (math.isfinite(x) and math.isfinite(z) and math.isfinite(y)):
                return None
            # y is bounded on the same terms as x and z, and deliberately so:
            # it sits BETWEEN them in the 20-byte record, so a y that is not a
            # plausible world coordinate indicts the whole point stride -- the
            # x and z either side of it are then wrong too, just less visibly.
            if not (abs(x) < _MAX_COORD and abs(z) < _MAX_COORD
                    and abs(y) < _MAX_COORD):
                return None
            if pid != i:
                seq = False
            ids.append(pid)
            xs.append(x)
            ys.append(y)
            zs.append(z)

        off += count * _POINT.size
        (extra_count,) = struct.unpack_from("<i", raw, off)
        off += 4
        # Hard invariant. Do NOT fall back to "read as many extras as fit":
        # that is precisely how the off-by-four parsers produce shifted fields.
        if extra_count != count or len(raw) < off + count * _EXTRA.size:
            return None

        # Kunos and nearly every writer emit id == i and everyone pairs extras
        # positionally. CSP alone treats the field as an index INTO the extras
        # ("payloadIndex") and dereferences it. The two readings agree for all
        # real content; where they cannot, follow CSP if the ids are a genuine
        # permutation, and otherwise refuse -- a scrambled id column means we
        # are misreading the file, and mis-paired side distances are invisible
        # in the output but wrong at every corner.
        order = None
        if not seq:
            if sorted(ids) != list(range(count)):
                return None
            order = ids

        side_l = []
        side_r = []
        usable = 0
        widths = []
        nxs = []
        nys = []
        nzs = []
        normals = 0
        for i in range(count):
            j = i if order is None else order[i]
            vals = _EXTRA.unpack_from(raw, off + j * _EXTRA.size)
            sl, sr = vals[5], vals[6]
            if not (math.isfinite(sl) and math.isfinite(sr)):
                return None
            # A handful of bad samples must not cost the whole track, so clamp
            # to the 0.0 "invalid" sentinel and let _fill_invalid_sides repair
            # the run later. Only a wrong MEDIAN condemns the file.
            if not (0.0 <= sl < _MAX_SIDE and 0.0 <= sr < _MAX_SIDE):
                sl = sr = 0.0
            if sl > 0.5 and sr > 0.5:
                usable += 1
                widths.append(sl + sr)
            side_l.append(sl)
            side_r.append(sr)
            # Surface normal, columns 9-11. ny == 0.0 is the invalid sentinel
            # and cannot collide with a real reading, since a usable normal
            # has ny >= _MIN_NORMAL_Y by definition.
            nx, ny, nz = vals[9], vals[10], vals[11]
            if not (math.isfinite(nx) and math.isfinite(ny)
                    and math.isfinite(nz)):
                nx = ny = nz = 0.0
            else:
                mag = math.sqrt(nx * nx + ny * ny + nz * nz)
                if abs(mag - 1.0) > _NORMAL_TOL or ny < _MIN_NORMAL_Y:
                    nx = ny = nz = 0.0
                else:
                    normals += 1
            nxs.append(nx)
            nys.append(ny)
            nzs.append(nz)
        if usable < count // 2:
            return None          # sides not populated on this track
        # Median, not mean: robust to the clamped outliers above.
        med = sorted(widths)[len(widths) // 2]
        if not (_MIN_TRACK_WIDTH <= med <= _MAX_TRACK_WIDTH):
            return None
        out = {"x": xs, "y": ys, "z": zs,
               "side_l": side_l, "side_r": side_r}
        # All or nothing on the normal column, on the same majority rule the
        # sides use. Real content either recorded the surface everywhere or
        # nowhere; a file where half the normals fail the unit test is one
        # whose normal column we are not reading correctly, and interpolating
        # banking across half a lap from the other half would be invention.
        if normals >= count // 2:
            out["nx"] = nxs
            out["ny"] = nys
            out["nz"] = nzs
        return out
    except struct.error:
        return None


def parse_fast_lane(path):
    """Return the decode_v7 dict for a spline on disk, or None if unreadable."""
    try:
        with open(path, "rb") as f:
            buf = f.read()
    except (IOError, OSError):
        return None
    return decode_v7(buf)


def smooth_closed(xs, zs, iters=3, lam=0.5, cap=0.8):
    """Capped Laplacian smoothing of a CLOSED polyline (last == first).

    Each pass moves a point halfway towards its neighbours' midpoint; the
    total displacement of any point is capped at `cap` metres so corners are
    rounded off by noise-scale amounts only, never reshaped.
    """
    n = len(xs) - 1          # last repeats first
    ox, oz = list(xs[:n]), list(zs[:n])
    cx, cz = list(ox), list(oz)
    for _ in range(iters):
        nx, nz = list(cx), list(cz)
        for i in range(n):
            mx = (cx[i - 1] + cx[(i + 1) % n]) / 2.0
            mz = (cz[i - 1] + cz[(i + 1) % n]) / 2.0
            px = cx[i] + (mx - cx[i]) * lam
            pz = cz[i] + (mz - cz[i]) * lam
            dx, dz = px - ox[i], pz - oz[i]
            d = math.hypot(dx, dz)
            if d > cap:
                px = ox[i] + dx / d * cap
                pz = oz[i] + dz / d * cap
            nx[i], nz[i] = px, pz
        cx, cz = nx, nz
    cx = [round(v, 2) for v in cx]
    cz = [round(v, 2) for v in cz]
    cx.append(cx[0])
    cz.append(cz[0])
    return cx, cz


def _fill_invalid_sides(sl, sr, eps=0.05):
    """Repair samples where BOTH sides are ~0 (the parser's invalid sentinel)
    by circular linear interpolation between the bounding valid samples.
    Without this, smoothing averages the zeros into valid neighbours --
    bending the centerline and pinching the band width near data gaps.
    A single zero side is left alone (the line can legitimately touch an edge).
    """
    n = len(sl)
    vidx = [i for i in range(n) if not (sl[i] <= eps and sr[i] <= eps)]
    if len(vidx) == n or not vidx:
        return sl, sr
    out_l, out_r = list(sl), list(sr)
    m = len(vidx)
    # O(n): walk consecutive valid pairs, interpolate across each gap run
    for a in range(m):
        i0 = vidx[a]
        i1 = vidx[(a + 1) % m]
        gap = (i1 - i0) % n
        if gap <= 1:
            continue
        for step in range(1, gap):
            t = step / float(gap)
            j = (i0 + step) % n
            out_l[j] = sl[i0] + (sl[i1] - sl[i0]) * t
            out_r[j] = sr[i0] + (sr[i1] - sr[i0]) * t
    return out_l, out_r


def _fill_gaps(vals, ok):
    """Circular linear interpolation across the runs where `ok[i]` is false.

    The same repair _fill_invalid_sides performs, for a series whose validity
    is decided elsewhere (the normal columns, where ny == 0.0 means "not a
    surface normal"). Kept separate rather than merged into that function
    because the pair rule there -- BOTH sides near zero -- is about what a
    side distance means, not about gap filling.
    """
    n = len(vals)
    vidx = [i for i in range(n) if ok[i]]
    if len(vidx) == n or not vidx:
        return list(vals)
    out = list(vals)
    m = len(vidx)
    for a in range(m):
        i0 = vidx[a]
        i1 = vidx[(a + 1) % m]
        gap = (i1 - i0) % n
        if gap <= 1:
            continue
        for step in range(1, gap):
            t = step / float(gap)
            out[(i0 + step) % n] = vals[i0] + (vals[i1] - vals[i0]) * t
    return out


def _smooth_series(vals, half=4):
    """Circular moving average of a per-point series (side distances,
    heights, normal components).
    O(n) running sum -- a windowed loop is O(n*k) and stalls the game's
    update loop on dense splines."""
    n = len(vals)
    w = 2 * half + 1
    if n == 0 or w >= n:
        avg = sum(vals) / n if n else 0.0
        return [avg] * n
    s = 0.0
    for k in range(-half, half + 1):
        s += vals[k % n]
    out = [s / w]
    for i in range(1, n):
        s += vals[(i + half) % n] - vals[(i - half - 1) % n]
        out.append(s / w)
    return out


# Bump when the edge-building algorithm improves: the in-game publisher
# regenerates any stored edges file whose "ver" is older than this.
# 4: edges carry their own heights (ly/ry), so banked corners are banked.
EDGES_VER = 4


def _cross_slope(nx, ny, nz, latx, latz):
    """Metres of rise per metre travelled along the horizontal direction
    (latx, latz), across the surface plane whose normal is (nx, ny, nz).
    See the header for how far a plane can be trusted here (4 mm across an
    axle, measured).

    Scale-invariant in the normal, which is why the caller may smooth the
    three components as ordinary series without renormalising. Zero when
    there is no usable normal -- flat is the honest answer for "unknown",
    and it is exactly what the edges did before they had heights at all.
    """
    if ny <= 0.0:
        return 0.0
    return -(nx * latx + nz * latz) / ny


def _decimate(ai, min_spacing=1.0):
    """Thin overly dense splines to >= min_spacing metres between points.

    Some tracks store the AI line at centimetre spacing; smoothing cost is
    O(n*k) with k ~ 1/spacing, which would stall the game's update loop for
    seconds. One metre is far below the noise scale being smoothed away.
    """
    xs, zs, sl, sr = ai["x"], ai["z"], ai["side_l"], ai["side_r"]
    n = len(xs)
    keep = [0]
    px, pz = xs[0], zs[0]
    for i in range(1, n):
        if math.hypot(xs[i] - px, zs[i] - pz) >= min_spacing:
            keep.append(i)
            px, pz = xs[i], zs[i]
    if len(keep) < 8:
        return ai
    out = {"x": [xs[i] for i in keep], "z": [zs[i] for i in keep],
           "side_l": [sl[i] for i in keep], "side_r": [sr[i] for i in keep]}
    # The vertical columns are optional -- hand-built dicts in tests and the
    # sign detectors below only ever need x/z/sides -- so they are carried
    # only when present, and every consumer must treat them as absent-able.
    for k in ("y", "nx", "ny", "nz"):
        col = ai.get(k)
        if col is not None:
            out[k] = [col[i] for i in keep]
    return out


def _left_sign_vote(ai, k=None):
    """(net_vote, ballots_cast) for the apex-hugging test. See detect_left_sign.

    Separated from the verdict so callers can ask how DECISIVE the vote was:
    a spline with no corners, or one whose line sits centred all the way
    round, casts no ballots and carries no information about the labelling.
    """
    xs, zs = ai["x"], ai["z"]
    sl, sr = ai["side_l"], ai["side_r"]
    n = len(xs)
    if k is None:
        total = 0.0
        for i in range(n):
            total += math.hypot(xs[i] - xs[i - 1], zs[i] - zs[i - 1])
        spacing = total / n if n else 1.0
        k = max(2, int(round(6.0 / max(spacing, 1e-6))))
    vote = 0.0
    cast = 0
    for i in range(n):
        ux = xs[i] - xs[i - k]
        uz = zs[i] - zs[i - k]
        vx = xs[(i + k) % n] - xs[i]
        vz = zs[(i + k) % n] - zs[i]
        ul = math.hypot(ux, uz)
        vl = math.hypot(vx, vz)
        if ul < 1e-6 or vl < 1e-6:
            continue
        # cross > 0 <=> turning toward the (-tz, tx) side of travel
        cross = (ux * vz - uz * vx) / (ul * vl)
        asym = sr[i] - sl[i]
        if abs(cross) < 0.03 or abs(asym) < 0.5:
            continue          # straight, or line is centred: no information
        # inside on (-tz,tx) side and left is the smaller gap -> left points
        # to (-tz,tx): vote +1. All four sign combinations reduce to this:
        vote += (1.0 if cross > 0 else -1.0) * (1.0 if asym > 0 else -1.0)
        cast += 1
    return vote, cast


def detect_left_sign(ai, k=None):
    """Which lateral direction SIDE_LEFT refers to: +1 for (-tz, tx), -1 for
    (tz, -tx). Determined from the data, not from a convention guess.

    The convention cannot be looked up: the two most credible implementations
    disagree. AcTools/Content Manager and the Blender importer both put left
    at (tz, -tx); CSP's own AI Spline Editor puts it at (-tz, tx). So decide
    per file, from physics.

    Physical invariant: at corners the AI fast lane hugs the INSIDE of the
    turn, so the smaller side distance points toward the curvature centre.
    Each sufficiently curved, sufficiently asymmetric point votes; the
    majority wins. Getting this wrong mirrors the band across the weaving
    racing line -- the exact "close but wobbly, laps poke out" symptom.
    """
    vote, _cast = _left_sign_vote(ai, k)
    return 1 if vote >= 0 else -1


def _centreline_turning(ai, sign, kt):
    """Total absolute turning (radians) of the centreline recovered under
    `sign`. The corroborating check for the labelling -- a different physical
    invariant from the apex vote, so agreement between them is real evidence.

    Recovering the centreline as P + ((side_l - side_r)/2) * lat cancels the
    racing line's weave when the sign is right, and DOUBLES it when it is
    wrong. A doubled weave has to turn far more to get round the lap, so the
    lower total turning wins.
    """
    xs, zs = ai["x"], ai["z"]
    sl, sr = ai["side_l"], ai["side_r"]
    n = len(xs)
    cx = []
    cz = []
    for i in range(n):
        tx = xs[(i + kt) % n] - xs[i - kt]
        tz = zs[(i + kt) % n] - zs[i - kt]
        tlen = math.hypot(tx, tz)
        if tlen < 1e-6:
            continue
        off = (sl[i] - sr[i]) / 2.0
        cx.append(xs[i] + sign * -tz / tlen * off)
        cz.append(zs[i] + sign * tx / tlen * off)
    m = len(cx)
    if m < 8:
        return None
    turn = 0.0
    for i in range(m):
        ax = cx[i] - cx[i - 1]
        az = cz[i] - cz[i - 1]
        bx = cx[(i + 1) % m] - cx[i]
        bz = cz[(i + 1) % m] - cz[i]
        al = math.hypot(ax, az)
        bl = math.hypot(bx, bz)
        if al < 1e-9 or bl < 1e-9:
            continue
        cosang = (ax * bx + az * bz) / (al * bl)
        turn += math.acos(max(-1.0, min(1.0, cosang)))
    return turn


def confirm_left_sign(ai, kt=None):
    """The detected SIDE_LEFT direction (+1/-1), or None if the data does not
    support a confident answer.

    Two independent tests must agree: the apex-hugging vote (which needs
    corners and an off-centre line) and centreline smoothness (which needs a
    line that weaves). Where one is uninformative the other decides; where
    they actively disagree, or neither has anything to say, return None.

    Returning None costs the track its outline. Guessing costs a MIRRORED
    outline, which looks plausible on a symmetric circuit and is wrong at
    every apex -- and, being plausible, would not get reported as a bug.
    """
    xs, zs = ai["x"], ai["z"]
    n = len(xs)
    if n < _MIN_COUNT:
        return None
    if kt is None:
        total = 0.0
        for i in range(n):
            total += math.hypot(xs[i] - xs[i - 1], zs[i] - zs[i - 1])
        spacing = total / n if n else 1.0
        kt = max(1, int(round(6.0 / max(spacing, 1e-6) / 2.0)))

    vote, cast = _left_sign_vote(ai)
    # Require both a quorum and a margin. A near-tied vote on a circuit that
    # does have corners means the apex invariant is not holding -- which is
    # itself a reason not to trust the labelling.
    voted = None
    if cast >= 20 and abs(vote) >= 0.2 * cast:
        voted = 1 if vote > 0 else -1

    turn_pos = _centreline_turning(ai, 1, kt)
    turn_neg = _centreline_turning(ai, -1, kt)
    smoothed = None
    if turn_pos is not None and turn_neg is not None:
        lo, hi = min(turn_pos, turn_neg), max(turn_pos, turn_neg)
        # Only decisive when the two differ properly. A line that runs
        # parallel to the centreline (constant offset) smooths identically
        # either way and must not be allowed to cast a coin-flip vote.
        if hi > 1e-6 and (hi - lo) / hi > 0.02:
            smoothed = 1 if turn_pos < turn_neg else -1

    if voted is not None and smoothed is not None:
        return voted if voted == smoothed else None
    return voted if voted is not None else smoothed


def _build_band(ai, sign, step_m=3.0, tangent_m=6.0):
    """Shared geometry core: the edge polylines plus the centreline length.

    `sign` is the caller's decision about which lateral direction side_l
    refers to -- see detect_left_sign / confirm_left_sign. Returns
    {"lx", "lz", "rx", "rz", "length_m"} or None, plus {"ly", "ry", "bank"}
    when the spline carried elevation. Coordinates are world metres, rounded
    to _ROUND_DP.

    HEIGHTS ride the same two stages as the plan view, for the same reason:
    the AI line's own height is the surface under the RACING line, which is
    metres off centre, so on a cross-slope it is metres of lateral offset
    times the slope away from the centreline's height. Recover the centre
    first (stage 1), then tilt each edge away from it (stage 2). Skipping
    stage 1 would drop the whole band by that much wherever the line is
    off-centre, i.e. at exactly the corners banking exists for.

    `length_m` stays a PLAN-VIEW length: it is the figure a lap time is
    quoted against and the one AC's own track_len_m matches, and the 3D
    difference is 0.06% even at Brands Indy (23.5 m of elevation over
    1.9 km).

    fast_lane.ai is the AI RACING line: it weaves across the track and any
    sample jitter is amplified into edge wobble when offset 5-10m sideways.
    So the edges are built in two stages:

      1. Recover the TRACK CENTERLINE: offset each racing-line point by
         (side_l - side_r)/2 along the (window-averaged) lateral. The
         centerline is real, smooth track geometry -- the weave cancels out.
      2. Offset the smoothed centerline by +-width/2 along the CENTERLINE's
         own tangent, with the width profile smoothed as a series.

    Deliberately NOT using the stored `forward` vector for the tangent: it is
    only the normalised step to the next point, so on a 0.3 m spline it is
    dominated by sample jitter, and it is zero or garbage in many files.
    A windowed central difference over ~tangent_m of arc is stable.
    """
    ai = _decimate(ai)
    xs, zs = ai["x"], ai["z"]
    n = len(xs)
    total = 0.0
    for i in range(n):
        total += math.hypot(xs[i] - xs[i - 1], zs[i] - zs[i - 1])
    spacing = total / n if n else 1.0
    kt = max(1, int(round(tangent_m / max(spacing, 1e-6) / 2.0)))
    ks = max(2, kt)
    fl, fr = _fill_invalid_sides(ai["side_l"], ai["side_r"])
    sl = _smooth_series(fl, half=ks)
    sr = _smooth_series(fr, half=ks)

    ys = ai.get("y")
    nxs, nys, nzs = ai.get("nx"), ai.get("ny"), ai.get("nz")
    if nys is not None:
        # Normals are sampled where the car drove, so a kerb strike or a
        # suspension oscillation shows up as a one-sample tilt -- and a tilt
        # is levered out to the full half-width, where a centimetre at the
        # line becomes a decimetre at the edge. Same window as the sides.
        ok = [v > 0.0 for v in nys]
        nxs = _smooth_series(_fill_gaps(nxs, ok), half=ks)
        nys = _smooth_series(_fill_gaps(nys, ok), half=ks)
        nzs = _smooth_series(_fill_gaps(nzs, ok), half=ks)

    # Stage 1: centerline + width per racing-line point. The lateral is
    # `sign`-corrected, so side_l is applied in the direction the CALLER
    # established from the data -- never a hard-coded handedness convention.
    cx = []
    cz = []
    wid = []
    cy = [] if ys is not None else None
    src = []                 # racing-line index behind each centreline point
    for i in range(n):
        tx = xs[(i + kt) % n] - xs[i - kt]
        tz = zs[(i + kt) % n] - zs[i - kt]
        tlen = math.hypot(tx, tz)
        if tlen < 1e-6:
            continue
        latx, latz = sign * -tz / tlen, sign * tx / tlen
        off = (sl[i] - sr[i]) / 2.0
        cx.append(xs[i] + latx * off)
        cz.append(zs[i] + latz * off)
        wid.append((sl[i] + sr[i]) / 2.0)
        src.append(i)
        if cy is not None:
            slope = 0.0 if nys is None else _cross_slope(
                nxs[i], nys[i], nzs[i], latx, latz)
            cy.append(ys[i] + slope * off)
    m = len(cx)
    if m < _MIN_COUNT:
        return None
    wid = _smooth_series(wid, half=ks)
    if cy is not None:
        # The AI line is a driven line, so its height carries body heave --
        # a few centimetres of suspension noise on top of real terrain. The
        # moving average takes that off and leaves gradients alone: it
        # reproduces a linear ramp exactly, and Brands' steepest is 15%.
        cy = _smooth_series(cy, half=ks)
    # Track length is the centreline's, not the racing line's: the racing
    # line's weave and its apex-cutting make it the shorter, driver-specific
    # figure, whereas the centreline is a property of the track.
    length_m = 0.0
    for i in range(m):
        length_m += math.hypot(cx[i] - cx[i - 1], cz[i] - cz[i - 1])

    # Stage 2: downsample the centerline, then offset by width along ITS
    # tangent (the centerline is smooth, so its tangent is stable).
    idxs = []
    acc = step_m
    px, pz = cx[0], cz[0]
    for i in range(m):
        acc += math.hypot(cx[i] - px, cz[i] - pz)
        px, pz = cx[i], cz[i]
        if acc >= step_m:
            acc = 0.0
            idxs.append(i)
    if len(idxs) < 8:
        return None
    kc = max(1, int(round(tangent_m / max(spacing, 1e-6) / 2.0)))
    lx = []
    lz = []
    rx = []
    rz = []
    ly = [] if cy is not None else None
    ry = [] if cy is not None else None
    for i in idxs:
        tx = cx[(i + kc) % m] - cx[i - kc]
        tz = cz[(i + kc) % m] - cz[i - kc]
        tlen = math.hypot(tx, tz)
        if tlen < 1e-6:
            continue
        # Signed, so "lx" really is the side side_l measures. The band itself
        # is identical either way (it is symmetric about the centreline), but
        # the viewer draws its start line lx[0] -> rx[0] and a caller reading
        # the key names should not be misled.
        latx, latz = sign * -tz / tlen, sign * tx / tlen
        w = wid[i]
        lx.append(cx[i] + latx * w)
        lz.append(cz[i] + latz * w)
        rx.append(cx[i] - latx * w)
        rz.append(cz[i] - latz * w)
        if ly is not None:
            # Projected onto the CENTRELINE's lateral, not the racing line's:
            # the two differ by a degree or so, and the point of stage 2 is
            # that the centreline's tangent is the stable one. The normal is
            # a property of the surface, so it is read at the racing-line
            # index that produced this centreline point.
            slope = 0.0 if nys is None else _cross_slope(
                nxs[src[i]], nys[src[i]], nzs[src[i]], latx, latz)
            ly.append(cy[i] + slope * w)
            ry.append(cy[i] - slope * w)
    if len(lx) < _MIN_COUNT:
        return None
    lx.append(lx[0])
    lz.append(lz[0])
    rx.append(rx[0])
    rz.append(rz[0])
    lx, lz = smooth_closed(lx, lz)
    rx, rz = smooth_closed(rx, rz)
    band = {"lx": lx, "lz": lz, "rx": rx, "rz": rz,
            "length_m": round(length_m, 1)}
    if ly is not None:
        # Closed and rounded like the plan view, and NOT put through
        # smooth_closed: that smooths a polyline against its own neighbours
        # in the plane, which for a height series would flatten real
        # gradients. Every input here is already smoothed as a series.
        ly.append(ly[0])
        ry.append(ry[0])
        band["ly"] = [round(v, _ROUND_DP) for v in ly]
        band["ry"] = [round(v, _ROUND_DP) for v in ry]
        # Says which of the two claims this band is making. "flat" is an
        # honest statement about a file with no surface normals -- elevation
        # known, cross-slope not -- and must not be mistaken for measured
        # banking that happens to be zero.
        band["bank"] = "flat" if nys is None else "normal"
    return band


def _with_heights(out, band):
    """Copy the optional height keys from a band onto an output dict.

    Absent stays absent. A spline with no y has no honest height to report,
    and filling in zeros would lay a hillside circuit flat at the datum --
    the same lie the flat edges told, only harder to spot because it would
    look deliberate.
    """
    if band.get("ly") is not None:
        out["ly"] = band["ly"]
        out["ry"] = band["ry"]
        out["bank"] = band["bank"]
    return out


def build_edges(ai, step_m=3.0, tangent_m=6.0):
    """Left/right track-edge polylines in world metres from a parsed spline.

    Returns {"lx", "lz", "rx", "rz", "src": "ai", "ver": EDGES_VER} plus
    {"ly", "ry", "bank"} when the spline carried elevation, in METRES at
    centimetre precision (smooth_closed rounds to 2 dp) -- not in
    centimetres, as an earlier version of this docstring claimed. The viewer
    consumes metres, the same space as the lap's x/z/y channels.
    """
    band = _build_band(ai, detect_left_sign(ai), step_m, tangent_m)
    if band is None:
        return None
    return _with_heights({"lx": band["lx"], "lz": band["lz"],
                          "rx": band["rx"], "rz": band["rz"],
                          "src": "ai", "ver": EDGES_VER}, band)


def parse_ai_line(raw):
    """fast_lane.ai bytes -> track boundary, or None.

    The one-call pure entry point: bytes in, geometry out, no file I/O, no
    network, no app or sim coupling. Returns

        {"lx": [...], "lz": [...],      left boundary, world metres
         "rx": [...], "rz": [...],      right boundary, world metres
         "ly": [...], "ry": [...],      their HEIGHTS, world metres (optional)
         "bank": "normal" | "flat",     where those heights' tilt came from
         "n": int,                      points per polyline (all four equal)
         "length_m": float}             centreline lap length, metres

    or None if this file cannot yield an honest boundary. The polylines are
    closed (last point repeats the first) and index-aligned, so lx[i]/rx[i]
    are opposite each other across the track and lx[0] -> rx[0] is the start
    line the viewer draws.

    Coordinates are AC world metres, the same space as a lap's x/z channels
    -- no scale, no offset, no negation, no image registration -- so the band
    lands on the recorded line by construction. ly/ry share that property
    vertically: they are the same `pos_y` a lap stores as `y`.

    ly/ry are absent, together, on a spline with no usable elevation. Present
    with "bank": "flat" is a different statement -- the heights are real and
    the cross-slope is unknown, so each cross-section is level.

    None is a first-class result, not a failure to report: an unreadable
    spline, an unpopulated one, or one whose left/right labelling cannot be
    established all mean "this track has no edges", and the viewer falls back.
    Never raises, so a malformed file cannot take a stint down with it.
    """
    try:
        ai = decode_v7(raw)
        if ai is None:
            return None
        # Decide the labelling BEFORE building. If the data will not say,
        # stop here: a mirrored band is worse than no band, because it looks
        # right and is wrong at every apex.
        sign = confirm_left_sign(ai)
        if sign is None:
            return None
        band = _build_band(ai, sign)
        if band is None:
            return None
        n = len(band["lx"])
        if n < _MIN_COUNT or len(band["lz"]) != n \
                or len(band["rx"]) != n or len(band["rz"]) != n:
            return None
        if band.get("ly") is not None and (len(band["ly"]) != n
                                           or len(band["ry"]) != n):
            return None       # index alignment is the whole contract
        return _with_heights({"lx": band["lx"], "lz": band["lz"],
                              "rx": band["rx"], "rz": band["rz"],
                              "n": n, "length_m": band["length_m"]}, band)
    except Exception:
        # Belt and braces. Every failure path above is explicit, but edge
        # building runs inside the game's update loop: an optional cosmetic
        # feature must never be the thing that ends a session.
        return None
