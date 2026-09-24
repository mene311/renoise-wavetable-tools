#!/usr/bin/env python3
"""
vitallfo_to_xrno — migrate Vital LFO shapes (.vitallfo) into Renoise modulation sets
(.xrno) so they behave per-voice, the way Vital's LFOs do.

    vitallfo_to_xrno.py [FILES_OR_DIRS...] [-o OUTDIR] [--target Volume|Pitch|Panning|Cutoff]
                        [--smoothing 2] [--dry]

A modulation set is the instrument's per-sample modulation chain: it runs once per voice,
unlike a track LFO which is global. The shape goes into the drawable envelope device
(`SampleEnvelopeModulationDevice`), looped over the cycle, tempo-synced so the length is
counted in pattern lines. Mapping rules are the same as the device presets:

    staircases (flat or vertical segments only) -> PlayMode Points, sparse points
    everything else                             -> PlayMode Lines, one point per grid line
"""
import argparse, glob, os, sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from vitallfo_to_xrdp import read_lfo, segment_values, grid_length, is_staircase  # noqa: E402

OUT_DEFAULT = os.path.expanduser("~/.local/share/Renoise/User Library/Modulation Sets/WT Shapes")

WRAPPER_XSD = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" elementFormDefault="qualified">
  <xs:include schemaLocation="/usr/local/share/renoise-3.5.4/Schemas/RenoiseInstrument34.xsd"/>
  <xs:element name="SampleModulationSet" type="SampleModulationSet"/>
</xs:schema>
"""

TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<SampleModulationSet doc_version="2">
  <Devices>
    <SampleEnvelopeModulationDevice type="SampleEnvelopeModulationDevice">
      <IsMaximized>true</IsMaximized>
      <IsSelected>true</IsSelected>
      <SelectedPresetName>Init</SelectedPresetName>
      <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>
      <SelectedPresetIsModified>true</SelectedPresetIsModified>
      <IsActive>
        <Value>1.0</Value>
        <Visualization>Device only</Visualization>
      </IsActive>
      <Target>{target}</Target>
      <Operator>+</Operator>
      <Bipolar>false</Bipolar>
      <TempoSynced>true</TempoSynced>
      <SustainIsActive>false</SustainIsActive>
      <SustainPos>96</SustainPos>
      <LoopStart>0</LoopStart>
      <LoopEnd>{length}</LoopEnd>
      <LoopMode>Forward</LoopMode>
      <Decay>
        <Value>100</Value>
        <Visualization>Device only</Visualization>
      </Decay>
      <Nodes>
        <PlayMode>{playmode}</PlayMode>
        <Length>{length}</Length>
        <ValueQuantum>0.0</ValueQuantum>
        <Polarity>Unipolar</Polarity>
        <Points>
{points}
        </Points>
      </Nodes>
    </SampleEnvelopeModulationDevice>
  </Devices>
  <Name>{name}</Name>
  <FilterType>0</FilterType>
  <FilterBankVersion>3</FilterBankVersion>
  <FilterDrive>0.0</FilterDrive>
  <PitchModulationRange>80</PitchModulationRange>
  <VolumeInputValue>1.0</VolumeInputValue>
  <PanningInputValue>0.0</PanningInputValue>
  <PitchInputValue>0.0</PitchInputValue>
  <CutoffInputValue>127</CutoffInputValue>
  <ResonanceInputValue>64.9</ResonanceInputValue>
</SampleModulationSet>
"""


def build(path, target, smoothing):
    name, pts, smooth = read_lfo(path)
    length = grid_length(pts)
    if is_staircase(pts):
        grid, xs = {}, sorted({p[0] for p in pts})
        for x, y, _ in pts:
            line = max(0, min(length, int(round(x * length))))
            if line == length and line in grid:
                continue                     # wrap value: keep what the ramp ends on
            grid[line] = max(0.0, min(1.0, y))
        points = "\n".join(f"          <Point>{k},{grid[k]:.4f},0.0</Point>" for k in sorted(grid))
        mode, npts = "Points", len(grid)
    else:
        xs = [i / length for i in range(length + 1)]
        vals = segment_values(pts, xs)
        for _ in range(max(0, smoothing) if smooth else 0):
            vals = [vals[0]] + [(vals[i - 1] + 2 * vals[i] + vals[i + 1]) / 4
                                for i in range(1, len(vals) - 1)] + [vals[-1]]
        points = "\n".join(f"          <Point>{i},{max(0.0, min(1.0, v)):.4f},0.0</Point>"
                           for i, v in enumerate(vals))
        mode, npts = "Lines", len(vals)
    xml = TEMPLATE.format(target=target, length=length, playmode=mode, points=points, name=name)
    return name, xml, dict(mode=mode, length=length, points=npts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="*")
    ap.add_argument("-o", "--outdir", default=OUT_DEFAULT)
    ap.add_argument("--target", default="Volume",
                    help="what the shape modulates per voice: Volume, Pitch, Panning, Cutoff")
    ap.add_argument("--smoothing", type=int, default=2)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    srcs = a.sources or [os.path.expanduser("~/.local/share/vital")]
    files = []
    for s in srcs:
        files += (sorted(glob.glob(os.path.join(s, "**", "*.vitallfo"), recursive=True))
                  if os.path.isdir(s) else [s])
    os.makedirs(a.outdir, exist_ok=True)

    xsd = os.path.join(a.outdir, ".wt_modset.xsd")
    if not a.dry:
        with open(xsd, "w") as f:
            f.write(WRAPPER_XSD)

    print(f"{'modulation set':30s} {'mode':7s} {'len':>4s} {'pts':>4s}  source")
    ok = skipped = 0
    taken = set()
    for f in files:
        try:
            name, xml, info = build(f, a.target, a.smoothing)
        except Exception as e:
            skipped += 1
            print(f"  skipped {os.path.basename(f)}: {e}")
            continue
        safe = "".join(c for c in name if c.isalnum() or c in " -_().,").strip() or "shape"
        stem, n = safe, 2
        while stem.lower() in taken:
            stem = f"{safe} {n}"; n += 1
        taken.add(stem.lower())
        out = os.path.join(a.outdir, stem + ".xrno")
        if not a.dry:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(xml)
        ok += 1
        print(f"{stem[:30]:30s} {info['mode']:7s} {info['length']:4d} {info['points']:4d}  "
              f"{os.path.basename(f)}")
    print(f"\n{'would write' if a.dry else 'wrote'} {ok} modulation sets ({a.target}) to {a.outdir}"
          + (f", {skipped} skipped" if skipped else ""))

    if not a.dry and os.path.exists(xsd):
        import subprocess
        bad = 0
        for f in sorted(glob.glob(os.path.join(a.outdir, "*.xrno"))):
            r = subprocess.run(["xmllint", "--noout", "--schema", xsd, f],
                               capture_output=True, text=True)
            if r.returncode:
                bad += 1
                if bad <= 3:
                    print(f"  invalid {os.path.basename(f)}: "
                          f"{r.stderr.strip().splitlines()[:1]}")
        print(f"schema check: {ok - bad}/{ok} valid against RenoiseInstrument34.xsd")


if __name__ == "__main__":
    main()
