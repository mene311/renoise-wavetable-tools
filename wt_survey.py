#!/usr/bin/env python3
"""
wt_survey — sample wavetables out of everything on disk, measure them, and (optionally)
build instruments from the sample.

    wt_survey.py --list            measure candidates, write a TSV, print a summary
    wt_survey.py --build           also build + verify the chosen 20

Measurements per table:
  cycles    how many cycles a frame contains (pitch detection; 1 = single cycle)
  bright    spectral centroid in harmonics (how bright the wave is vs its own fundamental)
  ceiling   harmonics a cycle can carry (cycle_len/2), i.e. what the register costs

Brightness is reported, not judged: a bright table is usually a deliberately bright
timbre, not something to be darkened. Builds use the neutral register (one cycle fitted
to the played note, which is what a wavetable synth does) unless you pass --cycle-len to
move the register on purpose.
"""
import argparse, contextlib, io, os, random, subprocess, sys, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wt_xrni as wt   # noqa: E402

V = os.path.expanduser("~/.local/share/vital")
PACKS = os.path.expanduser("~/Projects/renoise/wavetable-packs")
SR = 44100


def candidates():
    out = []
    for root, _, files in os.walk(V):
        for f in files:
            if f.endswith(".vitaltable"):
                out.append(("vitaltable", os.path.join(root, f)))
    rng = random.Random(7)
    presets = []
    for root, _, files in os.walk(V):
        for f in files:
            if f.endswith(".vital"):
                presets.append(os.path.join(root, f))
    out += [("preset", p) for p in rng.sample(presets, min(120, len(presets)))]
    esw = os.path.join(PACKS, "esw", "Echo Sound Works Core Tables")
    if os.path.isdir(esw):
        for root, _, files in os.walk(esw):
            out += [("esw", os.path.join(root, f)) for f in files if f.endswith(".wav")]
    bt = os.path.join(PACKS, "basstables-v1")
    if os.path.isdir(bt):
        for root, _, files in os.walk(bt):
            out += [("basstables", os.path.join(root, f)) for f in files if f.endswith(".wav")]
    ops = os.path.join(PACKS, "ops7")
    if os.path.isdir(ops):
        for root, _, files in os.walk(ops):
            out += [("ops7", os.path.join(root, f)) for f in files if f.endswith(".wav")]
    return out


def measure(kind, path, probe=6):
    """Cheap, consistent measurement: brightness on the frames a build would use."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fr, sr, _ = wt.load_source(path, probe, 0)          # native, no resample no blend
    fr = np.atleast_2d(fr)
    cyc = wt.table_cycles(fr)
    picked, _ = wt.select_table_frames(fr, probe, "even")
    picked = [wt.one_cycle(f, cyc) for f in picked]
    bright = wt.frame_brightness(picked)
    return dict(kind=kind, path=path, frames=len(fr), flen=fr.shape[1], cycles=cyc,
                bright=bright)


def choose(rows, count=20):
    """Stratify by brightness so the sample spans dark to noise, one per source family."""
    buckets = [(0, 1.5), (1.5, 3), (3, 6), (6, 12), (12, 30), (30, 70), (70, 1e9)]
    rows = sorted(rows, key=lambda r: r["bright"])
    picked, seen = [], set()
    for lo, hi in buckets:
        inb = [r for r in rows if lo <= r["bright"] < hi]
        if not inb:
            continue
        step = max(1, len(inb) // 3)
        for r in inb[::step][:3]:
            if (r["kind"], r["path"]) in seen:
                continue
            picked.append(r); seen.add((r["kind"], r["path"]))
    # top up with the most extreme tables if buckets were thin
    for r in rows:
        if len(picked) >= count:
            break
        if (r["kind"], r["path"]) not in seen:
            picked.append(r); seen.add((r["kind"], r["path"]))
    return picked[:count]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--cycle-len", type=int, default=169,
                    help="register to build at: samples per cycle (169 = C-4, 1070 = 41 Hz)")
    ap.add_argument("--outdir", default=os.path.expanduser(
        "~/.local/share/Renoise/User Library/Instruments/Wavetables/Survey"))
    ap.add_argument("--tsv", default="/tmp/wt_survey.tsv")
    ap.add_argument("--tsv-all", default="/tmp/wt_survey_all.tsv",
                    help="every measured table, for looking at the distribution")
    a = ap.parse_args()

    cands = candidates()
    print(f"{len(cands)} candidate tables on disk; measuring...")
    rows, skipped = [], 0
    for i, (kind, path) in enumerate(cands):
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                rows.append(measure(kind, path))
        except (Exception, SystemExit):
            skipped += 1
        if (i + 1) % 250 == 0:
            print(f"  {i+1}/{len(cands)} measured")
    print(f"measured {len(rows)} tables, skipped {skipped} (no embedded audio)")
    with open(a.tsv_all, "w") as f:
        f.write("kind\tpath\tframes\tcycles\tbright\n")
        for r in sorted(rows, key=lambda r: -r["bright"]):
            f.write(f"{r['kind']}\t{r['path']}\t{r['frames']}\t{r['cycles']}\t{r['bright']:.2f}\n")
    b = np.array([r["bright"] for r in rows]); c = np.array([r["cycles"] for r in rows])
    print(f"brightness across the library: min {b.min():.1f}  p25 {np.percentile(b,25):.1f}  "
          f"median {np.median(b):.1f}  p75 {np.percentile(b,75):.1f}  max {b.max():.1f}")
    print(f"cycle count: {int((c==1).sum())} single-cycle, {int((c>1).sum())} multi-cycle")
    for lo, hi, label in ((0,3,"classic (1-3 H)"),(3,8,"rich (3-8 H)"),(8,20,"bright (8-20 H)"),
                          (20,50,"very bright (20-50 H)"),(50,1e9,"noise-like (50+ H)")):
        n = int(((b >= lo) & (b < hi)).sum())
        print(f"  {label:22s} {n:5d} tables  {100*n/len(rows):5.1f}%")

    picked = choose(rows, a.count)
    f0 = SR / a.cycle_len
    cen_at = lambda b: b * f0
    print(f"\nregister for builds: {a.cycle_len} samples/cycle = {f0:.1f} Hz, "
          f"{a.cycle_len // 2} harmonics available\n")
    print(f"{'#':>2} {'kind':10s} {'frames':>6s} {'cycles':>6s} {'bright':>7s} "
          f"{'centroid@built':>14s} {'file':s}")
    with open(a.tsv, "w") as tsv:
        tsv.write("kind\tpath\tframes\tcycles\tbright\tcycles_len\tcentroid_at_build_hz\n")
        for i, r in enumerate(picked, 1):
            print(f"{i:2d} {r['kind']:10s} {r['frames']:6d} {r['cycles']:6d} {r['bright']:7.1f} "
                  f"{cen_at(r['bright']):11.0f} Hz {os.path.relpath(r['path'], os.path.expanduser('~'))[:52]}")
            tsv.write(f"{r['kind']}\t{r['path']}\t{r['frames']}\t{r['cycles']}\t{r['bright']:.2f}\t"
                      f"{a.cycle_len}\t{cen_at(r['bright']):.0f}\n")
    print(f"\nwrote {a.tsv}")

    if a.build:
        import re
        ok = 0
        for i, r in enumerate(picked, 1):
            name = f"survey {i:02d} {r['kind']} b{r['bright']:.0f}"
            name = re.sub(r"[^\w (),-]+", "_", name)
            cmd = [sys.executable, os.path.join(HERE, "wt_xrni.py"),
                   "--source", r["path"], "--n-frames", "12", "--select", "spectral",
                   "--cycle-len", str(a.cycle_len), "--name", name, "-o", a.outdir]
            b = subprocess.run(cmd, capture_output=True, text=True)
            if b.returncode:
                print(f"  build failed for {r['path']}: {b.stderr.strip().splitlines()[-1:]}")
                continue
            xrni = os.path.join(a.outdir, name + ".xrni")
            v = subprocess.run([sys.executable, os.path.join(HERE, "wt_verify.py"), xrni,
                                "--source", r["path"], "--select", "spectral",
                                "--outdir", os.path.join(a.outdir, "verify")],
                               capture_output=True, text=True).stdout
            good = "0 failed" in v
            ok += good
            print(f"  {'ok ' if good else 'BAD'} {name}")
        print(f"\nbuilt {ok}/{len(picked)} instruments into {a.outdir}")


def _native_first(path):
    """One native frame, for the auto_root measurement (cheap)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fr, _, _ = wt.load_source(path, 0, 0)
    return np.atleast_2d(fr)[0]


if __name__ == "__main__":
    main()
