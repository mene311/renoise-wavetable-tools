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

## Instruments that hide a device from the GUI

`--with-sweep` drops a shaped LFO, a Hydra and an **Instrument Macros** device into the
instrument's SUM chain. That last one is not offered anywhere in the instrument editor's
add-device menu, which makes it look impossible to create: it is not. An instrument's chain
is a `SampleFilterDeviceChain`, and that type allows 65 device kinds, including
`InstrumentMacroDevice`. Renoise loads it, keeps it and round-trips it when you save. It is
only the GUI menu that leaves it out.

So if you want one, either run the builder with `--with-sweep`, or add the device by hand to
the `.xrni`: write an `<InstrumentMacroDevice type="InstrumentMacroDevice">` block into one of
the instrument's `<DeviceChain>` elements (see `SWEEP` / `HYDRA` / `INSTR MACRO` in a built
file for the field order), then reopen the instrument. Nothing else is needed.

Parameter indices inside an instrument chain, read out of working files:

| device | parameter | index |
|---|---|---|
| Hydra | input | 1 |
| Instrument Macros | macro 1-8 | 1-8 |
| Filter | cutoff | 2 |
| Gainer | volume | 1 |
| LFO | position / Reset | 8 |


## Inside Renoise, as a tool

`renoise-tool/` builds the same instruments from inside Renoise, and
`com.meneses.WavetableBuilder.xrnx` in the repo root is the packaged tool. Load a wavetable as a
sample, select it, run Tools → Wavetable Instrument Builder, pick the frame count and save. It
writes the `.xrni` and loads it straight away.

It writes a file rather than building the instrument through the API because
`renoise.InstrumentMacro.mappings` is read-only, and instrument chains cannot be automated by
anything except a macro, so the mapping that walks the table has to exist in the file.
`renoise-tool/README.md` covers the edge cases and what each one does.


## No Python? Build them on GitHub

The builder runs in GitHub Actions, so nothing has to be installed locally:

1. Fork this repo (or use it directly).
2. Drop your wavetables into `wavetables/` — `.vitaltable`, `.vital`, a Serum-style `.wav`, a
   `.flac` or a `.npy` — and commit. One file becomes one instrument.
3. **Actions → Build wavetable instruments → Run workflow** (or just push, which triggers it).
   The run takes a few minutes; when it finishes, download the **instruments** artifact.
4. Unzip it into `~/.local/share/Renoise/User Library/Instruments/` (Windows:
   `%APPDATA%\Renoise\V3.5.4\User Library\Instruments`, macOS:
   `~/Library/Application Support/Renoise/V3.5.4/User Library/Instruments`).

The workflow exposes the useful flags as inputs: frames per instrument, frame selection
(spectral or even), cycle length (which sets the register), and whether to add the sweep
template and the gain/filter. It also runs the checker on everything it builds and uploads
those reference renders alongside.

### Renoise-native alternatives that already exist

If you would rather stay inside Renoise, two community tools cover the neighbouring ground:

- **Paketti** (esaruoho/paketti) concatenates single cycles into one long sample and plays
  wavetables by crossfading Wave A and Wave B. Random AKWF wavetables at 32/64/128/256 frames,
  `.wt` import and export, a single-cycle writer.
- **8chip** (halebop17/8chip) stages up to four single cycles and spreads them across the
  keyzones.

Both are the crossfade or keyzone approach. What this toolkit does differently is the
gate-scan architecture: one sample slot per frame, a gate LFO per frame whose triangle
envelopes add up to 1.0, and one macro that walks the table, which is what Renoise's own
`Utility/… frame Wavetable Init` templates and the instruments shared in the Trackercorps
Discord use.


## One caveat

Some instruments play at a different pitch than the key you press. When the loudest part of
the wave isn't the fundamental, the note comes out an octave or a twelfth away, and the top octaves get rough, since harmonics that no longer fit under Nyquist fold back down.
Looping one cycle in a sampler does that.

## Credits

The gating trick came from instruments Kaidiak shared in the Trackercorps Discord. Renoise
ships a plainer version of the same idea as `Utility/2, 4, 6 and 12 frame Wavetable Init`,
by slujr (zensphere). Thanks to both. No sample content lives in this repo.

MIT.
