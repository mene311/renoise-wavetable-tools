# renoise-wavetable-tools

Build wavetable instruments for Renoise. Load one, hold a note, turn macro 1, and the
sound morphs through the table the way a wavetable oscillator does in Serum or Vital.
It runs on the sampler, so there's no plugin and no CPU spike.

## What it does

Renoise has no wavetable oscillator. So each frame ends up as its own sample, all of them
playing at once, each one behind a gate.

One macro slides the gates: one frame sounds, then the next takes over. The triangles add
up to 1.0, so the level holds steady between frames.

## How the instrument is built inside Renoise

It's a chain layout, visible in the instrument editor's chain list (the same matrix you
get with Sample FX):

    GATES      one slow LFO per frame, each reading a custom triangle envelope and
               pointing at one frame's mixer volume. Macro 1 "WT Position" drives
               parameter 8, the position, on all of them at once.
    FRAME 01   the frame's sample -> mixer (volume 0) -> send to SUM, source muted
    FRAME 02   same idea, one chain per frame
    ...
    SUM        plain mixer, this is the instrument's output

The gates are the whole trick. A frozen LFO reads its envelope like a lookup table, which
turns the macro into a wavetable position. Twelve frames fit, because Renoise allows
twelve voices per note column.

## Use

```bash
# a folder of single-cycle waves
python3 wt_xrni.py --frames ./frames --name "My WT"

# a Vital wavetable or preset
python3 wt_xrni.py --source "Basic Shapes.vitaltable" --name "Shapes WT" --install

# a wavetable .wav from a Serum-style pack
python3 wt_xrni.py --source "Growl.wav" --n-frames 12 --name "Growl WT" --install
```

`--install` copies it to Renoise's User Library, under Instruments/Wavetables. Load it on
a track, hold a note, turn the macro. Automate the macro and the sweep moves on its own.

Nothing to hand? `python3 examples/make_sine_to_square.py /tmp/out` builds a sine to
square instrument from scratch, to hear what the format does.

## Knobs that change the sound

| flag | default | what it does |
|---|---|---|
| `--n-frames` | 12 | how many frames go in. Twelve is the ceiling, so a long table gets sampled down to twelve positions |
| `--cycle-len` | 169 | how many samples make one cycle. Shorter sits higher and brighter, longer sits lower and fuller |
| `--select spectral` | off | picks the frames that differ most from each other, which makes a more obvious sweep than taking every Nth frame |
| `--gate-amp`, `--gate-offset`, `--base-volume` | 1, 0, 0 | gate depth. One opens a frame fully and closes the last one, lower values blend frames instead of soloing them |

## Sources it reads

Folders of single-cycle waves, Vital `.vitaltable` files and `.vital` presets (the waves
are in there, base64 encoded), Serum-format `.wav` wavetables, and `.npy` arrays.
Need the opposite? `vitaltable_to_wav.py` writes a Serum-format `.wav` from a Vital table.

## One caveat

Pitch is only ever as good as the single cycle. A table whose energy sits on a harmonic
other than the first reads an octave or a twelfth away from the note you play, and playing
far from the base note shifts the top end. That is what a sampler does with one-cycle
content, not something the build fixes.

## Credits

The gating trick came from instruments Kaidiak shared in the Renoise Discord. Renoise
ships a plainer version of the same idea as `Utility/2, 4, 6 and 12 frame Wavetable Init`,
by slujr (zensphere). Thanks to both. No sample content lives in this repo.

MIT.
