# renoise-wavetable-tools

Build wavetable instruments for Renoise. Load one, hold a note, turn a single knob, and
the sound slides from one wave shape to the next, the way a wavetable oscillator does in
Serum, Vital or Massive. It plays on the sampler you already have, so there's no plugin and no CPU spike.

## What it does

A wavetable is a pile of single-cycle waves: one cycle of a sine, then something more
triangle-ish, then a saw, then a square, and so on, sometimes a few hundred of them. A
wavetable synth reads one at a time and morphs between them as you move the position.

Renoise has no wavetable oscillator. It has sample slots, and those stack.

Put every frame in its own slot, let them all play, then close them one by one as you
turn a knob. That's all these instruments are. Each frame gets its own gate, which is a
slow LFO with a triangle drawn on it. Turning the WT Position macro opens the current frame while
closing the previous one, and the triangles are sized so neighbours always add up to 1.0,
so the level stays put between frames. You get a morph that walks the whole table instead
of a crossfade between two waves.

Feed it a classic shapes table and you get sine to square. Feed it a growl table and you
get growl sweeps. FM tables, chip wavetables, whatever waves you have lying around.

## Use

Build an instrument from whatever source you have:

```bash
# a folder of single-cycle waves
python3 wt_xrni.py --frames ./frames --name "My WT"

# a Vital wavetable or preset
python3 wt_xrni.py --source "Basic Shapes.vitaltable" --name "Shapes WT" --install

# a wavetable .wav from a Serum-style pack
python3 wt_xrni.py --source "Growl.wav" --n-frames 12 --name "Growl WT" --install
```

`--install` puts it in Renoise's User Library, under Instruments/Wavetables. In Renoise,
load it on a track, hold a note, and turn macro 1, WT Position, in the instrument panel.
Automate that macro and the sweep moves on its own.

Nothing to hand? `python3 examples/make_sine_to_square.py /tmp/out` builds a sine to
square instrument from scratch, to hear what the format does.

## Knobs that change the sound

| flag | default | what it does |
|---|---|---|
| `--n-frames` | 12 | how many frames go in. Twelve is the ceiling in Renoise, so a long table gets sampled down to twelve positions |
| `--cycle-len` | 169 | how many samples make one cycle. Shorter sits higher and brighter, longer sits lower and fuller |
| `--select spectral` | off | picks the frames that differ most from each other, which makes a more obvious sweep than taking every Nth frame |
| `--gate-amp`, `--gate-offset`, `--base-volume` | 1, 0, 0 | gate depth. One opens a frame fully and closes the last one, lower values blend frames instead of soloing them |

## Sources it reads

Folders of single-cycle waves, Vital `.vitaltable` files and `.vital` presets (the waves
are in there, base64 encoded), Serum-format `.wav` wavetables, and `.npy` arrays.
Need the opposite? `vitaltable_to_wav.py` writes a Serum-format `.wav` from a
Vital table.

## Checking your build

`wt_verify.py` reads an instrument back and tells you if it's honest: the frames are the
ones from your source, one frame sounds at a time, the gates add up to 1.0 so sweeps don't
dip, and the tuning sits within a cent. It also renders reference audio, a sweep, the
frames one by one, a single frame held, to compare against what Renoise plays.

## Limits

Renoise allows twelve voices per note column, so twelve frames per instrument. Play far
above the note the frames were cut for and the top end gets gritty, which is how samplers behave.

## Credits

The gating trick came from instruments Kaidiak shared in the Renoise Discord. Renoise
ships a plainer version of the same idea as `Utility/2, 4, 6 and 12 frame Wavetable Init`.
No sample content lives in this repo.

MIT.
