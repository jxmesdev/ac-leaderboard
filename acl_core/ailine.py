# Parse Assetto Corsa's ai/fast_lane.ai (AiSpline version 7) and build the
# TRUE track boundary. Python 3.3 compatible; pure file I/O, unit-testable.
#
# Why: map.png is a stylized minimap -- its ribbon is drawn at roughly 60% of
# the real track width and its map.ini offsets can be a couple of pixels off.
# fast_lane.ai stores the ideal-line points in WORLD coordinates (the same
# coordinate system telemetry world positions use) plus per-point distances to
# the left/right track edges, so edges built from it align with recorded laps
# exactly, by construction.
#
# Binary layout (little-endian, per Kunos AiSpline v7):
#   header : int32 version(=7), int32 count, int32 lapTime, int32 sampleCount
#   points : count * { float x, y, z, length; int32 id }           (20 bytes)
#   extra  : int32 extraCount(=count), then count * 18 floats      (72 bytes)
#            [speed, gas, brake, obsoleteLatG, radius, SIDE_LEFT, SIDE_RIGHT,
#             camber, direction, normal xyz, length, forward xyz, tag, grade]

import math
import struct

_HEADER = struct.Struct("<iiii")
_POINT = struct.Struct("<ffffi")
_EXTRA = struct.Struct("<18f")

# Sanity bounds: AC world coords are metres from track origin.
_MAX_COORD = 100000.0
_MAX_SIDE = 80.0          # no real track is wider than this per side


def parse_fast_lane(path):
    """Return {"x", "z", "side_l", "side_r"} lists, or None if unreadable."""
    try:
        with open(path, "rb") as f:
            buf = f.read()
    except (IOError, OSError):
        return None
    if len(buf) < _HEADER.size:
        return None
    version, count, _laptime, _samples = _HEADER.unpack_from(buf, 0)
    if version != 7 or count < 8 or count > 500000:
        return None
    off = _HEADER.size
    if len(buf) < off + count * _POINT.size + 4:
        return None
    xs = []
    zs = []
    for i in range(count):
        x, _y, z, _ln, _pid = _POINT.unpack_from(buf, off + i * _POINT.size)
        if not (abs(x) < _MAX_COORD and abs(z) < _MAX_COORD):
            return None
        xs.append(x)
        zs.append(z)
    off += count * _POINT.size
    (extra_count,) = struct.unpack_from("<i", buf, off)
    off += 4
    if extra_count != count or len(buf) < off + count * _EXTRA.size:
        return None
    side_l = []
    side_r = []
    usable = 0
    for i in range(count):
        vals = _EXTRA.unpack_from(buf, off + i * _EXTRA.size)
        sl, sr = vals[5], vals[6]
        if not (0.0 <= sl < _MAX_SIDE and 0.0 <= sr < _MAX_SIDE):
            sl = sr = 0.0
        if sl > 0.5 and sr > 0.5:
            usable += 1
        side_l.append(sl)
        side_r.append(sr)
    if usable < count // 2:
        return None          # sides not populated on this track
    return {"x": xs, "z": zs, "side_l": side_l, "side_r": side_r}


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


def _smooth_series(vals, half=4):
    """Circular moving average of a per-point series (side distances).
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
EDGES_VER = 3


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
    return {"x": [xs[i] for i in keep], "z": [zs[i] for i in keep],
            "side_l": [sl[i] for i in keep], "side_r": [sr[i] for i in keep]}


def detect_left_sign(ai, k=None):
    """Which lateral direction SIDE_LEFT refers to: +1 for (-tz, tx), -1 for
    (tz, -tx). Determined from the data, not from a convention guess.

    Physical invariant: at corners the AI fast lane hugs the INSIDE of the
    turn, so the smaller side distance points toward the curvature centre.
    Each sufficiently curved, sufficiently asymmetric point votes; the
    majority wins. Getting this wrong mirrors the band across the weaving
    racing line -- the exact "close but wobbly, laps poke out" symptom.
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
    return 1 if vote >= 0 else -1


def build_edges(ai, step_m=3.0, tangent_m=6.0):
    """Left/right track-edge polylines in world metres from a parsed spline.

    fast_lane.ai is the AI RACING line: it weaves across the track and any
    sample jitter is amplified into edge wobble when offset 5-10m sideways.
    So the edges are built in two stages:

      1. Recover the TRACK CENTERLINE: offset each racing-line point by
         (side_l - side_r)/2 along the (window-averaged) lateral. The
         centerline is real, smooth track geometry -- the weave cancels out.
      2. Offset the smoothed centerline by +-width/2 along the CENTERLINE's
         own tangent, with the width profile smoothed as a series.

    Downsampled to ~step_m spacing, closed, capped-smoothed. Returns
    {"lx", "lz", "rx", "rz", "src": "ai", "ver": EDGES_VER} in centimetres.
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
    ai = {"x": xs, "z": zs, "side_l": fl, "side_r": fr}
    sign = detect_left_sign(ai)
    sl = _smooth_series(fl, half=ks)
    sr = _smooth_series(fr, half=ks)

    # Stage 1: centerline + width per racing-line point. LeftDir is the
    # DATA-DETECTED direction of side_l (see detect_left_sign).
    cx = []
    cz = []
    wid = []
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
    m = len(cx)
    if m < 8:
        return None
    wid = _smooth_series(wid, half=ks)

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
    for i in idxs:
        tx = cx[(i + kc) % m] - cx[i - kc]
        tz = cz[(i + kc) % m] - cz[i - kc]
        tlen = math.hypot(tx, tz)
        if tlen < 1e-6:
            continue
        latx, latz = -tz / tlen, tx / tlen
        w = wid[i]
        lx.append(cx[i] + latx * w)
        lz.append(cz[i] + latz * w)
        rx.append(cx[i] - latx * w)
        rz.append(cz[i] - latz * w)
    if len(lx) < 8:
        return None
    lx.append(lx[0])
    lz.append(lz[0])
    rx.append(rx[0])
    rz.append(rz[0])
    lx, lz = smooth_closed(lx, lz)
    rx, rz = smooth_closed(rx, rz)
    return {"lx": lx, "lz": lz, "rx": rx, "rz": rz,
            "src": "ai", "ver": EDGES_VER}
