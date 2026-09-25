# renoise-wavetable-tools

Build wavetable instruments for Renoise. Load one, hold a note, turn macro 1, and the
sound morphs through the table the way a wavetable oscillator does in Serum or Vital.
It runs on the sampler, so there's no plugin and no CPU spike.


Everything here sits alongside the rest of my Renoise work, listed at
<https://mene311.github.io/renoise-hub/>.

## LFO shapes and modulation sets

The Vital LFO shapes rebuilt as Renoise presets live in [`presets/`](presets): 133 LFO device
presets and 133 sampler modulation sets. Copy the two folders into your user library and they
show up in the LFO device and the sampler. See [presets/README.md](presets/README.md).

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
   `.flac`, a `.npy`, or a `.zip` of any of those, which is unpacked first. One wavetable becomes
   one instrument. GitHub's uploader takes a dragged folder but stops at 100 files, so a zip is the
   practical way to move a whole bank.
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


## In the browser, with the library

The pages in `docs/` do the whole conversion client-side. The builder takes dropped wavetables or
a zip of them, asks how many frames you want, and hands back instruments you can download one at
a time or all at once. Nothing is uploaded.

Next to it, the library page browses everything that has been published, searchable by name or by
the table it came from, and with a by category view that shows what each timbre folder holds.
Clicking a row fetches that instrument and draws its first frame, reading the sample whether
Renoise stored it as wav or, as it does on save, as flac.

Batches work from either view: tick instruments and take them as one zip, or take a whole category
with its own button. The zip keeps the `category/name.xrni` layout, so it unzips straight into the
right folders. Each file is fetched on its own and the zip is assembled in the page, which is why
a few hundred instruments take a moment and a very large selection asks first.

Both pages read the instrument repository from `raw.githubusercontent.com`, falling back to
jsDelivr. The `github.com/.../raw/` URL looks equivalent and is not: it redirects without an
`Access-Control-Allow-Origin` header, so a browser fetch against it always fails.

`tests/browser_check.py` drives both pages in a real browser: it builds an instrument from a
synthesised wavetable, re-reads the result, clicks a library row, runs a batch download, and fails
on any console error. Run it after touching `docs/`:

```sh
python tests/browser_check.py                                     # local server
python tests/browser_check.py --url https://mene311.github.io/renoise-wavetable-tools/
```

`docs/selftest.html` is the lighter version, for anyone wondering whether their browser can reach
the repository at all.

## Giving one back

The builder page has a fourth panel for this. When a build finishes it hashes the frames and
compares them against `hashes/index.json` in the instrument repository, which holds both hashes for
every instrument already published, and says whether what you made is already there, close to
something that is, or new. Tick what to send, say how to be credited, and it hands back one zip
holding the instruments plus a `donation.json` describing them. The upload page for `donations/` is
one click from there, and the repository does the filing.

Two hashes, because file bytes say nothing here: Renoise stores the samples as flac when it saves
and this page writes wav, so the same table differs byte for byte. An exact key over the samples
catches the same audio either way. A shape key, the cycle read at 24 points, catches the same table
rebuilt at another cycle length, which is the case that matters most, since hardly anyone rebuilds
with the same settings twice.

On arrival, `tools/ingest_donations.py` in the instrument repository checks again. Identical audio
is refused and named, a variant is held next to it for a look rather than filed, and anything new
goes into `instruments/<category>/` with a provenance row and a rebuilt index. Every processed zip
is kept under `accepted/` or `rejected/` with a report saying what was decided. To ask the same
question from a terminal, with the instrument repository checked out:

```sh
python3 tools/wt_hash.py --check ../some-instrument.xrni
```

## One caveat

Some instruments play at a different pitch than the key you press. When the loudest part of
the wave isn't the fundamental, the note comes out an octave or a twelfth away, and the top octaves get rough, since harmonics that no longer fit under Nyquist fold back down.
Looping one cycle in a sampler does that.

## Credits

The gating trick came from instruments Kaidiak shared in the Trackercorps Discord. Renoise
ships a plainer version of the same idea as `Utility/2, 4, 6 and 12 frame Wavetable Init`,
by slujr (zensphere). Thanks to both. No sample content lives in this repo.

MIT.
