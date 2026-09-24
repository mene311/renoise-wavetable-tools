#!/usr/bin/env python3
"""
build_sweep_chain — write a Renoise effect chain preset (.xrnt) that sweeps a wavetable
instrument the way a Vital patch would: one shape driving table position, filter and gain.

    build_sweep_chain.py [-o OUTDIR] [--name "Wavetable Sweep"] [--rate 8] [--sweep-shape]

Chain, in track order:

    0 INSTR MACRO   Instrument Macros device, so macro 1 (WT Position) is reachable here
    1 GAIN          Gainer (volume)
    2 LP FILTER     Analog Filter (cutoff)
    3 SWEEP         LFO with a triangle scan shape -> LP FILTER cutoff
    4 HYDRA         Hydra, three outputs wired to INSTR MACRO.1, LP FILTER cutoff, GAIN volume

Destination parameters used here, read off Renoise's own chains rather than guessed:

    track device numbering is 1 based (device 1 = the first in the chain)
    Gainer   volume   = param 2   (Renoise's Tutorial - Sound Design & Meta Devices)
    Filter   cutoff   = param 2   (Filter Wobble.xrnt, Hip Pass.xrnt)
    LFO      Reset    = param 8   (the wavetable templates drive WT Position through it)

The Hydra's own input is not wired: none of Renoise's bundled chains feed a Hydra from
another device, so its param index is not something this tool can copy from a real file.
Drag the SWEEP LFO's destination onto it, or automate its input.
"""
import argparse, os, re, sys, xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wt_xrni as wt                       # noqa: E402  (for the shape maths)

OUT_DEFAULT = os.path.expanduser("~/.local/share/Renoise/User Library/Effect Chains")

HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<RenoiseDeviceChain doc_version="21">
  <SelectedPresetName>Init</SelectedPresetName>
  <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>
  <SelectedPresetIsModified>false</SelectedPresetIsModified>
  <Devices>
"""

FOOTER = """  </Devices>
</RenoiseDeviceChain>
"""


def p(name, value, viz="Device only"):
    return f"      <{name}>\n        <Value>{value}</Value>\n        <Visualization>{viz}</Visualization>\n      </{name}>\n"


def b(name, value):
    """Flags in a chain preset are simple booleans, not parameter blocks."""
    return f"      <{name}>{str(value).lower()}</{name}>\n"


def macro_device(macro_name="WT Position"):
    s = '    <InstrumentMacroDevice type="InstrumentMacroDevice">\n'
    s += b("IsMaximized", True) + b("IsSelected", True)
    s += '      <SelectedPresetName>Init</SelectedPresetName>\n'
    s += '      <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>\n'
    s += '      <SelectedPresetIsModified>true</SelectedPresetIsModified>\n'
    s += p("IsActive", "1.0")
    for i in range(8):
        s += p(f"ParameterValue{i}", "0.0")
    s += '      <CustomDeviceName>INSTR MACRO</CustomDeviceName>\n'
    s += "    </InstrumentMacroDevice>\n"
    return s


def gainer_device():
    s = '    <GainerDevice type="GainerDevice">\n'
    s += b("IsMaximized", True) + b("IsSelected", False)
    s += '      <SelectedPresetName>Init</SelectedPresetName>\n'
    s += '      <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>\n'
    s += '      <SelectedPresetIsModified>false</SelectedPresetIsModified>\n'
    s += p("IsActive", "1.0") + p("Volume", "1.0", "Mixer and Device") + p("Panning", "0.5")
    s += '      <LPhaseInvert>false</LPhaseInvert>\n      <RPhaseInvert>false</RPhaseInvert>\n'
    s += '      <SmoothParameterChanges>true</SmoothParameterChanges>\n'
    s += '      <CustomDeviceName>GAIN</CustomDeviceName>\n'
    s += "    </GainerDevice>\n"
    return s


def filter_device():
    s = '    <AnalogFilterDevice type="AnalogFilterDevice">\n'
    s += b("IsMaximized", True) + b("IsSelected", False)
    s += '      <SelectedPresetName>Init</SelectedPresetName>\n'
    s += '      <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>\n'
    s += '      <SelectedPresetIsModified>false</SelectedPresetIsModified>\n'
    s += p("IsActive", "1.0")
    s += '      <OversamplingFactor>2x</OversamplingFactor>\n'
    s += '      <Model>2P K35</Model>\n'
    s += p("Type", "0.0") + p("Cutoff", "1.0", "Mixer and Device")
    s += p("Resonance", "0.0") + p("Inertia", "0.0078125") + p("Drive", "0.0")
    s += b("ShowResponseView", True) + b("ResponseViewMaxGain", 18)
    s += '      <CustomDeviceName>LP FILTER</CustomDeviceName>\n'
    s += "    </AnalogFilterDevice>\n"
    return s


def lfo_device(name, dest_effect, dest_param, rate, shape_points, length):
    s = '    <LfoDevice type="LfoDevice">\n'
    s += b("IsMaximized", True) + b("IsSelected", False)
    s += '      <SelectedPresetName>Init</SelectedPresetName>\n'
    s += '      <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>\n'
    s += '      <SelectedPresetIsModified>true</SelectedPresetIsModified>\n'
    s += p("IsActive", "1.0") + p("DestTrack", "-1") + p("DestEffect", dest_effect)
    s += p("DestParameter", dest_param) + p("Amplitude", "1.0") + p("Offset", "0.0")
    s += p("Frequency", f"{rate:g}") + p("Type", "4")   # no Reset: every real file omits it (default 0)
    s += "      <CustomEnvelope>\n        <PlayMode>Lines</PlayMode>\n"
    s += f"        <Length>{length}</Length>\n        <ValueQuantum>0.0</ValueQuantum>\n"
    s += "        <Polarity>Unipolar</Polarity>\n        <Points>\n"
    for i, v in enumerate(shape_points):
        s += f"          <Point>{i},{v:.4f},0.0</Point>\n"
    s += "        </Points>\n      </CustomEnvelope>\n"
    s += '      <CustomEnvelopeOneShot>false</CustomEnvelopeOneShot>\n'
    s += '      <UseAdjustedEnvelopeLength>true</UseAdjustedEnvelopeLength>\n'
    s += f'      <CustomDeviceName>{name}</CustomDeviceName>\n'
    s += "    </LfoDevice>\n"
    return s


def hydra_device(outs):
    """outs = [(dest_effect, dest_param)] for the first three outputs."""
    s = '    <HydraDevice type="HydraDevice">\n'
    s += b("IsMaximized", True) + b("IsSelected", False)
    s += '      <SelectedPresetName>Init</SelectedPresetName>\n'
    s += '      <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>\n'
    s += '      <SelectedPresetIsModified>true</SelectedPresetIsModified>\n'
    s += p("IsActive", "1.0") + b("VisiblePages", 1) + p("InputValue", "0.0", "Mixer and Device")
    for i in range(1, 10):
        e, pa = outs[i - 1] if i <= len(outs) else (-1, -1)
        s += p(f"Out{i}DestTrack", "-1") + p(f"Out{i}DestEffect", e) + p(f"Out{i}DestParameter", pa)
        s += p(f"Out{i}Min", "0.0") + p(f"Out{i}Max", "1.0")
        s += f"      <Out{i}Scaling>Linear</Out{i}Scaling>\n"
    s += '      <CustomDeviceName>HYDRA</CustomDeviceName>\n'
    s += "    </HydraDevice>\n"
    return s


def scan_shape(length=16):
    """Triangle sweep: up over the first half, down over the second."""
    return [abs(1 - 2 * (i / (length - 1))) for i in range(length)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--outdir", default=OUT_DEFAULT)
    ap.add_argument("--name", default="Wavetable Sweep")
    ap.add_argument("--rate", type=float, default=8.0, help="LFO rate in lines per cycle")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    shape = scan_shape(16)
    # 1 based device indices: 1 INSTR MACRO, 2 GAIN, 3 LP FILTER, 4 SWEEP, 5 HYDRA
    devices = (
        macro_device()
        + gainer_device()
        + filter_device()
        + lfo_device("SWEEP", dest_effect=3, dest_param=2, rate=a.rate,
                     shape_points=shape, length=16)
        + hydra_device([(1, 2), (3, 2), (2, 2)])
    )
    xml = HEADER + devices + FOOTER
    os.makedirs(a.outdir, exist_ok=True)
    out = os.path.join(a.outdir, a.name + ".xrnt")
    if not a.dry:
        with open(out, "w", encoding="utf-8") as f:
            f.write(xml)
    print(f"{'would write' if a.dry else 'wrote'} {out}")
    print("  0 INSTR MACRO  macro 1 = WT Position (param 2)")
    print("  1 GAIN         volume (param 2)")
    print("  2 LP FILTER    cutoff (param 2)")
    print(f"  3 SWEEP        shaped LFO at {a.rate:g} LPC -> LP FILTER cutoff")
    print("  4 HYDRA        out 1 -> INSTR MACRO.1, out 2 -> LP FILTER cutoff, out 3 -> GAIN volume")
    # validate if the schema is around
    xsd = "/usr/local/share/renoise-3.5.4/Schemas/RenoiseDeviceChain21.xsd"
    if os.path.exists(xsd) and os.path.exists(out):
        import subprocess
        r = subprocess.run(["xmllint", "--noout", "--schema", xsd, out],
                           capture_output=True, text=True)
        print("  schema:", "OK" if r.returncode == 0 else "FAIL")
        if r.returncode:
            print("   ", r.stderr.strip().splitlines()[:4])


if __name__ == "__main__":
    main()
