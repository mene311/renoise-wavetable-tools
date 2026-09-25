# LFO shapes and modulation sets

133 LFO shape presets and 133 sampler modulation sets, pulled out of Vital's LFO tables and
rebuilt as Renoise-native files. No plugins, no scripts to run: they're the same XML Renoise
itself writes, so they load as normal presets.

## Install

Copy both folders into your Renoise user library (Settings → User Library Path) so the layout
comes out as:

```
<User Library>/Effect Presets/LFO/*.xrdp
<User Library>/Modulation Sets/WT Shapes/*.xrno
```

From a terminal:

```sh
cp -r "Effect Presets/LFO" ~/.local/share/Renoise/User\ Library/Effect\ Presets/
cp -r "Modulation Sets/WT Shapes" ~/.local/share/Renoise/User\ Library/Modulation\ Sets/
```

The shape then appears in the LFO device's preset list, and the modulation set in the sampler's
modulation set list under WT Shapes.

## What's in them

The `.xrdp` files are LFO device presets, the same container Renoise uses for its own ones
(`FilterDevicePreset` wrapping a `LfoDevice` slot — that root name is Renoise's, not a mistake).
Names describe the shape: `12 Step`, `12 Min`, `1-2-1-1`, `1 Big 2 Little`, and so on.

The `.xrno` files are `SampleModulationSet` documents, which is what the sampler stores its
modulation sets in.

Both sets are the shapes the wavetable instruments use for their gate envelopes and for the
sweep rig, so they're handy on their own if you're building something similar by hand.

## Where they came from

`vitallfo_to_xrdp.py` and `vitallfo_to_xrno.py` in the repository root do the conversion: they
read Vital's LFO table JSON and emit these files. If you have your own Vital collection, point
the scripts at it and you'll get your shapes as Renoise presets.

## WT Sweep 16.xrdp

The shape the instruments carry baked in. Drop it on any LFO to get the same curve: a
triangle up and down over 16 lines, one step per pattern line, unipolar, no destination
set. The sweep rig in every instrument loads this shape inline, named `SWEEP`, so it never
depends on this file being present.
