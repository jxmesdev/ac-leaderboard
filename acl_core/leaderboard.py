# Leaderboard computation: filter records for a track+car combo and rank them.
# Python 3.3 compatible.

from acl_core.storage import combo_key, record_key, norm
from acl_core.timefmt import format_ms


def leaderboard_for(records, track, config, car):
    """Return ranked rows for a given track/config/car combination.

    Each row is a dict:
        {
          "rank": 1-based int,
          "user": display name,
          "time_ms": int,
          "time_str": "M:SS.mmm",
          "gap_ms": ms behind leader (0 for leader),
          "gap_str": "+1.234" (or "" for leader),
          "date": iso date string or "",
          "source": "auto"|"manual"|"",
        }
    Records are assumed to already hold at most one entry per user for the
    combo (see Store.upsert_record), but duplicates are collapsed defensively.
    """
    want = combo_key(track, config, car)
    best_by_user = {}
    for r in records:
        if (norm(r.get("track")), norm(r.get("config")), norm(r.get("car"))) != want:
            continue
        ms = r.get("time_ms")
        if ms is None:
            continue
        user_key = norm(r.get("user"))
        cur = best_by_user.get(user_key)
        if cur is None or ms < cur.get("time_ms", 1 << 62):
            best_by_user[user_key] = r

    rows = list(best_by_user.values())
    rows.sort(key=lambda r: (r.get("time_ms", 1 << 62), norm(r.get("user"))))

    out = []
    leader_ms = rows[0].get("time_ms") if rows else None
    for i, r in enumerate(rows):
        ms = r.get("time_ms")
        gap = 0 if leader_ms is None else (ms - leader_ms)
        out.append({
            "rank": i + 1,
            "user": r.get("user", ""),
            "time_ms": ms,
            "time_str": format_ms(ms),
            "gap_ms": gap,
            "gap_str": "" if gap == 0 else "+" + _format_gap(gap),
            "date": r.get("date", "") or "",
            "source": r.get("source", "") or "",
        })
    return out


def _format_gap(gap_ms):
    """Format a positive gap in ms as seconds, e.g. 1234 -> '1.234'."""
    seconds = gap_ms // 1000
    millis = gap_ms % 1000
    return "{0}.{1:03d}".format(seconds, millis)
