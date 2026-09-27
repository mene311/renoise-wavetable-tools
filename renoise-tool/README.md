# Wavetable Instrument Builder

A Renoise tool that turns a wavetable sitting in a sample slot into a gate-scan wavetable
instrument. No Python involved.

## Install

Copy `com.meneses.WavetableBuilder.xrnx` into Renoise's tool folder and restart, or drag it onto
Renoise:

```
~/.local/share/Renoise/V3.5.4/Scripts/Tools/                   Linux
~/Library/Application Support/Renoise/V3.5.4/Scripts/Tools/    macOS
%APPDATA%\Renoise\V3.5.4\Scripts\Tools\                        Windows
```

It shows up as **Tools → Wavetable Instrument Builder**, and takes a keybinding.

## Use

Load your wavetable as a sample. A Serum-style `.wav` wavetable of N frames, 2048 samples each,
lands in one sample slot in Renoise. Select that sample, run the tool, pick how many frames you
want, then Build and save. It writes the `.xrni`, loads it, and it is ready to play.

## What it builds

One sample slot per frame, a gate LFO per frame whose triangle envelopes add up to 1.0, and macro
1 named WT Position walking the gate LFO positions. Turn on the sweep option and it also drops in
an inactive SWEEP LFO, a HYDRA, the Instrument Macros device and a Key Tracker on the LFO's reset,
wired in two places only: LFO to Hydra input, Hydra output 1 to macro 1. Everything else is left
for you to point where you want.

## Why it writes a file

`renoise.InstrumentMacro.mappings` is read-only in the scripting API, so a tool cannot create the
macro mapping that walks the table, and instrument chains cannot be automated by anything except a
macro. The macro therefore has to exist in the file, which is why the tool writes a complete
`.xrni` and loads it with `renoise.app():load_instrument()`.

## Edge cases, and what happens

Twelve frames is the ceiling, because Renoise allows twelve voices per note column and a
thirteenth frame would vanish without warning. If the frame count you ask for is below the number
of frames in the table, the tool picks that many spread evenly across it, both ends included. If
the sample length does not divide evenly into frames, the tail is dropped and the report says how
many samples went. Buffer indices are 1-based per the API docs, so the reader starts at 1. Stereo
sources use the left channel, and the report names the channel count so it is not a silent choice.

### Finding the frame size, and slicing one cycle

Renoise's sample buffer exposes a length and a rate and nothing else — no frame size, no file
metadata — so the tool works the frame size out from the audio: the largest standard size that
divides the sample evenly, 2048 first and downwards. That is what `frames_from_serum_wav()` does
in `wt_xrni.py`, and the two builders have to agree, or the same file would build differently
here and there.

Then each frame is sliced to a single cycle and resampled to a common length, band-limited. Two
things go wrong without that, and both are silent — the instrument builds and simply sounds bad:

- A frame holding several cycles plays sharp by that factor, because the instrument declares one
  cycle's pitch for a waveform that repeats several times.
- A real frame count different from the one asked for means every slice lands mid-cycle, so each
  gate step is a discontinuity. A 256-frame table built at 12 frames used to give 43,690-sample
  blocks straddling 85 cycles; it now gives exact 512-sample single cycles.

An earlier version counted zero crossings, warned that the frames held more than one cycle, and
wrote the instrument anyway. The report now states the source frame size, the cycles per frame and
the frames picked, so an unusual table explains itself.

Pitch comes from the final cycle length: a cycle of `L` samples at rate `sr` has a natural
frequency of `sr / L`, and the tool picks the nearest Renoise note plus the cents offset. The sign
matters, because Renoise plays a sample at `2^((played - base_note)/12) · 2^(transpose/12) ·
2^(finetune/1200)`, so a sample that is flat of its note needs a positive finetune. A 169-sample
cycle at 44.1 kHz comes out at BaseNote 48, Finetune +4, matching the Python builder.

Cycles long enough to map below note 0 get clamped, the cents are still computed from the
unclamped note, and the report says so. Sample names are escaped, so a sample called
`Test & <Table>` cannot break the XML.

Sample data goes in as uncompressed WAV and the archive is store-only, so the file is bigger than
the Python builder's FLAC. The extension is never referenced in the XML, and Renoise opens WAV from
inside an instrument container, so this is only a size difference.

## Verification

`../tests/run.sh` runs four suites. `dsp_test.lua` covers the cycle analysis against shapes with
known answers: cycle detection at 2, 3, 4 and 8 cycles and at lengths that are not powers of two,
one-cycle extraction, and band-limited resampling — including that it drops harmonics rather than
folding them back as aliasing, which is what a naive interpolation gets wrong.
`cycle_pipeline_test.lua` drives a 256-frame, 4-cycle table through the whole pipeline and asserts
every written frame is exactly one cycle and that they all share a length. `old_vs_new.lua` prints
the old and new results for that table side by side.


The generated XML validates against Renoise's own `Schemas/RenoiseInstrument34.xsd`, the same check
the Python builder passes. The tuning maths agrees with `wt_xrni.py` on 169, 338 and 1070 sample
cycles. The zip passes `unzip -t` and Python's `zipfile.testzip()`, with CRC32 checked against
`zlib` for empty, ASCII and 256 byte payloads. The Lua files are syntax checked with `luac -p` and
load under both LuaJIT and Lua 5.4.

Three review passes went over it, reading the API type docs, comparing the XML and zip against the
validated Python output, and re-deriving the tuning maths. They found a double nested `<Value>`
inside every parameter block (152 of them, reject level), names inserted without escaping, finetune
computed from the clamped note, a popup read as a label instead of an index, `vb.text` instead of
`vb:text`, child views passed positionally instead of in `views`, a probe of an undocumented frame
index, a CRC32 built with subtraction where XOR was needed, and an invalid zip date in the central
directory. All fixed and rechecked.
