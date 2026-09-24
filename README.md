# renoise-wavetable-tools

Build **gate-scan wavetable instruments** (`.xrni`) for Renoise from any wavetable
source, then verify them against analytic references.

A gate-scan wavetable instrument is a *sample-based* wavetable oscillator: N frames
live in N sample slots, all sounding at once, each behind its own gate. One instrument
macro ("WT Position") slides the gates so exactly one frame sounds at a time,
cross-fading to the next — so you get a continuous wavetable sweep with no VSTs.

```
Macro "WT Position"
        |
        v
  chain 0  GATES ── one FROZEN LFO per frame ── custom unipolar envelope,
        │            parameter 8 = LFO position, one triangle per frame
        │            (neighbouring triangles sum to exactly 1.0)
        v
  chain 1  FRAME 01   sample 1 ── SampleMixer(volume 0) ── gate LFO ── Send ┐
  chain 2  FRAME 02   sample 2 ── SampleMixer(volume 0) ── gate LFO ── Send ┤ MuteSource
   ...                                                                    ┤
  chain N  FRAME NN   sample N ── SampleMixer(volume 0) ── gate LFO ── Send ┘
  chain N+1  SUM      SampleMixer ── instrument output
```

## Requirements

- Python 3.9+, `numpy`
- `ffmpeg` (frame → FLAC encoding)
- `xmllint` (optional, schema validation; Renoise's `Schemas/RenoiseInstrument34.xsd`)
- Renoise 3.5.x (instrument `doc_version="34"`)

## Quick start

```bash
# 1. from a folder of single-cycle frames (any length, any sample rate)
python3 wt_xrni.py --frames ./my_frames --name "My Wavetable WT"

# 2. from a Vital wavetable (.vitaltable) or a .vital preset (tables are embedded)
python3 wt_xrni.py --source ~/.local/share/vital/Factory/Wavetables/Basic/"Basic Shapes.vitaltable" \
                   --n-frames 12 --name "Basic Shapes WT" --install

# 3. from a Serum-format wavetable .wav (N frames x 2048 samples)
python3 wt_xrni.py --source "ESW Growl - Dark Matter.wav" --n-frames 12 --select spectral \
                   --root auto --name "Growl WT" --install

# analyse a source: brightness, suggested root, keyboard→Hz map
python3 wt_xrni.py --source SOMETHING --report

# audit what you built
python3 wt_verify.py "My Wavetable WT.xrni" --source ./my_frames --select even
```

Self-contained demo (synthesises a sine→triangle→saw→square table, nothing downloaded):

```bash
python3 examples/make_sine_to_square.py /tmp/out
```

Load the resulting `.xrni` in Renoise, hold a note, sweep **WT Position**.
`--install` copies it to `~/.local/share/Renoise/User Library/Instruments/Wavetables/`.

## Sources supported

| input | notes |
|---|---|
| frame directory | one `.wav`/`.flac` per frame, equal length, or use `--mixed-lengths` |
| Vital `.vitaltable` | both storage forms: `wave_data` (base64 float32) and `audio_file` (base64 int16 PCM chunked by `window_size`) |
| Vital `.vital` preset | its wavetable is embedded inline → `--table N` to pick one |
| Serum-format `.wav` | N frames × 2048 samples; frame size auto-detected |
| `.npy` | array `(n_frames, n_samples)` |

`vitaltable_to_wav.py TABLE.vitaltable -o DIR [--frames native,64,256]` converts the
other way: Vital → Serum-format `.wav` wavetable.

## Options that matter

| flag | default | what it does |
|---|---|---|
| `--n-frames` | 12 | how many frames to use (Renoise allows **12 voices per note column** — the hard cap) |
| `--select` | `even` | `spectral` = farthest-first pick of the frames that differ most (better morphs) |
| `--cycle-len` | 169 | samples per cycle ⇒ **sets the root note and the harmonic ceiling** (169 = C-4 / 84 harmonics; 338 = C-3 / 168; 1070 = 41 Hz / 535) |
| `--root auto` | off | pick the cycle length from the material's brightness so it sits in a usable register |
| `--target-centroid` | 600 | target audible centroid in Hz for `--root auto` |
| `--spacing` | 2 | envelope lines between gate peaks (crossfade width) |
| `--gate-amp` / `--gate-offset` / `--base-volume` | 1.0 / 0.0 / 0.0 | full-depth gate. `0.25 / -0.375 / 1.0` reproduces the official templates' shallow "morph" |
| `--install` | off | copy into the Renoise User Library |

### Choosing a root

Frames are single cycles, so the cycle length decides both the pitch and how much
high-frequency detail fits. Bright material (growls, bass tables) sounds shrill when
rooted at C-4 — measure it instead of guessing:

```
$ python3 wt_xrni.py --source "ESW Growl - Dark Matter.wav" --report
    brightness            62.0 harmonics (centroid / fundamental)
    cycle length        1070 samples -> fundamental   41.21 Hz (~note 16), 535 harmonics max
    centroid at root       2555 Hz
    keyboard map        C-1 65.4 Hz | C-2 130.8 Hz | C-3 261.7 Hz | C-4 523.4 Hz ...
```

`brightness ≈ 1–3` = classic shapes (fine at C-4), `5–20` = bright bass/growl
(shift down an octave or two), `>30` = noise-like.

## Verification

`wt_verify.py` audits a built instrument and checks it against the source plus
analytic references:

```
1 structure   samples ↔ frame chains ↔ sends → SUM, macro → LFO param 8, Forward loop
2 gates       gate weights sum to 1 (no level dip), ≤2 frames active, all frames reachable
3 provenance  every built frame == the intended source frame (correlation ≥ 0.999)
4 subjects    each frame's harmonic series vs analytic sine / triangle / saw / square
5 tuning      pitch error at C-4 ≤ 1 cent
6 renders     reference WAVs to A/B against Renoise: -frames, -sweep, -nulltest
```

The `-nulltest.wav` file is for a real null test: set `WT Position` to a frame's peak,
hold C-4, export from Renoise, subtract.

## Gotchas

- **12 frames max** per instrument (voices per note column). Longer tables get sampled
  down — use `--select spectral` so the frames you keep actually differ.
- **Transposing up aliases** (rate > 1). `Oversample` + Cubic interpolation are enabled;
  playing near the base note is cleanest.
- **SampleData is bound positionally** — the zip's `SampleData/SampleNN …` order must
  match the `<Sample>` order, which the builder guarantees.
- `--mixed-lengths` is only for special cases (e.g. one pitch per frame); loops then have
  no single tuning.

## Credits

The gate-scan mechanism was reverse-engineered from instruments shared in the Renoise
Discord community (Kaidiak's wavetables) and from Renoise's own
`Library/Instruments/Utility/{2,4,6,12} frame Wavetable Init.xrni` templates
(by slujr / zensphere). This repository contains only the tooling — no sample content.

## License

MIT — see `LICENSE`.
