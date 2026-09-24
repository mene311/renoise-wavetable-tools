#!/usr/bin/env python3
"""
vitallfo_to_xrdp — migrate Vital LFO shapes (.vitallfo) into Renoise LFO device presets.

    vitallfo_to_xrdp.py [FILES_OR_DIRS...] [-o OUTDIR] [--prefix "Vital "] [--length 64]
                        [--freq 4.0] [--amp 1.0] [--offset 0.0] [--mode auto|curve|points|lines]
                        [--dry]

Vital stores an LFO shape as flat (x, y) pairs with x ascending 0..1, a parallel `powers`
array (per-point bend) and a `smooth` flag. Renoise stores an LFO shape as integer grid
lines with a value, a per-point tension, and a PlayMode of Points | Lines | Curve:

    Vital interpolates linearly between points, so Renoise's `Lines` mode matches it. Two
details decide the conversion:

  staircases   A shape whose segments are all flat or vertical (Square, Pulse Series, the
               gates) becomes sparse PlayMode `Points`, which is Renoise's step-hold and
               what you want to edit by hand.
  everything   Anything with a ramp in it is rasterised onto every grid line and written
  else         as `Lines`, so saws stay saws and a lone vertical edge still snaps in one
               line. Vital's `smooth` flag (its slew filter) is applied as a light moving
               average over those samples, `--smooth-passes` times.

Output is the preset format Renoise writes for the LFO device (plain XML,
`<FilterDevicePreset doc_version="0">` with a `DeviceSlot type="LfoDevice"`), which lives in
`<user library>/Effect Presets/LFO/<name>.xrdp` and shows up in the LFO's preset menu.
"""
import argparse, glob, json, os, sys

OUT_DEFAULT = os.path.expanduser("~/.local/share/Renoise/User Library/Effect Presets/LFO")
TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<FilterDevicePreset doc_version="0">
  <DeviceSlot type="LfoDevice">
    <DestEffect>
      <Value>{dest_effect}</Value>
    </DestEffect>
    <DestParameter>
      <Value>{dest_param}</Value>
    </DestParameter>
    <Amplitude>
      <Value>{amp}</Value>
    </Amplitude>
    <Offset>
      <Value>{offset}</Value>
    </Offset>
    <Frequency>
      <Value>{freq}</Value>
    </Frequency>
    <Type>
      <Value>4</Value>
    </Type>
    <CustomEnvelope>
      <PlayMode>{playmode}</PlayMode>
      <Length>{length}</Length>
      <ValueQuantum>0.0</ValueQuantum>
      <Points>
{points}
      </Points>
    </CustomEnvelope>
  </DeviceSlot>
</FilterDevicePreset>
"""


def read_lfo(path):
    """-> (name, [(x, y, power)], smooth)"""
    d = json.load(open(path))
    flat = d.get("points") or []
    powers = d.get("powers") or []
    pts = []
    for i in range(0, len(flat) - 1, 2):
        n = i // 2
        pts.append((float(flat[i]), float(flat[i + 1]),
                    float(powers[n]) if n < len(powers) else 0.0))
    # the file name is what the user called it; the JSON `name` is stale in many packs
    stem = os.path.splitext(os.path.basename(path))[0]
    return (stem or d.get("name") or "shape", pts, bool(d.get("smooth")))


def grid_length(pts, minimum=64, maximum=512):
    """Pick the envelope grid so the shape's own divisions land on lines. Vital shapes are
    written at fractions like 1/12, 1/16 or 1/24 of a cycle, so 64 lines rounds their edges
    off; 96, 128, 192 or 384 lines fit them exactly. Falls back to whichever candidate has
    the smallest worst-case rounding."""
    sample_pts = pts
    candidates = [96, 128, 192, 256, 384, 512]
    if minimum:
        candidates = [c for c in candidates if c >= minimum] or [512]
    best, best_err = candidates[-1], None
    for n in candidates:
        worst = max(abs(x * n - round(x * n)) for x, _, _ in sample_pts)
        if best_err is None or worst < best_err:
            best, best_err = n, worst
        if worst <= 0.02:
            return n
    return min(best, maximum)


def segment_values(pts, sampled):
    """Piecewise-linear value at each sampled x. Vital writes vertical edges as two
    points at the same x, and there the later value is the one that applies."""
    out = []
    for x in sampled:
        v = None
        for (x0, y0, _), (x1, y1, _) in zip(pts, pts[1:]):
            if x1 - x0 < 1e-12 and abs(x - x0) < 1e-12:
                v = y1                     # exactly on the edge: the jump has happened
                break
        if v is None:
            for (x0, y0, _), (x1, y1, _) in zip(pts, pts[1:]):
                if x1 - x0 < 1e-12:
                    continue
                if x0 <= x <= x1:
                    v = y0 + (y1 - y0) * ((x - x0) / (x1 - x0))
                    break
        if v is None:
            v = pts[0][1] if x < pts[0][0] else pts[-1][1]
        out.append(v)
    return out


def is_staircase(pts):
    """True when every segment is flat or vertical: a gate/staircase shape, which is what
    Renoise's step-hold `Points` mode mirrors. A single hard edge inside an otherwise
    smooth shape does not qualify, since step-hold would flatten its ramps."""
    if not has_hard_edges(pts):
        return False
    for (x0, y0, _), (x1, y1, _) in zip(pts, pts[1:]):
        vertical = abs(x1 - x0) < 1e-6
        flat = abs(y1 - y0) < 1e-3
        if not (vertical or flat):
            return False
    return True


def has_hard_edges(pts):
    """True when the shape has vertical edges inside the cycle. A duplicate at x = 1.0 is
    just the wrap point (Saw Up ends with two points at 1.0), so it does not count."""
    return any(abs(pts[i + 1][0] - pts[i][0]) < 1e-6 and pts[i][0] < 1.0 - 1e-6
               for i in range(len(pts) - 1))


def convert(path, args):
    name, pts, smooth = read_lfo(path)
    length = args.length or grid_length(pts)
    stepped = is_staircase(pts)
    mode = args.mode if args.mode != "auto" else ("Points" if stepped else "Lines")
    mode = {"curve": "Curve", "points": "Points", "lines": "Lines"}.get(mode.lower(), mode)

    if stepped:                        # keep the exact steps, merge the vertical edges
        grid, tensions = {}, {}
        xs = sorted({p[0] for p in pts})
        last_x = xs[-1]
        for x, y, t in pts:
            line = max(0, min(length, int(round(x * length))))
            val = max(0.0, min(1.0, y))
            if line == length and line in grid:
                continue               # the wrap value: keep what the ramp ends on
            if line == length and not grid:
                grid[line] = val
            grid[line] = val
            if abs(t) > 1e-9 and not args.no_tension:
                tensions[line] = max(-1.0, min(1.0, t / args.tension_div))
        rows = []
        for line in sorted(grid):
            t = tensions.get(line, 0.0)
            rows.append(f"        <Point>{line},{grid[line]:.4f},{t:.3f}</Point>")
        used = len(tensions)
    else:                              # continuous shape: one point per grid line
        xs = [i / length for i in range(length + 1)]
        vals = segment_values(pts, xs)
        for _ in range(max(0, args.smooth_passes) if smooth else 0):
            vals = [vals[0]] + [(vals[i - 1] + 2 * vals[i] + vals[i + 1]) / 4
                                for i in range(1, len(vals) - 1)] + [vals[-1]]
        rows = [f"        <Point>{i},{max(0.0, min(1.0, v)):.4f},0.000</Point>"
                for i, v in enumerate(vals)]
        used = 0

    xml = TEMPLATE.format(dest_effect=-1, dest_param=-1, amp=f"{args.amp:g}",
                          offset=f"{args.offset:g}", freq=f"{args.freq:g}",
                          playmode=mode, length=length, points="\n".join(rows))
    return name, xml, dict(points=len(rows), source_points=len(pts), mode=mode,
                           length=length, tensions=used, smooth=smooth)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="*", default=None)
    ap.add_argument("-o", "--outdir", default=OUT_DEFAULT)
    ap.add_argument("--prefix", default="Vital ")
    ap.add_argument("--length", type=int, default=0, help="grid lines (0 = auto per shape)")
    ap.add_argument("--freq", type=float, default=4.0, help="rate in lines per cycle")
    ap.add_argument("--amp", type=float, default=1.0)
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--mode", default="auto", help="auto | curve | points | lines")
    ap.add_argument("--smooth-passes", type=int, default=2,
                    help="moving-average passes for shapes Vital marks as smooth (default 2)")
    ap.add_argument("--tension-div", type=float, default=10.0,
                    help="divisor mapping Vital's point powers onto Renoise tension (-1..1)")
    ap.add_argument("--no-tension", action="store_true", help="ignore Vital's point powers")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    srcs = a.sources or [os.path.expanduser("~/.local/share/vital")]
    files = []
    for s in srcs:
        if os.path.isdir(s):
            files += sorted(glob.glob(os.path.join(s, "**", "*.vitallfo"), recursive=True))
        else:
            files.append(s)
    if not files:
        raise SystemExit("no .vitallfo files found")
    os.makedirs(a.outdir, exist_ok=True)

    print(f"{'preset':34s} {'mode':7s} {'len':>4s} {'pts':>4s} {'tension':>8s}  source")
    ok, skipped, taken = 0, 0, set()
    for f in files:
        try:
            name, xml, info = convert(f, a)
        except Exception as e:
            skipped += 1
            print(f"  skipped {os.path.basename(f)}: {e}")
            continue
        safe = "".join(c for c in name if c.isalnum() or c in " -_().,").strip() or "shape"
        stem = f"{a.prefix}{safe}"
        n = 2
        while stem.lower() in taken:
            stem = f"{a.prefix}{safe} {n}"; n += 1
        taken.add(stem.lower())
        out = os.path.join(a.outdir, stem + ".xrdp")
        if not a.dry:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(xml)
        ok += 1
        print(f"{stem[:34]:34s} {info['mode']:7s} {info['length']:4d} "
              f"{info['points']:4d} {info['tensions']:8d}  {os.path.basename(f)}")
    print(f"\n{'would write' if a.dry else 'wrote'} {ok} presets to {a.outdir}"
          + (f" ({skipped} skipped)" if skipped else ""))


if __name__ == "__main__":
    main()
