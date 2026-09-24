#!/usr/bin/env python3
"""
wt_catalogue — measure every wavetable on disk, cluster them by timbre (features taken
from the single-cycle content), then build instruments into one folder per cluster.

    wt_catalogue.py --scan                features + clusters -> catalogue TSV
    wt_catalogue.py --scan --build        also build every table into its cluster folder

Features per table (median over the frames a build would use):
  bright    spectral centroid in harmonics (how bright vs its own pitch)
  odd       share of energy in odd harmonics (square/clarinet vs saw/string)
  slope     log amplitude vs log harmonic fit (-1 saw, -2 triangle, ~0 flat/noisy)
  flat      spectral flatness (geometric/arithmetic mean: 0 tonal, 1 noise)
  h1        fundamental's share of the energy (how close to a sine)
  crest     peak / rms of the cycle (peakiness)
  zcr       mean absolute difference (roughness)
"""
import argparse, contextlib, glob, hashlib, io, os, random, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wt_xrni as wt   # noqa: E402

V = os.path.expanduser("~/.local/share/vital")
PACKS = os.path.expanduser("~/Projects/renoise/wavetable-packs")
LIB = os.path.expanduser("~/.local/share/Renoise/User Library/Instruments/Wavetables")


def candidates():
    out = []
    for root, _, files in os.walk(V):
        for f in files:
            if f.endswith((".vitaltable", ".vital")):
                out.append((os.path.relpath(os.path.join(root, f), V),
                            os.path.join(root, f)))
    for pack, ext in ((os.path.join(PACKS, "esw"), ".wav"),
                      (os.path.join(PACKS, "basstables-v1"), ".wav"),
                      (os.path.join(PACKS, "ops7"), ".wav")):
        for root, _, files in os.walk(pack):
            for f in files:
                if f.endswith(ext):
                    out.append((os.path.relpath(os.path.join(root, f), PACKS),
                                os.path.join(root, f)))
    return out


def features(path, probe=6, table=0):
    src = {"groups": None}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        fr, sr, _ = wt.load_source(path, probe, 0, table=table)
    fr = np.atleast_2d(fr)
    cyc = wt.table_cycles(fr)
    picked, _ = wt.select_table_frames(fr, probe, "even")
    picked = np.atleast_2d([wt.one_cycle(f, cyc) for f in picked])
    rows = []
    for a in picked:
        n = len(a)
        X = np.abs(np.fft.rfft(a - a.mean()))
        p = X[1:] ** 2
        if p.sum() <= 0:
            continue
        k = np.arange(1, len(X))
        bright = float((k * p).sum() / p.sum())
        odd = float(p[0::2].sum() / p.sum())              # harmonics 1,3,5...
        h1 = float(p[0] / p.sum())
        with np.errstate(divide="ignore"):
            lg = np.log(p + 1e-20)
        sl = np.polyfit(np.log(k[:64]), lg[:64], 1)[0]
        mag = X[1:] + 1e-12
        flat = float(np.exp(np.log(mag).mean()) / mag.mean())
        rms = float(np.sqrt((a ** 2).mean()))
        crest = float(np.abs(a).max() / rms) if rms else 0.0
        rows.append((bright, odd, sl, flat, h1, crest, float(np.abs(np.diff(a)).mean())))
    if not rows:
        raise ValueError("no usable frames")
    fp = hashlib.sha1(np.round(picked[:, :min(512, picked.shape[1])], 3).tobytes()).hexdigest()
    return np.median(np.array(rows), axis=0), fp


FEATS = ["bright", "odd", "slope", "flat", "h1", "crest", "zcr"]


def name_cluster(c):
    """Turn a cluster centroid into something a musician would recognise."""
    b, odd, sl, fl, h1, cr, zc = c
    if b > 60 or fl > 0.45:
        return "noise and texture"
    if b > 25:
        return "harsh and metallic"
    if fl > 0.25 and b > 12:
        return "gritty and distorted"
    if h1 > 0.55 and b < 3:
        return "sine and sub"
    if odd > 0.85 and sl < -1.4 and b < 6:
        return "triangle and soft"
    if odd > 0.8 and sl > -1.4 and b < 12:
        return "square and pulse"
    if odd < 0.6 and sl > -1.6:
        return "saw and bright"
    if b < 12:
        return "additive and organ"
    return "digital and formant"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--probe", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tsv", default="~/.local/share/wt_catalogue.tsv")
    ap.add_argument("--outdir", default="/tmp/wt_catalogue_out")
    a = ap.parse_args()

    cands = candidates()
    if a.limit:
        cands = cands[:a.limit]
    print(f"{len(cands)} sources; measuring features...")

    rows, skipped, seen, dupes = [], 0, set(), 0
    for i, (tag, path) in enumerate(cands, 1):
        try:
            f, fp = features(path, a.probe)
        except (Exception, SystemExit):
            skipped += 1
            continue
        if fp in seen:               # same waveform embedded in another file
            dupes += 1
            continue
        seen.add(fp)
        rows.append((tag, path, f))
        if i % 200 == 0:
            print(f"  {i}/{len(cands)}: {len(rows)} unique, {dupes} duplicates, {skipped} unusable")

    print(f"unique tables: {len(rows)}  (duplicates skipped: {dupes}, unusable: {skipped})")
    F = np.array([r[2] for r in rows])
    X = (F - F.mean(0)) / (F.std(0) + 1e-9)
    try:
        from sklearn.cluster import KMeans
        km = KMeans(n_clusters=a.k, n_init=10, random_state=0).fit(X)
        labels = km.labels_
        cents = km.cluster_centers_ * (F.std(0) + 1e-9) + F.mean(0)
    except ImportError:                                     # crude fallback
        labels = np.digitize(F[:, 0], np.percentile(F[:, 0], np.linspace(0, 100, a.k + 1)[1:-1]))
        cents = np.array([F[labels == c].mean(0) if (labels == c).any() else F.mean(0)
                          for c in range(a.k)])
    names = {c: name_cluster(cents[c]) for c in range(len(cents))}
    # make folder names unique
    seen, uniq = {}, {}
    for c in range(len(cents)):
        nm = names[c]
        seen[nm] = seen.get(nm, 0) + 1
        uniq[c] = nm if seen[nm] == 1 else f"{nm} {seen[nm]}"

    tsv = os.path.expanduser(a.tsv)
    os.makedirs(os.path.dirname(tsv), exist_ok=True)
    with open(tsv, "w") as f:
        f.write("cluster\tname\tsource\t" + "\t".join(FEATS) + "\n")
        for (tag, path, feats), lab in zip(rows, labels):
            f.write(f"{lab}\t{uniq[lab]}\t{path}\t"
                    + "\t".join(f"{v:.3f}" for v in feats) + "\n")
    print(f"\nwrote {tsv}\n")
    print(f"{'cluster':28s} {'n':>4s} {'bright':>7s} {'odd':>5s} {'slope':>6s} "
          f"{'flat':>5s} {'h1':>5s} {'crest':>6s}")
    for c in np.argsort(-np.array([ (labels==i).sum() for i in range(len(cents))])):
        n = int((labels == c).sum())
        b, odd, sl, fl, h1, cr, zc = cents[c]
        print(f"{uniq[c]:28s} {n:4d} {b:7.1f} {odd:5.2f} {sl:6.2f} {fl:5.2f} {h1:5.2f} {cr:6.2f}")

    if a.build:
        import shutil, subprocess, tempfile
        os.makedirs(a.outdir, exist_ok=True)
        listing = os.path.join(a.outdir, "sources.txt")
        with open(listing, "w") as f:
            for (tag, path, _), lab in zip(rows, labels):
                nm = uniq[lab] + " / " + os.path.splitext(os.path.basename(path))[0]
                nm = nm.replace("/", "-").replace("\t", " ")
                f.write(f"{path}\t{nm}\n")
        print(f"\nbuilding {len(rows)} instruments in batch...")
        subprocess.run([sys.executable, os.path.join(HERE, "wt_xrni.py"),
                        "--sources-from", listing, "--dedupe", "--fast", "--install",
                        "-o", a.outdir], check=False)
        # sort the installed instruments into their timbre folders
        man = os.path.join(a.outdir, "wt_build_manifest.json")
        by_src = {r[1]: uniq[l] for r, l in zip(rows, labels)}
        moved = 0
        if os.path.exists(man):
            import json
            for e in json.load(open(man)):
                src = e["source"]
                cat = by_src.get(src)
                if not cat:
                    continue
                f = os.path.join(LIB, e["xrni"])
                if os.path.exists(f):
                    d = os.path.join(LIB, cat)
                    os.makedirs(d, exist_ok=True)
                    shutil.move(f, os.path.join(d, e["xrni"]))
                    moved += 1
        print(f"filed {moved} instruments into timbre folders under {LIB}")


if __name__ == "__main__":
    main()
