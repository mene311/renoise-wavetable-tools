#!/usr/bin/env python3
"""
Self-contained demo: synthesise a classic sine -> triangle -> saw -> square table
(no external sample packs, nothing copyrighted), build a Renoise gate-scan
wavetable instrument from it, and verify the result.

    python3 examples/make_sine_to_square.py [OUTDIR]

then load the .xrni in Renoise, hold a note and sweep the "WT Position" macro.
"""
import os, subprocess, sys, tempfile, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)


def additive(n=2048, harmonics=(1,), odd_only=False, sq=False):
    """One cycle of a band-limited wave from a harmonic series."""
    x = np.arange(n)
    y = np.zeros(n)
    for k, amp in harmonics:
        if odd_only and k % 2 == 0:
            continue
        y += amp * np.sin(2 * np.pi * k * x / n)
    return y / max(1e-9, np.abs(y).max())


def frames(n_frames=12, points=2048):
    """Morph sine -> triangle -> saw -> square across n_frames (linear blends)."""
    N = points
    sine = additive(N, [(1, 1.0)])
    tri = additive(N, [(k, 1.0 / k ** 2) for k in range(1, 64)], odd_only=True)
    saw = additive(N, [(k, 1.0 / k) for k in range(1, 64)])
    square = additive(N, [(k, 1.0 / k) for k in range(1, 64)], odd_only=True)
    anchors = [sine, tri, saw, square]
    out = []
    for i in range(n_frames):
        p = i * (len(anchors) - 1) / (n_frames - 1)
        lo = int(np.floor(p))
        hi = min(lo + 1, len(anchors) - 1)
        t = p - lo
        out.append(anchors[lo] * (1 - t) + anchors[hi] * t)
    return np.array(out)


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "out")
    os.makedirs(outdir, exist_ok=True)

    tmp = tempfile.mkdtemp(prefix="sine2square_")
    for i, f in enumerate(frames()):
        with wave.open(os.path.join(tmp, f"frame {i+1:02d}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
            w.writeframes((np.clip(f / np.abs(f).max(), -1, 1) * 32767).astype("<i2").tobytes())
    print(f"wrote {len(os.listdir(tmp))} frames to {tmp}")

    xrni = os.path.join(outdir, "Sine to Square WT.xrni")
    subprocess.run([sys.executable, os.path.join(TOOLS, "wt_xrni.py"),
                    "--frames", tmp, "--name", "Sine to Square WT",
                    "-o", outdir], check=True)
    print(f"\nbuilt: {xrni}")
    print("verify with:")
    print(f"  python3 {os.path.join(TOOLS, 'wt_verify.py')} \"{xrni}\" --expect basic-shapes")


if __name__ == "__main__":
    main()
