# Handoff — wavetable instruments for Renoise

> Everything published for Renoise, including this project, is indexed at
> <https://mene311.github.io/renoise-hub/> (repo `~/Projects/renoise-hub`).


**Status: PAUSED, nothing running.** The tooling, the library, the Renoise tool and the web builder
are built and published; the instruments carry the sweep rig and the duplicate check works.
Open items are listed under Remaining, and the newest one is a wrap bug in the sibling session's
sparse LFO presets.

Repo: `~/Projects/renoise-wavetable-tools` → https://github.com/mene311/renoise-wavetable-tools
Instruments: https://github.com/mene311/renoise-wavetable-instruments (2,335 files, rig baked in,
last commit `a05a2de`)
Site: https://mene311.github.io/renoise-wavetable-tools/ (Pages, source `/docs`)
Themes gallery: https://mene311.github.io/renoise-forum-color-themes/ (Pages, repo root)
Local library: `~/.local/share/Renoise/User Library/Instruments/Wavetables/` — 2,319 filed by timbre
+ 16 flat variants, every filed instrument rigged and phase-fixed

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
git log --oneline | head            # site, tool, presets, hub
```

The instruments refresh used to be listed here as the outstanding job. It is done: `7f7850a` and
later carry it, and on 2026-09-25 all 2,373 local instruments were compared against the published
ones — same names, identical `Instrument.xml` by sha256, identical frame content. Nothing is behind
on either side, so do not re-copy the library over the repo unless the library actually changed.

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

## 2026-09-25 — donating an instrument, and the duplicate check

The ask: let someone who builds a table offer it to the library, catching duplicates first, with
hashes of the wavetables.

- **Hashes of the frames, not the file.** Renoise stores sample data as flac on save and the
  builder writes wav, so the same table differs byte for byte. `tools/wt_hash.py` (in the
  instruments repo) decodes and hashes twice: an exact key over the samples, and a shape key, the
  cycle read at 24 points and quantised to 8 bit, which survives another cycle length or another
  rendering. `hashes/index.json` holds both for all 2,373 instruments (1.1 MB, ~620 KB gzipped).
- **`docs/wt-hash.js`** mirrors it, and `wt-hash.js` also owns `decodeSample`, used by the library
  view, the smoke test and the builder. `tests/browser_check.py` asserts the JS key equals the key
  in the Python-built index, which is the guard against the two drifting.
- **Two decoder traps, both found by that test.** Chromium resamples to the audio device rate
  unless told otherwise: a 169 sample cycle came back as 183, so every hash disagreed. Decode with
  an `OfflineAudioContext` at the rate parsed out of the flac streaminfo or the wav fmt chunk.
  And libsndfile and Chromium disagree in the last bits of a float sample, which at 16 bit lands
  either side of a rounding boundary, so the exact key quantises to 11 bit instead.
- **The builder's fourth panel**: after a build it hashes what it made, compares against the index
  (raw first with a daily cache-busting query, jsDelivr as fallback) and shows *already in the
  library* / *looks like a variant* / *new*. Tick, credit yourself, get one zip with the
  instruments plus `donation.json`, then the `donations/` upload page.
- **`tools/ingest_donations.py`** + `.github/workflows/ingest-donations.yml` in the instruments
  repo: identical audio refused and named, a variant (80% of frames matching) held in
  `donations/review/`, anything new filed into `instruments/<category>/` with a provenance row and
  a rebuilt index. Zips kept under `accepted/` or `rejected/`, decisions written to `REPORT.md`.
- Tested: ingest on a throwaway copy (duplicate under a new name refused, a fresh table accepted
  and indexed, a broken zip reported, and re-donating the accepted file refused on the second
  pass), and `tests/browser_check.py` at 24/24 both locally and against the deployed site.
- Gotcha: the workflow's first run committed a `__pycache__` because it staged everything. It now
  stages `instruments hashes provenance.tsv donations .gitignore`.
- Gotcha: `raw.githubusercontent.com` serves a stale copy for a few minutes after a push
  (jsDelivr for much longer), so a check run straight after pushing a rebuilt index can fail on
  the old one. Wait, or re-run.

## Remaining after this session

- [ ] The `.xrnx` Renoise tool has still never been run inside Renoise, only under a stubbed API.
- [ ] 27 instruments in the repo have no `provenance.tsv` row (23 flat variants plus four whose
      names differ slightly from their row); the library browser keys off provenance, so it skips
      them. An earlier note said 31, before the survey/Kaidiak/test files were removed.
- [ ] Optional: prune the 47 without the sweep rig, or recluster with other k.
- [ ] Optional: decide whether the hub moves to the bare `mene311.github.io` root.
- [ ] Review `donations/review/` when the first variant arrives; the 80% threshold is a guess that
      has only been exercised against synthetic cases.

## 2026-09-25 — 27 instruments removed from the library

Asked for: the survey set, the dissected instruments and the test builds.

- Gone: `Survey/` (20, a cross-pack sample whose source tables are published under their own
  names), `Kaidiak/` (3, third-party `.xrni` kept to dissect the format), and the four `TEST *`
  builds. 2,373 -> 2,346 instruments.
- None carried the sweep rig, so 2,326 rigged is unchanged and the count without it drops from 47
  to 20 (the growl/bass tuning registers and a few early single-table builds).
- `provenance.tsv`, `provenance.json` and `catalogue.tsv` each lost their 23 rows and `hashes/`
  was rebuilt; all three files now hold 2,319 rows and agree. README counts updated, and the hub's
  prose count with them.
- The local library copies were moved to `~/Projects/renoise/removed/2026-09-25/`, not deleted, so
  a Renoise install can be put back from there; the repo copies live on in git history.
- `tests/browser_check.py` used `Kaidiak` for its batch test and now uses `impulses and clicks`
  (3 instruments, same expected count). 24/24 both locally and against the deployed site.

## 2026-09-25 (later) — seven more out, and the library got filters

- Removed the flat copies whose content is already filed, rigged, under a timbre folder:
  `Growl Dirty Raw Strings`, `Vital Harmonic Series` (= `Wub Harmonically Interesting`),
  the three `Vital Basic Shapes` (= `Chords Clean Skank Stabs or Pads 2`), `Vital Classic Fade`
  (= `Notahorn Ciddy Cute Kick 2`) and `WaveEdit SYNLP155` (= `SYNLP155`). Four were identical
  audio and three matched 83-100% of frames both ways. 2,346 -> 2,339, and the count without the
  sweep rig is down to 13. Table is now 2,326 rigged + 13 variants.
- Local library and repo verified equal again after the removal, and the 34 files moved aside live
  in `~/Projects/renoise/removed/2026-09-25/` (`same-as-rigged/` for this batch).
- Library page: a **source** filter beside the category one, both showing counts, a line naming the
  active filters, a clear button, and the view in the query string so a narrowed list is a link
  (`?cat=white+noise&src=WaveEdit+Online+%28CC0%29`). `tests/browser_check.py` grew six checks for
  it and is now **31 checks, green locally and against the deployed site**.
- Watch out: after an index rebuild, raw serves the old copy for a minute or two, and jsDelivr for
  much longer, so a check run immediately after can report the previous count. Not a bug in the
  page; wait and re-run.

---

# 2026-09-25 (night) — gallery theme, downloads, and the wub that never arrived

## Theme gallery matched to the hub
`~/Projects/renoise-forum-color-themes` (Pages from the repo root, commit `71474e4`):
- `style.css` is now the hub's stylesheet, verbatim, with a header comment saying it is mirrored
  from `renoise-hub/style.css` — **keep the two in step** (hub is the source of truth).
- `gallery.css` is the only page-specific file and uses hub tokens exclusively (no new colours).
- Markup moved to the hub's idiom: `.site-header` with the hub logo linking home + the same nav
  (`Themes` marked active), hero band, the filters in a `.panel`, `tag` badges instead of coloured
  pills, hub footer. Filters, sorting, palette filter, variant grouping and lazy previews unchanged.
- Verified by measuring screenshots rather than by eye (the vision tool is unavailable in this
  session): header `#161618`, borders `#2e2e34`, page `#0e0e10`, panels `#1e1e22`, accent `#6f9f40`,
  identical to the hub; 560 cards render, count reads `560 / 560`.

## .xrnc downloads forced (server side, free)
`github.com/…/raw/master/themes/x.xrnc` serves `text/plain`, so Firefox *displays* the theme.
`mene311.github.io/…/themes/x.xrnc` serves `application/octet-stream` → downloads. Links now point
at the site's own origin and carry `download="<file>"` (only honoured same-origin). Verified live:
`content-type: application/octet-stream`, 560/560 catalog files present, no `raw/master` links left.
Note: `github.io` cannot set `Content-Disposition` at all — if raw-CDN links are ever wanted, a host
that allows headers (Cloudflare Transform Rules / `_headers`) is required.

## The wub: shapes did not start at zero
Measured across the 133 `.vitallfo`: **71 began at their peak**, only 35 had the low point at line 0.
A Renoise LFO starts at its first point, so on a cutoff the modulation began wide open with nowhere
to travel — no wub. Both converters in `~/Projects/renoise/tools/` now rotate each shape to start at
its low point (`align_to_low`, 85 of 133 needed it, `--no-align` opts out): `Sin` went from
`first 1.000, low at line 48` to `first 0.000, low at 0, peak at 48`. Regenerated and published all
133 `.xrdp` + 133 `.xrno` (library + `presets/`), plus `WT Sweep 16.xrdp` = the shape the instruments
bake, now `0 → peak → 0`.

## Instrument rig: order and baked shape
- Chain order now reads left to right the way Renoise's own `KT - Rnd - Hydra.xrnt` does
  (KT 1 → LFO 2 → Hydra 3, KT → param 8): **Mixer, KT -> RESET, SWEEP, HYDRA, INSTR MACRO**.
  Previously the KT sat last, after the LFO it resets.
- The baked sweep shape starts at its low point: `scan_shape` went from `abs(1 - 2*(i/15))`
  (peak at line 0, the old behaviour) to `1 - abs(1 - 2*(i/15))` — zero at line 0, peak mid-cycle.
- Rebuilt the whole library (2,318 built, 0 failed, one source was a 0-byte file). Verified on all
  2,319 filed instruments: rigged, KT-first, first envelope value `0.0`, zero stale duplicates.
- Remote verified: `REMOTE SUM chain: Mixer, KT -> RESET, SWEEP, HYDRA, INSTR MACRO`, envelope
  `0,0.0000  1,0.1333 … 15,0.0000`. Frames untouched — 8/8 spot check byte-identical to
  `hashes/index.json`, so the index needed no regeneration.

## Duplicate check (the site's upload comparison)
Two faults, both fixed:
1. **Frame selection drifted.** A batch-mode rewrite of `wt_catalogue.py` dropped the
   `--select spectral` flag the per-source version passed, so the library was built *even* while the
   site's builder defaults to *spectral* → every default upload matched no frames and read "new".
   Fixed the catalogue, rebuilt the library on spectral, re-synced the instruments repo and
   regenerated `hashes/index.json` (2,339 entries). Also fixed 100 build failures: `spectral` on
   tables with 1–2 native frames returned one frame; `select_table_frames` now blends instead.
2. **The verdict bar.** A full frame overlap was reported as "variant", so a table that *was* already
   in the library still looked donatable. Both `docs/wt-hash.js` and `tools/wt_hash.py` now read
   `overlap >= 0.99` as **identical**, with the note "same table, different frame selection".
- Verified against the live copies: live `wt-hash.js` + live index + a default (spectral) build of
  `BassTables 01.wav` → `identical | of: BassTables 01 WT.xrni` → "already in the library".
- Gotcha: `wt_hash.py --build-index` indexes the **repo's** instruments, so sync the repo *before*
  re-indexing, or the index describes the previous build (this made a test look inverted).

## Facts worth not rediscovering
- An instrument chain is a `SampleFilterDeviceChain` and allows **65** device kinds — filters, gainers,
  LFOs, Hydras, Doofers, sends, and an `InstrumentMacroDevice`. A modulation set
  (`SampleModulationSet`) allows only **11** `Sample*ModulationDevice` kinds and its targets are
  Volume/Panning/Pitch/Cutoff/Resonance/Drive — you cannot reach macros from there.
- The Instrument Macros device is absent from the instrument editor's add-device menu but is legal in
  the file and Renoise loads, keeps and re-saves it (proven by the hand-wired instrument). Documented
  in the tools README.
- Verified parameter indices — instrument context: Hydra input **1**, macros **1-8**, filter cutoff
  **2**, gainer volume **1**, LFO position/Reset **8**. Track context: device indexing is 1-based
  (Gainer volume 2, filter cutoff 2), LFO Reset 8.
- `.xrnt` chain presets are the *track* format only (no Sample devices), so an instrument-side rig
  ships baked into the `.xrni`, never as a preset.
- Renoise's own wavetable template LFOs are `preset Init / library Bundled Content / modified true`
  with the shape inline. Ours match, so nothing depends on a preset the user might not have.
- The instruments repo's files are **hardlinks** to the library, and the builder copies samples in
  place, so a rebuild propagates into the repo working tree (git showed a clean tree after a rebuild
  that changed every file).

## Remaining after this session
- [ ] **Wrap bug in the sibling session's sparse LFO presets** (commit `726a2e0`). It switched the
      presets to Vital's authored points with `Curve` interpolation, and the phase fix survived, but
      `presets/Effect Presets/LFO/Sin.xrdp` now has **two** points: `0,0.0000` and `48,1.0000`. The
      descending half is gone, so the cycle jumps from the peak straight back to zero — a sawtooth
      rather than a sine. Vital's Sin has three authored points; the third (`96,0.0`) should be there.
      Check whether the rotation drops the final point or the wrap duplicate is being removed.
- [ ] **Reconcile the two converter copies.** `~/Projects/renoise-wavetable-tools/vitallfo_to_xrdp.py`
      (repo, `726a2e0`, sparse + Curve + tension, **no** `align_to_low`) differs from
      `~/Projects/renoise/tools/vitallfo_to_xrdp.py` (dense rasterisation + `align_to_low`). The repo's
      output is what is published, so it is probably canonical — but the working copy's phase fix must
      not be lost. Same for `vitallfo_to_xrno.py`.
- [ ] **Source-table key for the duplicate check.** A donor who picks a different frame selection or
      cycle length still reads "new" (the twelve frames genuinely differ). Indexing one hash of the
      whole uploaded wavetable, alongside the per-frame keys, would catch any setting; the provenance
      needed to compute them already exists.
- [ ] **Decide the baked default shape.** The instruments bake the 16-step triangle; the 133 Vital
      curves now live beside them as presets. If one should be baked instead, add
      `--sweep-shape <file.vitallfo|.xrdp>` and rebuild (~35 min, or patch the envelopes in place).
- [ ] **Listen to it in Renoise.** Nothing in this session was heard: the sweep, the KT reset and the
      rotated presets are verified structurally and by measurement only.
- [ ] Instruments repo as independent copies instead of hardlinks, if an in-place edit ever needs to be
      rolled back cleanly.
- [ ] Hub facts refresh (`renoise-hub/build.py`, weekly workflow) — the hub lists 2,339 instruments;
      the local library is 2,319 filed + 16 flat, and `Survey/` (20, pre-rig) is still there.
- [ ] Kaidiak's three instruments were removed from the repo on purpose (`d5a27bb`) and are now missing
      locally too; recoverable from git `3966a36` if wanted.

---

# 2026-09-25 (later) — the tool is installed, and the other tools are published

## The `.xrnx` is installed in Renoise, and finally has a load test

- Installed at
  `~/.config/Renoise/V3.5.4/Scripts/Tools/com.meneses.WavetableBuilder.xrnx` →
  symlink to `renoise-tool/`, the same pattern `RenoiseChat` and `YTSampler` use, so
  editing the repo edits what Renoise loads. Verified byte-identical to the packaged
  `.xrnx` (`main.lua`, `wtlib.lua`, `zipwriter.lua`, `manifest.xml`).
- **Two Renoise instances were already running** (one 10h41m, one 27m) and were left
  alone. The tool appears on the *next* start, or on `Tools → Reload All Tools`. This
  is still the one thing not proven on this machine: nothing has been run inside a live
  Renoise, because restarting someone's session to test is not worth it.
- New `tests/load_test.lua` — the harness that was previously ad-hoc. It stubs the parts
  of the API the tool touches (`renoise.song/app/tool/ViewBuilder`, with a lazy
  self-returning stub so deep chains like `song.selected_sample.sample_buffer` resolve),
  puts the tool dir on `package.path` the way Renoise does, and runs the entry point.
  Checks: manifest parses and its `<Id>`/`ApiVersion` are right, deps resolve, `wtlib`
  and `zipwriter` return non-empty tables, and `main.lua` evaluates and runs. **6/6
  pass** under LuaJIT. Run it from the repo root: `luajit tests/load_test.lua`.

## `renoise-tools` published — the three `.xrnx` tools

New public repo: <https://github.com/mene311/renoise-tools> (local `~/Projects/renoise-tools`).

Scope was set deliberately: **Renoise tools only, not Python, final versions only.** So
the 50-odd Python scripts in `~/Projects/renoise/tools/` are *not* in it. What is:

| Tool | Version | Was |
|---|---|---|
| `com.meneses.PhraseToPattern` | 1.0 | only ever existed in the Renoise config dir — **first copy under version control** |
| `com.meneses.YTSampler` | 1.00 | `~/Projects/renoise/tools/yt-sampler/`, no repo |
| `com.meneses.RenoiseChat` | 0.10 | `~/Projects/renoise/chat/`, no repo |

`WavetableBuilder` is *not* duplicated there; the README points at this repo. `RenoiseChat`
is documented honestly as needing its `brain.mjs` daemon (TCP 127.0.0.1:19715), so the
`.xrnx` alone is half a tool.

### The archive shape bug — worth remembering

`build.sh` packs each tool dir into `dist/<Id>.xrnx`. **The first version made a zip with
the `<Id>.xrnx/` directory as the top-level entry, which installs nothing.** The official
guide (<https://renoise.github.io/xrnx/start/installing.html>) is explicit: *"only zip the
contents of the folder, not the folder itself"* — `manifest.xml` and `main.lua` must sit at
the archive root. Fixed, and `build.sh` now asserts `manifest.xml` is at the root and that
no `preferences.xml` shipped, because this is invisible until someone drags the file in.

- `preferences.xml` is Renoise runtime state written into a tool dir; it is gitignored and
  excluded from archives. `YTSampler` had one sitting next to `main.lua`; it was dropped.
- CI green on the first run (run `36144146666`, 23s): lints all three under `luac5.1`
  (Renoise embeds LuaJIT = 5.1), builds, re-checks the archive shape, uploads the artifact.
  Downloaded the artifact and re-verified all three unpack with `manifest.xml` at the root,
  `<Id>` matching the filename, and every `.lua` compiling.
- `renoise-hub` updated (`data.json` + rebuilt `index.html`, pushed `30138c8`) — the Tools
  section listed only `renoise-wavetable-tools` before.

### Not done, on purpose / still open

- [ ] **The Python tooling in `~/Projects/renoise/tools/` is still unpublished** (SFZ →
  `.xrni` conversion, the official-mirror and forum harvesters, the Renoise-format
  scanners). User scoped it out of this repo. It is 3.0 M and has no git at all.
- [ ] **The two converter copies are still unreconciled.** `tools/vitallfo_to_xrdp.py` is
  *newer and a superset* of the repo's: it has the repo's sparse/Curve/rotation path **and**
  `--dense`/`--no-align`. Every other wavetable tool in `tools/` (`wt_xrni.py`,
  `wt_catalogue.py`, `build_sweep_chain.py`) is also newer than what is published. The
  handoff warned the *published* presets came from the repo version, so this is a
  regenerate-and-compare job, not a copy. Still needs a decision.
- [ ] The wrap bug in the sparse LFO presets (two points, `0,0.0` and `48,1.0`, descending
  half missing) is still open, above.
