#!/usr/bin/env python3
"""
vitaltable_to_wav — export a Vital wavetable (.vitaltable, or a .vital preset's
embedded table) as a SERUM-FORMAT wavetable .wav: N frames x 2048 samples,
32-bit float, 44100 Hz. Loadable by Serum, Vital (import), Ableton Wavetable,
Kilohearts, Pigments ... and directly playable/choppable in Renoise.

  vitaltable_to_wav.py TABLE.vitaltable [-o OUTDIR] [--frames 8,64,256] [--frame-size 2048]

Vital stores audio two ways (both handled):
  * "Wave Source"       -> keyframes[].wave_data = base64 float32 frames
  * "Audio File Source" -> component.audio_file = base64 int16 PCM chunked by window_size
"""
import argparse, base64, json, os, subprocess, sys, tempfile
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wt_xrni as wt   # noqa: E402


def native_frames(path, table=0):
    d = json.load(open(path))
    if "settings" in d:
        wts = (d["settings"] or {}).get("wavetables") or []
        if not wts:
            raise SystemExit(f"{path}: preset embeds no wavetable")
        d = wts[table]
    for g in d.get("groups") or []:
        for c in g.get("components") or []:
            fr, sr = wt._decode_vital_component(c)
            if fr is not None:
                return fr, sr, c.get("type")
    raise SystemExit(f"{path}: no decodable audio component")


def interp_to(frames, n):
    """Phase-aligned linear blend of a frame table up to n frames (or native if n <= len)."""
    N = len(frames)
    if n <= N:
        idxs = [round(i * (N - 1) / max(1, n - 1)) for i in range(n)]
        return frames[idxs], idxs
    out = []
    for i in range(n):
        P = i * (N - 1) / (n - 1)
        lo = int(np.floor(P)); hi = min(lo + 1, N - 1); t = P - lo
        out.append(frames[lo] * (1 - t) + frames[hi] * t)
    return np.array(out), None


def write_wt_wav(path, frames, sr=44100):
    flat = np.asarray(frames, dtype="<f4").ravel()
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tf:
        tf.write(flat.tobytes()); raw = tf.name
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(sr),
                    "-ac", "1", "-i", raw, "-c:a", "pcm_f32le", path], check=True)
    os.unlink(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tables", nargs="+")
    ap.add_argument("-o", "--outdir", default=".")
    ap.add_argument("--frames", default="native,64,256",
                    help="comma list of frame counts to write ('native' = as stored)")
    ap.add_argument("--table", type=int, default=0, help="table index inside a .vital preset")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    for t in a.tables:
        frames, sr, kind = native_frames(t, a.table)
        base = os.path.splitext(os.path.basename(t))[0]
        print(f"{base}: {len(frames)} native frames x {frames.shape[1]} samples "
              f"@ {sr} Hz ({kind})")
        for spec in a.frames.split(","):
            n = len(frames) if spec.strip() == "native" else int(spec)
            out, idxs = interp_to(frames, n)
            name = f"{base} ({n}f).wav" if spec.strip() != "native" else f"{base} ({n}f native).wav"
            p = os.path.join(a.outdir, name)
            write_wt_wav(p, out, sr)
            print(f"   -> {p}  ({len(out)} frames x {out.shape[1]} samples, "
                  f"32-bit float, {os.path.getsize(p)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
