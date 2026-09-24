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
thirteenth frame would vanish without warning. If the sample length does not divide evenly by the
frame count, the frame length becomes `floor(length / frames)`, the tail is dropped, and the
report says how many samples went. Buffer indices are 1-based per the API docs, so the reader
starts at 1. Stereo sources use the left channel, and the report names the channel count so it is
not a silent choice.

Pitch comes from the frame length: a frame of `L` samples at rate `sr` has a natural frequency of
`sr / L`, and the tool picks the nearest Renoise note plus the cents offset. The sign matters,
because Renoise plays a sample at `2^((played - base_note)/12) · 2^(transpose/12) ·
2^(finetune/1200)`, so a sample that is flat of its note needs a positive finetune. A 169-sample
cycle at 44.1 kHz comes out at BaseNote 48, Finetune +4, matching the Python builder.

Some wavetable files repeat inside a frame. The tool counts upward zero crossings and warns when a
frame crosses more than a few times, since the instrument will play sharp; it does not try to fix
it. Cycles long enough to map below note 0 get clamped, the cents are still computed from the
unclamped note, and the report says so. Sample names are escaped, so a sample called
`Test & <Table>` cannot break the XML.

Sample data goes in as uncompressed WAV and the archive is store-only, so the file is bigger than
the Python builder's FLAC. The extension is never referenced in the XML, and Renoise opens WAV from
inside an instrument container, so this is only a size difference.

## Verification

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
