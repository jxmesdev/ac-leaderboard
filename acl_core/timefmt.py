# Lap-time formatting/parsing. Python 3.3 compatible (no f-strings).


def format_ms(ms):
    """Format an integer number of milliseconds as a lap time string.

    Examples: 83456 -> "1:23.456", 59999 -> "0:59.999".
    Returns "--:--.---" for None/invalid input.
    """
    if ms is None:
        return "--:--.---"
    try:
        ms = int(round(ms))
    except (TypeError, ValueError):
        return "--:--.---"
    if ms < 0:
        return "--:--.---"
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    millis = ms % 1000
    return "{0}:{1:02d}.{2:03d}".format(minutes, seconds, millis)


def parse_time(text):
    """Parse a human-typed lap time into integer milliseconds, or None.

    Accepts a variety of formats:
      "1:23.456", "1:23.4", "1:23", "83.456", "83", "83.4"
    Whitespace is ignored. Returns None if it cannot be parsed or is <= 0.
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    s = s.replace(",", ".")

    minutes = 0
    rest = s
    if ":" in s:
        parts = s.split(":")
        if len(parts) != 2:
            return None
        min_part, rest = parts[0].strip(), parts[1].strip()
        if min_part == "":
            minutes = 0
        else:
            try:
                minutes = int(min_part)
            except ValueError:
                return None
            if minutes < 0:
                return None

    # rest is seconds(.fraction)
    if rest == "":
        return None
    sec_whole = rest
    frac = "0"
    if "." in rest:
        sp = rest.split(".")
        if len(sp) != 2:
            return None
        sec_whole, frac = sp[0].strip(), sp[1].strip()
        if sec_whole == "":
            sec_whole = "0"
        if frac == "":
            frac = "0"

    if not sec_whole.isdigit() or not frac.isdigit():
        return None

    seconds = int(sec_whole)
    # If there is no explicit minutes field, allow seconds >= 60 (e.g. "83.456").
    if ":" not in s:
        minutes += seconds // 60
        seconds = seconds % 60
    elif seconds >= 60:
        return None

    # Normalise the fractional part to exactly milliseconds (3 digits).
    frac = (frac + "000")[:3]
    millis = int(frac)

    total = minutes * 60000 + seconds * 1000 + millis
    if total <= 0:
        return None
    return total
