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


def build_edges(ai, step_m=3.0):
    """Left/right track-edge polylines in world metres from a parsed spline.

    Offsets each ideal-line point along the XZ perpendicular of the local
    tangent by that point's side distances. Downsampled to ~step_m spacing
    and closed (first point repeated at the end). Returns
    {"lx", "lz", "rx", "rz"} with coordinates rounded to centimetres.
    """
    xs, zs = ai["x"], ai["z"]
    sl, sr = ai["side_l"], ai["side_r"]
    n = len(xs)
    lx = []
    lz = []
    rx = []
    rz = []
    acc = step_m          # so the first point is always emitted
    px, pz = xs[0], zs[0]
    for i in range(n):
        acc += math.hypot(xs[i] - px, zs[i] - pz)
        px, pz = xs[i], zs[i]
        if acc < step_m:
            continue
        acc = 0.0
        tx = xs[(i + 1) % n] - xs[i - 1]
        tz = zs[(i + 1) % n] - zs[i - 1]
        tlen = math.hypot(tx, tz)
        if tlen < 1e-6:
            continue
        # lateral = tangent rotated 90 degrees in the XZ plane
        latx, latz = -tz / tlen, tx / tlen
        lx.append(round(xs[i] + latx * sl[i], 2))
        lz.append(round(zs[i] + latz * sl[i], 2))
        rx.append(round(xs[i] - latx * sr[i], 2))
        rz.append(round(zs[i] - latz * sr[i], 2))
    if len(lx) < 8:
        return None
    lx.append(lx[0])
    lz.append(lz[0])
    rx.append(rx[0])
    rz.append(rz[0])
    return {"lx": lx, "lz": lz, "rx": rx, "rz": rz}
