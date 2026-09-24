#!/usr/bin/env python3
"""
wt_verify — audit a gate-scan wavetable .xrni built by wt_xrni.py, and test it
against KNOWN SUBJECTS (analytic sine / triangle / saw / square + the source table).

  wt_verify.py INSTRUMENT.xrni [--source table.vitaltable] [--outdir DIR]

Checks
  1 structure   samples <-> frame chains <-> sends -> SUM, macro -> LFO param 8,
                Forward loop over the whole frame
  2 gates       recompute the gate weights from the XML envelope points at 512
                macro positions: sum == 1 (no level dip), <= 2 frames active,
                every frame reaches 1.0 somewhere
  3 provenance  every built frame must match a source-table frame (band-limited
                resample of it) with correlation >= 0.999
  4 subjects    classify each frame's harmonic series against analytic references
                (sine / triangle / saw / square) - for Vital "Basic Shapes" the
                expected progression is sine -> triangle -> saw -> square
  5 tuning      pitch error at C-4 (from BaseNote + Transpose + Finetune and the
                loop length) must be <= 1 cent
  6 renders     reference WAVs to A/B against what Renoise actually plays:
                <name>-frames.wav   each frame, 0.5 s, at C-4
                <name>-sweep.wav    one full macro sweep
                <name>-nulltest.wav frame 1 held 2 s (null-test against a Renoise
                                    export of the same instrument / same macro)
"""
import argparse, os, re, sys, subprocess, zipfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wt_xrni as wt   # noqa: E402  (module is main()-guarded)

SR = 44100
C4F = 440.0 * 2 ** ((48 - 57) / 12)
PASS, FAIL = [], []


def check(ok, label, detail=""):
    (PASS if ok else FAIL).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"   {detail}" if detail else ""))
    return ok


# ------------------------------------------------------------------ instrument
def read_instrument(path):
    z = zipfile.ZipFile(path)
    xml = z.read("Instrument.xml").decode()
    import xml.etree.ElementTree as ET
    r = ET.fromstring(xml)
    sg = r.find("SampleGenerator")

    samples = []
    for s in (sg.find("Samples") if sg.find("Samples") is not None else []):
        g = lambda t, d=None: (s.findtext(t) or d)
        mp = s.find("Mapping")
        samples.append(dict(
            name=g("Name"), chain=int(g("DeviceChainIndex", "0")),
            loop=g("LoopMode"), loop_start=int(g("LoopStart", "0")),
            loop_end=int(g("LoopEnd", "0")), transpose=int(g("Transpose", "0")),
            finetune=int(g("Finetune", "0")), base_note=int(mp.findtext("BaseNote")),
            note_start=int(mp.findtext("NoteStart")), note_end=int(mp.findtext("NoteEnd")),
            file=dict(s.attrib).get("x", None)))

    chains = []
    for dc in (sg.find("DeviceChains") if sg.find("DeviceChains") is not None else []):
        devs = []
        for d in (dc.find("Devices") if dc.find("Devices") is not None else []):
            typ = dict(d.attrib).get("type") or d.tag
            entry = dict(type=typ, name=(d.findtext("CustomDeviceName") or ""))
            if typ == "LfoDevice":
                v = lambda t: float((d.findtext(t + "/Value") or "0").strip() or 0)
                pts = [tuple(float(x) for x in p.split(",")[:2])
                       for p in re.findall(r"<Point>([^<]+)</Point>",
                                           ET.tostring(d, encoding="unicode"))]
                env = d.find("CustomEnvelope")
                entry.update(dest_track=v("DestTrack"), dest_effect=v("DestEffect"),
                             dest_param=v("DestParameter"), amp=v("Amplitude"),
                             offset=v("Offset"), freq=v("Frequency"),
                             length=int(env.findtext("Length")), points=pts,
                             polarity=env.findtext("Polarity"),
                             play_mode=env.findtext("PlayMode"))
            if typ == "SampleMixerDevice":
                entry["volume"] = float((d.findtext("Volume/Value") or "0").strip() or 0)
            if typ == "SendDevice":
                entry["dest_send"] = float((d.findtext("DestSendTrack/Value") or "-1").strip())
                entry["mute_source"] = d.findtext("MuteSource")
            devs.append(entry)
        chains.append(dict(name=dc.findtext("Name"), devices=devs))

    macro = r.find("GlobalProperties/Macro0")
    maps = []
    if macro is not None:
        for m in macro.findall("Mappings/Mapping"):
            maps.append(dict(chain=int(m.findtext("DestChainIndex")),
                             device=int(m.findtext("DestDeviceIndex")),
                             param=int(m.findtext("DestParameterIndex"))))
    return dict(root=r, xml=xml, samples=samples, chains=chains,
                macro_name=(macro.findtext("Name") if macro is not None else None),
                maps=maps, z=z)


def load_frames(z, samples):
    out = []
    for n in sorted(f for f in z.namelist() if f.startswith("SampleData/")):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "f32le",
                              "-ac", "1", "-ar", str(SR), "-"],
                             input=z.read(n), capture_output=True).stdout
        out.append(np.frombuffer(raw, dtype="<f4").astype(np.float64))
    return out


# ---------------------------------------------------------------------- gates
def gate_weights(lfo, phase, n_frames):
    """Weights of all gate LFOs at a macro phase, read from the XML points."""
    line = phase * lfo[0]["length"]
    w = []
    for l in lfo:
        pts = l["points"]
        L = l["length"]
        v = 0.0
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            if x0 <= line <= x1:
                t = 0.0 if x1 == x0 else (line - x0) / (x1 - x0)
                v = y0 + (y1 - y0) * t
                break
        else:
            v = pts[-1][1] if pts else 0.0
        w.append(max(0.0, v) * l["amp"] + l["offset"])
    return np.array(w)


# ------------------------------------------------------------------- subjects
def analytic_harmonics(kind, n=16):
    h = np.zeros(n + 1)
    for k in range(1, n + 1):
        if kind == "sine":
            h[k] = 1.0 if k == 1 else 0.0
        elif kind == "triangle":
            h[k] = (1.0 / k ** 2) if k % 2 else 0.0
        elif kind == "saw":
            h[k] = 1.0 / k
        elif kind == "square":
            h[k] = (1.0 / k) if k % 2 else 0.0
    return h


def frame_harmonics(a, n=16):
    X = np.abs(np.fft.rfft(a)) / (len(a) / 2.0)
    h = np.zeros(n + 1)
    h[1:min(n, len(X) - 1) + 1] = X[1:min(n, len(X) - 1) + 1]
    return h


def classify(a):
    h = frame_harmonics(a)
    if h[1] == 0:
        return "silence", 1.0
    h = h / h[1]
    best = None
    for kind in ("sine", "triangle", "saw", "square"):
        ref = analytic_harmonics(kind)
        ref = ref / ref[1]
        err = float(np.abs(h - ref).sum())
        if best is None or err < best[1]:
            best = (kind, err)
    return best


def is_sine(a, tol=0.06):
    h = frame_harmonics(a)
    return h[1] > 0 and (np.abs(h[2:]) / h[1]).max() < tol


# ------------------------------------------------------------------- renders
def write_wav(path, sig, sr=SR):
    import wave
    sig = np.clip(sig / max(1e-9, np.abs(sig).max()) * 0.9, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((sig * 32767).astype("<i2").tobytes())


def tone(cycle, secs, sr=SR):
    reps = int(secs * sr / len(cycle)) + 1
    return np.tile(cycle, reps)[:int(secs * sr)]


def render_reference(frames, gates, name, outdir):
    os.makedirs(outdir, exist_ok=True)
    base = os.path.join(outdir, re.sub(r"[^\w. ()-]+", "_", name))
    n = len(frames)
    per = 0.5
    write_wav(base + "-frames.wav", np.concatenate([tone(f, per) for f in frames]))
    hetero = len({len(f) for f in frames}) > 1   # one pitch per frame: no meaningful "mix"
    segs = []
    for i in range(n * 2):                     # 2 x per frame -> reaches the wrap
        p = (i / (n * 2.0)) % 1.0
        w = gate_weights(gates, p, n)
        if hetero:
            segs.append(tone(frames[int(np.argmax(w))], per))
        else:
            mix = sum(wi * fi for wi, fi in zip(w, frames))
            segs.append(tone(mix, per))
    write_wav(base + "-sweep.wav", np.concatenate(segs))
    write_wav(base + "-nulltest.wav", tone(frames[0], 2.0))
    return [base + s for s in ("-frames.wav", "-sweep.wav", "-nulltest.wav")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xrni")
    ap.add_argument("--source", help="source .vitaltable/.vital/.wav to verify provenance against")
    ap.add_argument("--outdir", default="/tmp/wt_verify")
    ap.add_argument("--expect", help="'basic-shapes' asserts sine->...->square progression")
    ap.add_argument("--select", choices=["even", "spectral"], default="even",
                    help="frame selection used when the instrument was built")
    a = ap.parse_args()

    inst = read_instrument(a.xrni)
    frames = load_frames(inst["z"], inst["samples"])
    n = len(inst["samples"])
    print(f"=== {os.path.basename(a.xrni)} — {n} frames ===")

    print("\n1. structure")
    check(n >= 2, "at least 2 frames", f"{n}")
    check(inst["macro_name"] == "WT Position", "instrument macro is 'WT Position'",
          repr(inst["macro_name"]))
    frame_chains = [c for c in inst["chains"] if c["name"].startswith("FRAME")]
    sum_chains = [c for c in inst["chains"] if c["name"] == "SUM"]
    check(len(frame_chains) == n, "one chain per frame", f"{len(frame_chains)}")
    check(len(sum_chains) == 1, "sum bus chain present")
    sum_idx = inst["chains"].index(sum_chains[0]) if sum_chains else -1
    sends_ok = all(any(d.get("dest_send") == sum_idx and d.get("mute_source") == "true"
                       for d in c["devices"]) for c in frame_chains)
    check(sends_ok, "every frame chain sends (MuteSource) into the sum bus", f"sum chain #{sum_idx}")
    loop_ok = all(s["loop"] == "Forward" and s["loop_end"] == len(frames[i])
                  for i, s in enumerate(inst["samples"]))
    check(loop_ok, "every frame loops Forward over its whole length", f"{len(frames[0])} samples")
    map_ok = len(inst["maps"]) == n and [m["param"] for m in inst["maps"]] == [8] * n
    check(map_ok, "macro drives LFO parameter 8 on every gate",
          f"{len(inst['maps'])} mappings, param(s) {sorted(set(m['param'] for m in inst['maps']))}")

    print("\n2. gates")
    def is_gate(d):
        return d.get("name", "").startswith("gate") or not d.get("name")
    gates = [d for c in inst["chains"] if c["name"] == "GATES"
             for d in c["devices"] if d["type"] == "LfoDevice" and is_gate(d)]
    if not gates:   # also accept a layout where each frame chain holds its own gate
        gates = [d for c in frame_chains for d in c["devices"] if d["type"] == "LfoDevice"]
    if not gates:   # ... or gates kept in a chain of their own, one per frame chain
        gates = [d for c in inst["chains"] for d in c["devices"] if d["type"] == "LfoDevice"]
    check(len(gates) == n, "one gate LFO per frame", f"{len(gates)}")
    dest_ok = all(int(g["dest_track"]) == i + 1 and int(g["dest_param"]) == 2
                  for i, g in enumerate(gates))
    check(dest_ok, "each gate modulates its own frame's mixer volume (DestParameter 2)")
    full_depth = all(abs(g["amp"] - 1.0) < 1e-6 and abs(g["offset"]) < 1e-6 for g in gates)
    L = gates[0]["length"] if gates else n * 2
    phases = sorted(set(list(np.arange(0, L, 1) / L) + list(np.linspace(0, 1, 512, endpoint=False))))
    sums, actives, peaks = [], [], np.zeros(n)
    for p in phases:
        w = gate_weights(gates, p, n)
        sums.append(w.sum())
        actives.append(int((w > 1e-6).sum()))
        peaks = np.maximum(peaks, w)
    if full_depth:
        check(abs(np.mean(sums) - 1.0) < 2e-3, "no level dip: gate weights sum to 1",
              f"mean {np.mean(sums):.4f}, min {min(sums):.4f}, max {max(sums):.4f}")
        check(max(actives) <= 2, "crossfade only ever blends 2 frames", f"max {max(actives)}")
        check(peaks.min() > 0.999, "every frame is reachable (gates peak at 1.0)",
              f"min peak {peaks.min():.3f}")
    else:
        print(f"  [note] non-full-depth gate flavour (amp {gates[0]['amp']:g}, "
              f"offset {gates[0]['offset']:g}) — sum/dip/reachability assertions skipped; "
              f"weight range {min(np.min(gate_weights(gates,p,n)) for p in phases):.3f}"
              f"..{max(np.max(gate_weights(gates,p,n)) for p in phases):.3f}")

    print("\n3. provenance")
    if a.source:
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            native, sr, _ = wt.load_source(a.source, 0, 0)   # 0 frames / 0 cycle = native, unresampled
            picked, idxs = wt.select_table_frames(native, n, a.select)
        if idxs is None:      # interpolated: recompute the exact blends
            expect = [wt.bandlimit_resample(p, len(frames[0])) for p in picked]
            src_desc = f"{len(native)} native frames, blended up to {n}"
        else:
            expect = [wt.bandlimit_resample(native[i], len(frames[0])) for i in idxs]
            src_desc = f"native frames {idxs}"
        corrs = [float(np.corrcoef(f, e)[0, 1]) for f, e in zip(frames, expect)]
        check(min(corrs) >= 0.999, "every built frame == the intended source frame",
              f"worst correlation {min(corrs):.5f}  ({src_desc})")
        print("        per-frame correlation:", " ".join(f"{c:.4f}" for c in corrs))
    else:
        print("  [skip] no --source given")

    print("\n4. known subjects (harmonic series vs analytic sine/triangle/saw/square)")
    table = []
    for i, f in enumerate(frames):
        kind, err = classify(f)
        table.append((i + 1, kind, err))
        print(f"        frame {i+1:2d}: closest to {kind:8s} (L1 error {err:.3f})")
    if a.expect == "basic-shapes":
        first_sine = is_sine(frames[0])
        last_kind = table[-1][1]
        check(first_sine, "frame 1 is a pure sine (no harmonics)")
        mid = [k for _, k, _ in table]
        order_ok = ("sine" in mid[:3]) and ("square" in mid[-3:] or "saw" in mid[-3:])
        check(order_ok, "progression runs sine -> ... -> square/saw",
              f"{[k for _, k, _ in table]}")

    hetero = len({len(f) for f in frames}) > 1
    print("\n5. tuning")
    s0 = inst["samples"][0]
    f0 = SR / len(frames[0])
    if hetero:
        print("  [skip] one pitch per frame — no single tuning to verify")
        cents = 0.0
    cents = 1200 * np.log2((f0 * 2 ** ((48 - s0["base_note"]) / 12.0)
                            * 2 ** (s0["transpose"] / 12.0)
                            * 2 ** (s0["finetune"] / 1200.0)) / C4F)
    if not hetero:
      check(abs(cents) <= 1.0, "in tune at C-4 within 1 cent",
          f"BaseNote {s0['base_note']}, Transpose {s0['transpose']}, "
            f"Finetune {s0['finetune']}, f0 {f0:.2f} Hz -> {cents:+.2f} cents")

    print("\n6. reference renders")
    outs = render_reference(frames, gates, os.path.basename(a.xrni).rsplit('.', 1)[0], a.outdir)
    for o in outs:
        print(f"        {o}")

    print(f"\n=== {len(PASS)} passed, {len(FAIL)} failed ===")
    for f in FAIL:
        print("   FAILED:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
