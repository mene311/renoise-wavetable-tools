# renoise-wavetable-tools

Build gate-scan wavetable `.xrni` instruments for Renoise, then check them.

N frames sit in N sample slots and all sound at once. Each frame has an LFO gate
reading a custom triangle envelope, so one macro ("WT Position") opens one frame at a
time and hands over to the next. Neighbouring triangles sum to 1.0, so you won't hear a
level dip while sweeping.

    macro WT Position -> chain 0 (one frozen LFO per frame) -> frame chains 1..N -> SUM

## Requirements

Python3 with numpy, ffmpeg, xmllint (optional), Renoise 3.5.x.

## Use

```bash
# a folder of single-cycle frames, any length or rate
python3 wt_xrni.py --frames ./frames --name "My WT"

# a Vital table or preset (tables are embedded in both)
python3 wt_xrni.py --source "Basic Shapes.vitaltable" --n-frames 12 --name "Shapes WT" --install

# a Serum-format .wav wavetable
python3 wt_xrni.py --source "Growl.wav" --n-frames 12 --select spectral --name "Growl WT" --install

# audit a build
python3 wt_verify.py "Growl WT.xrni" --source "Growl.wav"
```

Demo with nothing to download: `python3 examples/make_sine_to_square.py /tmp/out`

Load the `.xrni`, hold a note, sweep WT Position. `--install` copies to
`~/.local/share/Renoise/User Library/Instruments/Wavetables/`.

## Flags worth knowing

| flag | default | effect |
|---|---|---|
| `--n-frames` | 12 | 12 is the ceiling; Renoise allows 12 voices per note column |
| `--select` | even | `spectral` keeps the frames that differ most |
| `--cycle-len` | 169 | samples per cycle, which sets the loop pitch and the harmonic ceiling: 169 gives 260 Hz with 84 harmonics, 1070 gives 41 Hz with 535 |
| `--gate-amp` `--gate-offset` `--base-volume` | 1, 0, 0 | full-depth gate; 0.25, -0.375, 1 reproduces the stock templates' shallow morph |


Sources: frame folders, Vital `.vitaltable` (both `wave_data` and `audio_file` storage
forms), `.vital` presets, Serum-format `.wav`, `.npy`. `vitaltable_to_wav.py` converts
the other way.

## What wt_verify checks

Structure, gate sums, provenance against the source, harmonic series against analytic
sine/triangle/saw/square, tuning in cents, and `-frames`, `-sweep`, `-nulltest` renders
for A/B in Renoise.

## Limits

Transposing above the root note aliases. Oversample and Cubic don't remove that
entirely. SampleData binds positionally, so the zip order matters, and the builder
handles it.

## Credits

Mechanism reverse-engineered from instruments shared in the Renoise Discord (Kaidiak)
and from Renoise's `Utility/{2,4,6,12} frame Wavetable Init.xrni`. No sample content here.

MIT.
