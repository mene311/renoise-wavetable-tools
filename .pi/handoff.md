# Handoff — wavetable instruments for Renoise

> Everything published for Renoise, including this project, is indexed at
> <https://mene311.github.io/renoise-hub/> (repo `~/Projects/renoise-hub`).


**Status: PAUSED, nothing running.** Last session built the tooling, the library, the Renoise tool
and the web builder, and the instruments repo was refreshed (commit `b08b792`). Small leftovers are
listed under Remaining.

Repo: `~/Projects/renoise-wavetable-tools` → https://github.com/mene311/renoise-wavetable-tools
Instruments: https://github.com/mene311/renoise-wavetable-instruments (2,342, pre-rig)
Site: https://mene311.github.io/renoise-wavetable-tools/ (Pages, source `/docs`)

## Mission

Give Renoise a wavetable instrument pipeline, without a VST in sight:

1. build native gate-scan wavetable `.xrni` from any wavetable source (Vital JSON, Serum-style
   wav, frame folders, packs), then sweep them with one macro;
2. convert the whole local wavetable collection and file it by timbre;
3. let people who do not know Python do the same, from GitHub or from inside Renoise.

## Progress (all done)

### The architecture, decoded and verified
Reverse-engineered from Kaidiak's instruments (shared in the **Trackercorps** Discord, see the
correction below) and Renoise's own `Library/Instruments/Utility/{2,4,6,12} frame Wavetable
Init.xrni` (by slujr / zensphere):

- chain 0 `GATES`: SampleMixer + one **frozen** LFO per frame (`Freq 9.99999997e-07`) reading a
  custom unipolar Lines envelope; each frame's triangle peaks 2 lines apart so neighbouring
  gates sum to 1.0
- chains 1..N `FRAME`: SampleMixer (volume 0) + Send (`MuteSource`) → `SUM`
- chain N+1 `SUM`: SampleMixer, the instrument's output
- macro 1 `WT Position` → SampleDSP chain 0, devices 1..N, **parameter 8** (the LFO's
  position/Reset), 0.0-1.0 linear
- 12 frames max = Renoise's twelve voices per note column

### Tooling (`wt_xrni.py`, ~1,000 lines, plus friends)
- `wt_xrni.py` — builder. Sources: frame dirs, `.vitaltable` (both `wave_data` float32 and
  `audio_file` int16 forms), `.vital` presets, Serum-style `.wav` (auto frame size), `.npy`.
  Flags that matter: `--n-frames`, `--select even|spectral`, `--cycle-len`, `--root auto`
  (brightness-driven, deliberately **not** in the README), `--lowpass`, `--with-sweep`,
  `--with-fx`, `--jobs`, `--sources-from` batch, `--dedupe`, `--fast`, `--install`.
- `wt_verify.py` — audits a build: structure, gate sums, provenance vs source, analytic
  sine/tri/saw/square, tuning in cents, plus `-frames`/`-sweep`/`-nulltest` renders.
- `wt_catalogue.py` — features (brightness, odd-harmonic share, harmonic slope, flatness,
  fundamental share, crest, roughness), k-means into ten timbre families, builds into folders.
- `wt_survey.py` — stratified sampling of the library, writes a feature TSV.
- `vitaltable_to_wav.py` — Vital table → Serum-format `.wav`.
- `vitallfo_to_xrdp.py` — 133 Vital LFO shapes → Renoise LFO device presets
  (`Effect Presets/LFO/`, names without a prefix).
- `vitallfo_to_xrno.py` — the same shapes as per-voice modulation sets
  (`Modulation Sets/WT Shapes/`, target Volume, looping, tempo synced).
- `build_sweep_chain.py` — `.xrnt` chain: LFO → Hydra → the instrument's macros.
- `replace_rebuilt.py`, `validate_xrni.py` — library surgery and validation.

### The library
- 1,851 unique wavetables measured from ~6,500 candidates (deduped), filed into ten timbre
  folders under `~/.local/share/Renoise/User Library/Instruments/Wavetables/`.
- Brightness distribution of that collection: 30.5% classic (1-3 harmonics), 25.1% rich,
  19.1% bright, 13.5% very bright, 11.8% noise-like. Pitch detection found 1,849 single-cycle
  tables and exactly 2 multi-cycle ones (`WaveEdit/SYNLP39` = 4, `VitalPresets/13579` = 2).
- Rebuilt the whole set with `--with-sweep`: **2,319 built, 0 failed, filed in place**;
  library now 2,373 instruments, 2,326 with the sweep template, no duplicate names.

### Sweep template, as agreed
SUM chain = Mixer, SWEEP (shaped LFO, **inactive**, 16 lines/cycle, 16-step envelope, wired to
the Hydra input), HYDRA (out 1 → macro 1, rest free), INSTR MACRO, KT → RESET (Key Tracker on
the LFO's Reset parameter). Instrument Macros device is legal inside an instrument chain
(`SampleFilterDeviceChain`, 65 device kinds) even though the GUI never offers it — documented in
the READMEs. Verified parameter indices inside an instrument chain: Hydra input 1, macro 1-8 =
params 1-8, filter cutoff 2, gainer volume 1, LFO position/Reset 8.

### Renoise tool (`renoise-tool/`, packaged as `com.meneses.WavetableBuilder.xrnx`)
- Load a wavetable as a sample, select it, tool → frames → Build and save; it writes the `.xrni`
  and loads it. Batch: Convert scope = this sample / every sample in this instrument / every
  instrument in the song, with Build all writing one instrument per source into a folder.
- **Why it writes a file**: `renoise.InstrumentMacro.mappings` is READ-ONLY in the API, and
  instrument chains can only be moved by a macro, so the mapping must exist in the file.
- Checked: XML validates against `RenoiseInstrument34.xsd`, zip passes `unzip -t` and
  `zipfile.testzip()`, CRC32 matches zlib, tuning matches the Python builder, `luac -p` clean,
  loads under LuaJIT with a stubbed API.

### Web builder and library browser (`docs/`, GitHub Pages)
- `index.html` — drag and drop wavetables, options (frames, spectral/even, cycle length, sweep),
  builds in the browser, downloads `.xrni` files, draws the first frame. Nothing uploaded.
- `library.html` — browses the published instruments (search, category filter, sort by
  brightness), fetches a row's `.xrni`, unzips it with `DecompressionStream`, draws the frame and
  reports frames/cycle/BaseNote/Finetune/loop/sweep.
- `ci/build-instruments.yml` is now in `.github/workflows/` too: drop files in `wavetables/`,
  run the Workflow, download the artifact. Tested green (run 36050483695, artifact contained a
  valid rigged instrument).

### Batches, and how big things get in
- Multi-file: GitHub's uploader takes multiple files and a **dragged folder**, but caps at **100
  files at a time**, and 25 MiB per file through the browser (100 MiB via git).
- **Zip support, all three paths**: `expand_sources()` in `wt_xrni.py` unpacks zip entries into the
  batch listing, the workflow unzips before building, and the browser expands a dropped zip with
  the shared `listZip()` reader (store and deflate via `DecompressionStream`).
- Tested: CLI (zip of 2 → 2 valid instruments), browser under node (2 → 2 valid), and the workflow
  in the cloud (run `36057088905`: 2 unpacked, 1 duplicate skipped by `--dedupe`, 2 built, 13/13
  verified, artifact uploaded).

### GitHub
- `renoise-wavetable-tools` public: tools, Renoise tool, docs site, READMEs unslopped
  (noslop 0.0/1k).
- `renoise-wavetable-instruments` public: **2,373 instruments, 2,326 of them rigged**, pushed as
  `b08b792` ("Rebuild every instrument with the in-instrument sweep template"), in sync with
  `origin/master`. `provenance.tsv` and `catalogue.tsv` cover the 2,342 built from a source table;
  the other 31 are variants and test builds with no provenance row. CC0 licence for the
  CC0-derived share, takedown note for the rest. User asked to upload everything and will answer
  takedowns.
- Everything else on the account made private except renoise repos (`bacania-site` deliberately
  left public because it serves bacania.cl over Pages; `mene311` profile repo is private, so the
  profile README no longer renders).
- `gh` token now carries the `workflow` scope.

## Remaining

- [x] **Instruments repo refreshed** — 2,373 files, 2,326 rigged, pushed (`b08b792`).
- [ ] 31 repo instruments have no `provenance.tsv` row (27 flat variants plus four that came out
      of the rebuild with a double space in the name, e.g. `ESW Analog - Moog Square 01  WT.xrni`).
      The library browser skips them because it keys off provenance. Fix by regenerating the two
      TSVs from `~/.local/share/wt_catalogue.tsv` and the manifests, or by renaming the four.
- [ ] Optional: prune the 47 instruments without the rig (27 flat manual variants, `Survey/` 20,
      `Kaidiak/` 3) — the sweep demos and the Survey set were kept on purpose.
- [ ] Optional: re-run the timbre clustering with a different k or extra features (phase
      randomness) if a boundary looks wrong by ear; the catalogue TSV makes that cheap.
- [ ] Optional: `--root auto` is implemented but undocumented on purpose ("root is still too
      high" per the user). Revisit only with their say-so.
- [ ] Optional: the `.xrnx` is version 3 in its manifest; bump when the batch mode is tested in a
      real Renoise (it has never been run inside Renoise, only under a stubbed API).

## Gotchas learned the hard way

- **Finetune sign.** Renoise plays at `2^((played − base)/12)·2^(transpose/12)·2^(finetune/1200)`,
  so a flat sample needs a **positive** finetune. The first build shipped every instrument 9.4
  cents flat.
- **The instruments came from the Trackercorps Discord**, not the Renoise Discord (corrected in
  both READMEs).
- **Vital's LFO JSON**: flat `(x, y)` pairs, x ascending 0..1, a parallel `powers` array, and a
  `smooth` flag. `smooth` does *not* mean stepped — staircases are the shapes whose segments are
  all flat or vertical, and a duplicate at x = 1.0 is just the wrap point.
- **Chain presets cannot hold instrument devices** (`RenoiseDeviceChain` has no Sample* devices),
  but *instrument* chains are `SampleFilterDeviceChain` and allow 65 device kinds. There is no
  preset file for instrument-side chains, so that rig ships inside the `.xrni`.
- **Naming collisions during a rebuild**: the catalogue wrote `<cluster> - <table>.xrni` while the
  library used `<table> WT.xrni`, so filing doubled the library, and my first reconciliation pass
  mangled table names that contain " - ". Fixed by naming builds `<table> WT.xrni` and restoring
  the folders from the published repo.
- **Zip byte-level bugs** in both hand-written writers: a central-directory record 4 bytes short,
  a local header with a one-byte extra-length field, DOS date bytes swapped, and CRC32 built with
  subtraction where XOR was needed. Test with `unzip -t`, `zipfile.testzip()` and a `zlib` CRC
  comparison before trusting either writer.
- **DFT reconstruction**: keep both Fourier coefficients; folding them into amplitude and phase
  flips the sign of the sine term. And normalise each frame to peak 1.0, as the Python builder
  does, or amplitudes will not match.
- **Lua locals resolve at compile time**: `build_batch` calling `show_result` defined below it
  resolves to a nil global. Forward-declare, or order the file.
- **`pgrep -f "script.py"` matches your own shell**, so a polling loop never exits. Use
  `pgrep -f "[s]cript.py"` or check `ps`.
- **Parallel agents need a model name the setup accepts**; `deepseek-v4-pro` was rejected silently
  (all three tasks "succeeded" with no output). Retry without an explicit model.
- Prompt-injection aside worth remembering: several `.vital` presets embed the *same* factory
  table, so a catalogue without content hashing is mostly duplicates — 91 of the first 120
  candidates collapsed into 18 unique tables.

## Key paths

| Thing | Path |
|---|---|
| Tools | `~/Projects/renoise-wavetable-tools/` (repo), `~/Projects/renoise/tools/` (also has the older SFZ/instrument tooling) |
| Renoise tool | `~/Projects/renoise-wavetable-tools/renoise-tool/` + `com.meneses.WavetableBuilder.xrnx` |
| Site | `~/Projects/renoise-wavetable-tools/docs/` |
| Instrument library | `~/.local/share/Renoise/User Library/Instruments/Wavetables/<timbre>/` |
| LFO presets | `~/.local/share/Renoise/User Library/Effect Presets/LFO/` |
| Modulation sets | `~/.local/share/Renoise/User Library/Modulation Sets/WT Shapes/` |
| Chain preset | `~/.local/share/Renoise/User Library/Effect Chains/Wavetable Sweep.xrnt` |
| Catalogue | `~/.local/share/wt_catalogue.tsv`, `/tmp/wt_survey_all.tsv` |
| Panels | `/tmp/parallel-api-review-*.md`, `/tmp/parallel-format-review-*.md` (the review findings) |
| Renoise schemas | `/usr/local/share/renoise-3.5.4/Schemas/RenoiseInstrument34.xsd`, `RenoiseDeviceChain21.xsd` |

## Resume with

```
cd ~/Projects/renoise-wavetable-tools
git log --oneline | head            # last: 0b38b10 + the site/batch commit
# refresh the instruments repo (the outstanding job):
python3 ~/Projects/renoise/tools/wt_catalogue.py --scan            # writes the TSV mapping
# then copy the library's category folders over the repo's, commit, push
```

To rebuild anything from scratch: `wt_catalogue.py --scan --build --with-sweep` (~35 min, 2,319
instruments, 0.87 s each). Verify any instrument with
`python3 tools/wt_verify.py "<path>.xrni"`. Test the web builder with
`node /tmp/js_test.mjs` (builds both variants, schema-validates, compares frames to Python).

## 2026-09-24 — library page: fetch, category view, batches

Reported from the phone: clicking a wavetable in the library browser gave
"NetworkError when attempting to fetch resource".

- Cause: the click and the per-row `get` link used `https://github.com/…/raw/…`, which answers
  302 with an empty `access-control-allow-origin`, so `fetch()` always failed. Two CORS-friendly
  mirrors now (`raw.githubusercontent.com`, then jsDelivr).
- Second fault behind it: `library.html` called `WT.*` while `wt-builder.js` publishes
  `WTBuilder`, so nothing it fetched could be parsed. Alias added there and in `selftest.html`;
  `index.html` already had one (my first attempt duplicated that `const` and broke the builder
  page with a SyntaxError until the browser check caught it).
- Third: Renoise stores sample data inside the .xrni as FLAC, so `WT.parseWav` fails on every
  published instrument. The draw path now decodes wav or flac (browsers decode flac themselves).
- New: by category view with counts and a per-category batch button, checkboxes + select all shown,
  zip built in the page with `WT.zipStore`, progress and failure reporting, favicon.
- New test: `tests/browser_check.py` (playwright drives /usr/bin/chromium). 15 checks, runs local
  and against the deployed URL, fails on console errors. Verified 15/15 both ways.
  Needs a venv with playwright: `~/.local/venvs/browser/bin/python tests/browser_check.py`.
