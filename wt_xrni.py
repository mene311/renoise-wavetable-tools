#!/usr/bin/env python3
"""
wt_xrni — build native Renoise *wavetable* instruments (.xrni, doc_version 34).

Gate-scan wavetable architecture (verified against Kaidiak's "Modern Talking.xrni",
"Deep Throat.xrni", "Flenders ll.xrni" and the official
`Library/Instruments/Utility/{2,4,6,12} frame Wavetable Init.xrni`):

  * one frame = one looping single-cycle sample per DSP chain
  * every frame is mapped BaseNote<->full note range with Overlap=Play All, so all
    frames run at once
  * per frame one **frozen** LFO (Freq = 1e-6 = minimum) reads a *custom, unipolar,
    Lines* envelope containing a triangle for that frame only (peaks `--spacing`
    lines apart, triangle half-width = `--spacing`, so neighbouring triangles
    overlap and cross-fade with sum == 1)
  * that LFO modulates the frame's own **SampleMixer Volume** (DestTrack = frame
    chain, DestEffect 0, DestParameter 2)
  * instrument Macro 1 "WT Position" -> each gate LFO's *parameter 8* (the LFO
    position/phase, 0..1) -> sweeping the macro slides the read head through the
    triangles -> wavetable sweep
  * each frame chain ends in a SendDevice (MuteSource) into a final "SUM" chain

Frame sources
  --vitaltable T.vitaltable   extract the embedded frames from a Vital factory/user
                              wavetable (its "Wave Source" components carry raw
                              base64 float32 frames) and resample each cycle to a
                              usable length (--cycle-len, default 169 samples =
                              C-4 at 44.1 kHz)
  --frames DIR                a directory of .wav/.flac single-cycle frames
                              (equal length; use --resample-cycle to band-limit)
  --npy F.npy                 array (n_frames, n_samples)

Usage
  wt_xrni.py --vitaltable ~/.local/share/vital/Factory/Wavetables/Basic/"Basic Shapes.vitaltable" \
             --frames 12 --name "Vital Basic Shapes WT" --install
  wt_xrni.py --frames /tmp/frames --name "My WT" -o /tmp/out
"""
import argparse, base64, json, os, re, shutil, subprocess, sys, tempfile, wave, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKELETON = os.path.join(HERE, "template_clean.xrni")
SR = 44100
C4 = 440.0 * 2 ** ((48 - 57) / 12)   # Renoise C-4 (BaseNote 48)

# ----------------------------------------------------------------- sample xml
SAMPLE_TPL = """        <Sample>
          <SelectedPresetName>Init</SelectedPresetName>
          <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>
          <SelectedPresetIsModified>true</SelectedPresetIsModified>
          <Name>{name}</Name>
          <Volume>1.0</Volume>
          <Panning>0.5</Panning>
          <Transpose>0</Transpose>
          <Finetune>{finetune}</Finetune>
          <BeatSyncIsActive>false</BeatSyncIsActive>
          <BeatSyncMode>Repitch</BeatSyncMode>
          <BeatSyncLines>16</BeatSyncLines>
          <OneShotTrigger>false</OneShotTrigger>
          <NewNoteAction>NoteOff</NewNoteAction>
          <Oversample>true</Oversample>
          <InterpolationMode>Cubic</InterpolationMode>
          <AutoSeek>false</AutoSeek>
          <AutoFade>false</AutoFade>
          <LoopMode>Forward</LoopMode>
          <LoopRelease>false</LoopRelease>
          <LoopStart>0</LoopStart>
          <LoopEnd>{loop_end}</LoopEnd>
          <SingleSliceTriggerEnabled>true</SingleSliceTriggerEnabled>
          <IsAlias>false</IsAlias>
          <MuteGroupIndex>-1</MuteGroupIndex>
          <ModulationSetIndex>0</ModulationSetIndex>
          <DeviceChainIndex>{chain}</DeviceChainIndex>
          <Mapping>
            <Layer>Note-On Layer</Layer>
            <BaseNote>{base_note}</BaseNote>
            <NoteStart>0</NoteStart>
            <NoteEnd>119</NoteEnd>
            <MapKeyToPitch>true</MapKeyToPitch>
            <VelocityStart>0</VelocityStart>
            <VelocityEnd>127</VelocityEnd>
            <MapVelocityToVolume>true</MapVelocityToVolume>
          </Mapping>
          <DisplayStart>0</DisplayStart>
          <DisplayLength>{loop_end}</DisplayLength>
          <SelectionRangeStart>-1</SelectionRangeStart>
          <SelectionRangeEnd>-1</SelectionRangeEnd>
          <SelectedChannel>L+R</SelectedChannel>
          <VZoomFactor>1.0</VZoomFactor>
        </Sample>
"""

MIXER_TPL = """          <SampleMixerDevice type="SampleMixerDevice">
            <SelectedPresetName>Init</SelectedPresetName>
            <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>
            <SelectedPresetIsModified>false</SelectedPresetIsModified>
            <CustomDeviceName>{name}</CustomDeviceName>
            <IsMaximized>true</IsMaximized>
            <IsSelected>false</IsSelected>
            <IsActive>
              <Value>1.0</Value>
              <Visualization>Device only</Visualization>
            </IsActive>
            <Panning>
              <Value>0.5</Value>
              <Visualization>Device only</Visualization>
            </Panning>
            <Volume>
              <Value>{volume}</Value>
              <Visualization>Mixer and Device</Visualization>
            </Volume>
            <PostPanning>
              <Value>0.5</Value>
              <Visualization>Device only</Visualization>
            </PostPanning>
            <PostVolume>
              <Value>1.0</Value>
              <Visualization>Device only</Visualization>
            </PostVolume>
          </SampleMixerDevice>
"""

SEND_TPL = """          <SendDevice type="SendDevice">
            <SelectedPresetName>Init</SelectedPresetName>
            <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>
            <SelectedPresetIsModified>true</SelectedPresetIsModified>
            <IsMaximized>false</IsMaximized>
            <IsSelected>false</IsSelected>
            <IsActive>
              <Value>1.0</Value>
              <Visualization>Device only</Visualization>
            </IsActive>
            <SendAmount>
              <Value>1.0</Value>
              <Visualization>Mixer and Device</Visualization>
            </SendAmount>
            <SendPan>
              <Value>0.5</Value>
              <Visualization>Device only</Visualization>
            </SendPan>
            <DestSendTrack>
              <Value>{dest}</Value>
              <Visualization>Device only</Visualization>
            </DestSendTrack>
            <MuteSource>true</MuteSource>
            <SmoothParameterChanges>true</SmoothParameterChanges>
            <ApplyPostVolume>true</ApplyPostVolume>
          </SendDevice>
"""

LFO_TPL = """          <LfoDevice type="LfoDevice">
            <SelectedPresetName>Init</SelectedPresetName>
            <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>
            <SelectedPresetIsModified>true</SelectedPresetIsModified>
            <CustomDeviceName>{label}</CustomDeviceName>
            <IsMaximized>true</IsMaximized>
            <IsSelected>false</IsSelected>
            <IsActive>
              <Value>1.0</Value>
              <Visualization>Device only</Visualization>
            </IsActive>
            <DestTrack>
              <Value>{dest_track}</Value>
              <Visualization>Device only</Visualization>
            </DestTrack>
            <DestEffect>
              <Value>0.0</Value>
              <Visualization>Device only</Visualization>
            </DestEffect>
            <DestParameter>
              <Value>2</Value>
              <Visualization>Device only</Visualization>
            </DestParameter>
            <Amplitude>
              <Value>{amp}</Value>
              <Visualization>Device only</Visualization>
            </Amplitude>
            <Offset>
              <Value>{offset}</Value>
              <Visualization>Device only</Visualization>
            </Offset>
            <Frequency>
              <Value>9.99999997e-07</Value>
              <Visualization>Device only</Visualization>
            </Frequency>
            <Type>
              <Value>4</Value>
              <Visualization>Device only</Visualization>
            </Type>
            <CustomEnvelope>
              <PlayMode>Lines</PlayMode>
              <Length>{length}</Length>
              <ValueQuantum>0.0</ValueQuantum>
              <Polarity>Unipolar</Polarity>
              <Points>
{points}
              </Points>
            </CustomEnvelope>
            <CustomEnvelopeOneShot>false</CustomEnvelopeOneShot>
            <UseAdjustedEnvelopeLength>true</UseAdjustedEnvelopeLength>
          </LfoDevice>
"""

MACRO_TPL = """      <Macro0>
        <Value>0.0</Value>
        <Visualization>Device only</Visualization>
        <Name>WT Position</Name>
        <Mappings>
{mappings}        </Mappings>
      </Macro0>
"""

MAPPING_TPL = """          <Mapping>
            <DestChainType>SampleDSP</DestChainType>
            <DestChainIndex>0</DestChainIndex>
            <DestDeviceIndex>{dev}</DestDeviceIndex>
            <DestParameterIndex>8</DestParameterIndex>
            <Min>0.0</Min>
            <Max>1.0</Max>
            <Scaling>Linear</Scaling>
          </Mapping>
"""


# ------------------------------------------------------------------- helpers
def freq_to_note(f):
    """Renoise note number (C-4 == 48) + cents deviation for a frequency."""
    import math
    exact = 57 + 12 * math.log2(f / 440.0)
    note = int(round(exact))
    # Renoise: final pitch = played_note - base_note + transpose + finetune(cents),
    # so a *flat* sample (exact below the note) needs a POSITIVE finetune.
    cents = int(round((note - exact) * 100))
    note = max(0, min(119, note))
    return note, max(-128, min(127, cents))


def bandlimit_resample(cyc, n_out):
    """Ideal band-limited resample of one cycle to n_out samples (keeps harmonics
    up to n_out/2, i.e. no aliasing from the decimation)."""
    import numpy as np
    X = np.fft.rfft(cyc)
    keep = n_out // 2
    Y = np.zeros(keep + 1, dtype=complex)
    n = min(keep + 1, len(X))
    Y[:n] = X[:n]
    if n_out % 2 == 0:
        Y[keep] = X[keep].real if keep < len(X) else 0.0
    return np.fft.irfft(Y, n=n_out)


def _encode_job(args):
    """Worker for parallel frame encoding (module level so it can be pickled)."""
    samples, sr, dst = args
    return dst, encode_flac(samples, sr, dst)


def encode_frames(items, jobs=None):
    """items = [(samples_i16, sr, dst)]. Returns [(dst, nframes)] in order.
    One ffmpeg per frame is most of the build time, so run them in parallel."""
    if not jobs:            # None or 0 = auto
        jobs = int(os.environ.get("WT_JOBS", "0")) or min(8, (os.cpu_count() or 4))
    if jobs <= 1 or len(items) <= 1:
        return [(dst, encode_flac(samples, sr, dst)) for samples, sr, dst in items]
    # fork context: children do not re-import __main__, so this stays safe when the
    # module is imported by another script. Any failure falls back to serial.
    try:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        try:
            ctx = multiprocessing.get_context("fork")
        except ValueError:
            ctx = None
        with ProcessPoolExecutor(max_workers=min(jobs, len(items)), mp_context=ctx) as ex:
            return list(ex.map(_encode_job, items))
    except Exception:
        return [(dst, encode_flac(samples, sr, dst)) for samples, sr, dst in items]


def encode_flac(frames_i16, sr, dst):
    """Write frames (int16 array) to FLAC via ffmpeg; returns frame count."""
    import numpy as np
    tmp = dst + ".wav"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(frames_i16.astype("<i2").tobytes())
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", tmp, "-c:a", "flac",
                    "-compression_level", "8", dst], check=True)
    os.unlink(tmp)
    return len(frames_i16)


# ------------------------------------------------------------- frame sources
def _decode_vital_component(c, frame_size=None):
    """Returns (frames 2d array, sample_rate) for a Vital component, or (None, reason).
    Vital stores audio in two different ways:
      * "Wave Source"        -> keyframes[].wave_data   = base64 float32 frames (one cycle each)
      * "Audio File Source"  -> component.audio_file    = base64 int16 PCM, chunked by window_size
    """
    import numpy as np
    if c.get("audio_file"):
        raw = base64.b64decode(c["audio_file"])
        sr = int(c.get("audio_sample_rate") or SR)
        sizes = [frame_size] if frame_size else []
        if c.get("window_size"):
            sizes.append(int(float(c["window_size"])))
        sizes += [2048, 4096, 1024, 512, 256]
        for ws in dict.fromkeys(s for s in sizes if s):
            for skip in (0, 1, 4):
                for dt, name, scale in (("<i2", "int16", 32768.0), ("<f4", "float32", 1.0)):
                    n = (len(raw) - skip) // np.dtype(dt).itemsize
                    if n and n % ws == 0:
                        a = np.frombuffer(raw[skip:skip + n * np.dtype(dt).itemsize],
                                          dtype=dt).astype(np.float64) / scale
                        return a.reshape(-1, ws), sr
        return None, f"audio_file ({len(raw)} B) not divisible by any known frame size"
    wd = []
    for kf in c.get("keyframes") or []:
        if kf.get("wave_data"):
            wd.append(np.frombuffer(base64.b64decode(kf["wave_data"]), dtype="<f4").astype(np.float64))
    if wd:
        L = max(len(x) for x in wd)
        return np.array([np.pad(x, (0, L - len(x))) for x in wd]), SR
    return None, "component has no audio"


def select_table_frames(table, n, mode="even"):
    """Return (frames, idxs) of n frames from a table.
    'even' + n > len(table): blend adjacent table frames (phase-aligned upsampling)
    so a 4- or 8-frame table still fills all n slots.
    'spectral': farthest-first pick of the most different native frames."""
    import numpy as np
    N = len(table)
    if mode == "spectral" or n <= N:
        idxs = pick_frame_indices(table, n, mode)
        return [table[i] for i in idxs], idxs
    out = []
    for i in range(n):
        P = i * (N - 1) / (n - 1)
        lo = int(np.floor(P)); hi = min(lo + 1, N - 1); t = P - lo
        out.append(table[lo] * (1 - t) + table[hi] * t)
    return out, None


def pick_frame_indices(table, n, mode="even"):
    """Choose n frame indices out of a table. 'spectral' = farthest-first traversal
    on normalised magnitude spectra, which maximises how different the swept frames
    sound (even spacing often picks near-identical frames in long tables)."""
    import numpy as np
    N = len(table)
    if n >= N:
        return list(range(N))
    if mode != "spectral":
        return [round(i * (N - 1) / (n - 1)) for i in range(n)]
    mags = []
    for f in table:
        X = np.abs(np.fft.rfft(f))
        if len(X) > 256:                      # coarse log-ish band reduction
            X = X[:256]
        X = X / (X.sum() or 1.0)
        mags.append(X)
    mags = np.array(mags)
    idxs = [int(np.argmax(np.abs(table).max(axis=1)))]     # start on the loudest frame
    dist = np.full(N, np.inf)
    for _ in range(n - 1):
        d = np.abs(mags - mags[idxs[-1]]).sum(axis=1)
        dist = np.minimum(dist, d)
        dist[idxs] = -1
        idxs.append(int(np.argmax(dist)))
    return sorted(idxs)


def frame_brightness(frames):
    """Median spectral centroid in HARMONIC-NUMBER units (scale invariant): how bright
    a frame is relative to its own fundamental. 1-3 = classic shapes, 5-20 = bright
    growl/bass material, >30 = noise-like."""
    import numpy as np
    cs = []
    for a in frames:
        A = np.abs(np.fft.rfft(a)) ** 2
        k = np.arange(len(A))
        cs.append((k * A).sum() / max(A.sum(), 1e-9))
    return float(np.median(cs))


def auto_root(frames, target_centroid=600.0, root_min=41.2, root_max=523.25, sr=SR):
    """Choose a cycle length (= root note) so the frame's audible centroid lands in a
    comfortable register instead of screeching up top or vanishing down low.
    Returns (cycle_len, brightness, ideal_f0, used_f0)."""
    b = frame_brightness(frames)
    want = target_centroid / max(b, 0.5)
    f0 = min(max(want, root_min), root_max)
    return int(round(sr / f0)), b, want, f0


def root_report(name, frames, cycle_len, brightness=None, sr=SR):
    import numpy as np
    f0 = sr / cycle_len
    b = brightness if brightness is not None else frame_brightness(frames)
    note = 57 + 12 * np.log2(f0 / 440.0)
    base = int(round(note))            # the note this sample is naturally at
    print(f"  root report — {name}")
    print(f"    brightness          {b:6.1f} harmonics (centroid / fundamental)")
    print(f"    cycle length        {cycle_len} samples -> fundamental {f0:7.2f} Hz "
          f"(~note {int(round(note))}), {cycle_len//2} harmonics max")
    print(f"    centroid at root    {b*f0:7.0f} Hz")
    km = " | ".join(f"{lbl} {f0*2**((key-base)/12):7.1f} Hz"
                    for lbl, key in (("C-1", 24), ("C-2", 36), ("C-3", 48), ("C-4", 60), ("C-5", 72)))
    print(f"    keyboard map        {km}   (BaseNote {base})")


def detect_cycles(frame, rel=0.02):
    """How many cycles does this frame actually contain? GCD of the significant
    spectral bins: 1 means it is a single cycle, 8 means the frame repeats 8 times
    (and must be sliced before resampling, or it plays 8x too high)."""
    import numpy as np, math
    a = np.asarray(frame, dtype=np.float64)
    a = a - a.mean()
    X = np.abs(np.fft.rfft(a))
    if X.max() <= 0:
        return 1
    idx = [int(b) for b in np.nonzero(X > rel * X.max())[0] if b > 0]
    if not idx:
        return 1
    g = 0
    for b in idx:
        g = math.gcd(g, b)
        if g == 1:
            return 1
    return max(1, g)


def table_cycles(frames):
    """One cycle count for a whole table (frames of a table share a pitch)."""
    from collections import Counter
    gs = [detect_cycles(f) for f in frames]
    g, cnt = Counter(gs).most_common(1)[0]
    return g if (g > 1 and cnt >= max(2, len(frames) // 2)) else 1


def one_cycle(frame, cycles=None):
    """Slice a frame down to one cycle (averaging the repeats for a bit of noise
    rejection) so that resampling it does not multiply the pitch."""
    import numpy as np
    frame = np.asarray(frame, dtype=np.float64)
    g = int(cycles or detect_cycles(frame))
    if g <= 1:
        return frame
    n = len(frame) // g
    if n <= 0:
        return frame
    parts = np.array([frame[i * n:(i + 1) * n] for i in range(g)])
    return parts.mean(axis=0)



def _res(a, cycle_len):
    return a if not cycle_len else bandlimit_resample(a, cycle_len)


def frames_from_vital(path, n_frames, cycle_len, table=0, verbose=True, select='even', cycles=None):
    """Frames from a Vital .vitaltable OR a .vital preset (which embeds its
    wavetable inline at settings.wavetables[n])."""
    import numpy as np, bisect
    d = json.load(open(path))
    if "settings" in d:                       # .vital preset
        wts = (d["settings"] or {}).get("wavetables") or []
        if not wts:
            raise SystemExit(f"{path}: preset embeds no wavetable (it uses a factory table)")
        if table >= len(wts):
            raise SystemExit(f"{path}: preset has {len(wts)} tables, --table {table} out of range")
        d = wts[table]
        if verbose:
            print(f"   preset table {table}: {d.get('name')!r}")
    got = None
    for g in d.get("groups") or []:
        for c in g.get("components") or []:
            fr, sr = _decode_vital_component(c)
            if fr is not None:
                got = (fr, sr, c.get("type"))
                break
        if got:
            break
    if not got:
        raise SystemExit(f"{path}: no decodable audio component")
    table_frames, sr, kind = got
    if verbose:
        print(f"   {kind}: {table_frames.shape[0]} frames x {table_frames.shape[1]} samples @ {sr} Hz")
    cycles = cycles or table_cycles(table_frames)
    if cycles > 1 and verbose:
        print(f"   pitch detection: frames contain {cycles} cycles -> slicing one cycle")
    if n_frames <= 0:          # 0 = all native frames, no selection/blending
        return np.array([_res(one_cycle(f, cycles), cycle_len) for f in table_frames]), sr, cycle_len
    picked, idxs = select_table_frames(table_frames, n_frames, select)
    if verbose:
        print(f"   using {'interpolated' if idxs is None else 'frames'} "
              f"{idxs if idxs is not None else '0..%d blended' % (len(table_frames)-1)} "
              f"-> band-limited to {cycle_len}-sample cycles")
    return np.array([_res(one_cycle(f, cycles), cycle_len) for f in picked]), sr, cycle_len


def frames_from_serum_wav(path, n_frames, cycle_len, frame_size=None, verbose=True, select='even', cycles=None):
    """Frames from a Serum-style wavetable .wav (N frames x 2048 samples)."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le",
                          "-ac", "1", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    a = np.frombuffer(raw, dtype="<f4").astype(np.float64)
    sizes = [frame_size] if frame_size else []
    sizes += [2048, 4096, 1024, 512, 256]
    ws = next((s for s in sizes if s and len(a) % s == 0 and len(a) // s >= 2), None)
    if ws is None:
        raise SystemExit(f"{path}: {len(a)} samples is not an even number of known frame sizes")
    n = len(a) // ws
    tf = a.reshape(n, ws)
    if verbose:
        print(f"   wavetable: {n} frames x {ws} samples")
    cycles = cycles or table_cycles(tf)
    if cycles > 1 and verbose:
        print(f"   pitch detection: frames contain {cycles} cycles -> slicing one cycle")
    if n_frames <= 0:
        return np.array([_res(one_cycle(f, cycles), cycle_len) for f in tf]), SR, cycle_len
    picked, idxs = select_table_frames(tf, n_frames, select)
    if verbose:
        print(f"   using {'interpolated' if idxs is None else 'frames'} "
              f"{idxs if idxs is not None else '0..%d blended' % (len(tf)-1)} "
              f"-> band-limited to {cycle_len}-sample cycles")
    return np.array([_res(one_cycle(f, cycles), cycle_len) for f in picked]), SR, cycle_len


def frames_from_dir(path, resample_cycle=None, allow_mixed=False):
    import numpy as np
    files = sorted(f for f in os.listdir(path) if f.lower().endswith((".wav", ".flac", ".aiff", ".aif")))
    if not files:
        raise SystemExit(f"{path}: no .wav/.flac frames")
    out = []
    for f in files:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", os.path.join(path, f),
                              "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                             capture_output=True, check=True).stdout
        out.append(np.frombuffer(raw, dtype="<f4").astype(np.float64))
    n = {len(a) for a in out}
    if len(n) != 1 and not allow_mixed:
        raise SystemExit(f"frames have differing lengths {sorted(n)} — resample them first "
                         "(or pass --mixed-lengths if that is intentional, e.g. one pitch per frame)")
    if resample_cycle:
        out = [bandlimit_resample(a, resample_cycle) for a in out]
    # differing lengths are only legal for special cases (one pitch per frame): keep a list
    return (np.array(out) if len(n) == 1 else out), SR, (resample_cycle or len(out[0]))


def load_source(path, n_frames, cycle_len, frame_size=None, table=0, select='even', allow_mixed=False, cycles=None):
    if os.path.isdir(path):
        print(f"frame dir: {path}")
        return frames_from_dir(path, cycle_len, allow_mixed)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".vitaltable", ".vital"):
        print(f"vital: {path}")
        return frames_from_vital(path, n_frames, cycle_len, table=table, select=select, cycles=cycles)
    if ext in (".wav", ".flac", ".aif", ".aiff"):
        print(f"wavetable file: {path}")
        return frames_from_serum_wav(path, n_frames, cycle_len, frame_size, select=select, cycles=cycles)
    raise SystemExit(f"{path}: unsupported source (use .vitaltable/.vital, a Serum-style .wav, or a frame directory)")


# ------------------------------------------------------------------- builder
def triangle_points(n_frames, spacing, frame_idx):
    """Envelope points for one frame's gate: a triangle peaking at line
    frame_idx*spacing, spanning +/-spacing lines, wrapping around the cycle."""
    L = n_frames * spacing
    peak = frame_idx * spacing
    pts = []
    for x in range(L + 1):
        d = (x - peak) % L
        if d > L / 2:
            d -= L
        v = max(0.0, 1.0 - abs(d) / spacing)
        pts.append(f"                <Point>{x},{v:.6f},0.0</Point>")
    return L, pts


def lowpass_frames(frames, f0, hz, taper=0.5):
    """Band-limit single-cycle frames to `hz` at playback root `f0`: keeps harmonics
    up to hz/f0 and fades the top `taper` fraction of those out smoothly, so bright
    growl tables stop screeching without turning into a buzzsaw."""
    import numpy as np
    if not hz or hz <= 0:
        return frames
    keep = max(2, int(hz / max(f0, 1e-9)))
    out = []
    for a in frames:
        X = np.fft.rfft(a)
        n = min(keep + 1, len(X))
        fade_from = max(1, int(keep * (1.0 - taper)))
        w = np.ones(len(X))
        w[n:] = 0.0
        if fade_from < keep:
            w[fade_from:keep + 1] = 0.5 * (1 + np.cos(np.pi * (np.arange(fade_from, keep + 1) - fade_from)
                                                     / max(1, keep - fade_from)))
        out.append(np.fft.irfft(X * w, n=len(a)))
    return np.array(out)


def build(frames, name, sr, cycle_len, out_path, spacing=2, gate_amp=1.0,
          gate_offset=0.0, base_volume=0.0, base_note=None, finetune=None,
          source="", jobs=None):
    import numpy as np
    n = len(frames)
    if n < 2:
        raise SystemExit("need at least 2 frames")
    if n > 12:
        print(f"  !! {n} frames: Renoise allows only 12 voices per note column — "
              "the 13th+ frames will be cut off")
    if base_note is None or finetune is None:
        bn, ft = freq_to_note(sr / cycle_len)
        base_note = bn if base_note is None else base_note
        finetune = ft if finetune is None else finetune

    tmp = tempfile.mkdtemp(prefix="wt_xrni_")
    todo = []
    for i, f in enumerate(frames):
        a = np.asarray(f, dtype=np.float64)
        peak = np.abs(a).max()
        if peak > 0:
            a = a / peak
        fname = f"Sample{i:02d} (frame {i+1:02d}).flac"
        todo.append((np.clip(a, -1, 1) * 32767.0, sr, os.path.join(tmp, fname)))
    encoded = encode_frames(todo, jobs)
    audio = [os.path.basename(dst) for dst, _ in encoded]
    samples_xml = [SAMPLE_TPL.format(name=f"frame {i+1:02d}", finetune=finetune,
                                    loop_end=nf, chain=i + 1, base_note=base_note)
                   for i, (_, nf) in enumerate(encoded)]

    # --- device chains: chain 0 = gates (LFOs), 1..n = frame chains, n+1 = SUM
    sum_idx = n + 1
    chains = []
    gate_devs = [MIXER_TPL.format(name="GATES", volume="1.0")]
    for i in range(n):
        L, pts = triangle_points(n, spacing, i)
        gate_devs.append(LFO_TPL.format(label=f"gate {i+1:02d}", dest_track=i + 1,
                                        amp=f"{gate_amp:g}", offset=f"{gate_offset:g}",
                                        length=L, points="\n".join(pts)))
    chains.append((f"GATES", "\n".join(gate_devs)))
    for i in range(n):
        chains.append((f"FRAME {i+1:02d}",
                       MIXER_TPL.format(name="Mixer", volume=f"{base_volume:g}")
                       + SEND_TPL.format(dest=sum_idx)))
    chains.append(("SUM", MIXER_TPL.format(name="Mixer", volume="1.0")))

    dc_xml = "    <DeviceChains>\n"
    for ci, (nm, devs) in enumerate(chains):
        dc_xml += f"""      <DeviceChain>
        <SelectedPresetName>Init</SelectedPresetName>
        <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>
        <SelectedPresetIsModified>true</SelectedPresetIsModified>
        <Devices>
{devs}        </Devices>
        <Name>{nm}</Name>
        <RoutingIndex>-1</RoutingIndex>
      </DeviceChain>
"""
    dc_xml += "    </DeviceChains>\n"

    mappings = "".join(MAPPING_TPL.format(dev=i + 1) for i in range(n))

    with zipfile.ZipFile(SKELETON) as z:
        xml = z.read("Instrument.xml").decode("utf-8")
    xml = re.sub(r"<Name>[^<]*</Name>", f"<Name>{name}</Name>", xml, count=1)
    xml = xml.replace("<SelectedSampleIndex>-1</SelectedSampleIndex>",
                      "<SelectedSampleIndex>0</SelectedSampleIndex>", 1)
    xml = xml.replace("<MacrosVisible>false</MacrosVisible>", "<MacrosVisible>true</MacrosVisible>", 1)
    xml = re.sub(r"\s*<Macro0>\s*<Value>50</Value>\s*<Visualization>Device only</Visualization>\s*"
                 r"<Name>Macro 1</Name>\s*</Macro0>",
                 "\n" + MACRO_TPL.format(mappings=mappings).rstrip(), xml, count=1)
    if "WT Position" not in xml:
        raise SystemExit("could not install the WT Position macro into the skeleton")
    xml = xml.replace("<SampleGenerator>\n",
                      "<SampleGenerator>\n      <Samples>\n" + "".join(samples_xml) +
                      "      </Samples>\n", 1)
    xml = xml.replace("    <SelectedDeviceChainIndex>-1</SelectedDeviceChainIndex>",
                      dc_xml + "    <SelectedDeviceChainIndex>0</SelectedDeviceChainIndex>", 1)
    if "<DeviceChains>" not in xml:
        raise SystemExit("could not inject device chains into the skeleton")

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Instrument.xml", xml)
        for fname in audio:
            z.write(os.path.join(tmp, fname), f"SampleData/{fname}")
    shutil.rmtree(tmp, ignore_errors=True)

    print(f"  {name}: {n} frames, {cycle_len} samples/cycle @ {sr} Hz, "
          f"BaseNote {base_note}, Finetune {finetune:+d} cents, "
          f"gate amp {gate_amp:g}/offset {gate_offset:g} on mixer volume {base_volume:g}, "
          f"envelope {n*spacing} lines")
    print(f"  -> {out_path} ({os.path.getsize(out_path)/1024:.0f} KB)")


def write_manifest(out_path, **kw):
    """Record build provenance next to the output so wt_verify can reproduce it."""
    import json, datetime
    man = os.path.join(os.path.dirname(os.path.abspath(out_path)), "wt_build_manifest.json")
    entries = json.load(open(man)) if os.path.exists(man) else []
    entries = [e for e in entries if e.get("xrni") != os.path.basename(out_path)]
    kw["xrni"] = os.path.basename(out_path)
    kw["built"] = datetime.datetime.now().isoformat(timespec="seconds")
    entries.append(kw)
    json.dump(entries, open(man, "w"), indent=1)


def validate(path):
    v = os.path.join(HERE, "validate_xrni.py")
    if os.path.exists(v):
        subprocess.run([sys.executable, v, path])
    xsd = "/usr/local/share/renoise-3.5.4/Schemas/RenoiseInstrument34.xsd"
    if os.path.exists(xsd) and shutil.which("xmllint"):
        with tempfile.TemporaryDirectory() as td:
            with zipfile.ZipFile(path) as z:
                x = z.read("Instrument.xml")
            f = os.path.join(td, "i.xml")
            open(f, "wb").write(x)
            r = subprocess.run(["xmllint", "--noout", "--schema", xsd, f],
                               capture_output=True, text=True)
            print("  xmllint schema:", "OK" if r.returncode == 0 else "FAIL")
            if r.returncode:
                print(r.stderr.strip()[:800])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="anything: .vitaltable, .vital preset, Serum-style .wav wavetable, or a dir of frames")
    ap.add_argument("--vitaltable", help="Vital .vitaltable or .vital preset (alias of --source)")
    ap.add_argument("--wavetable", help="Serum-style wavetable .wav (N frames x 2048 samples)")
    ap.add_argument("--frames", help="directory of single-cycle .wav/.flac frames")
    ap.add_argument("--table", type=int, default=0, help="which embedded table (for .vital presets)")
    ap.add_argument("--frame-size", type=int, help="frame size for .wav wavetables (default: auto)")
    ap.add_argument("--jobs", type=int, default=0,
                    help="parallel frame encoders (0 = auto: min(8, cpus), 1 = serial)")
    ap.add_argument("--mixed-lengths", action="store_true",
                    help="allow frame files of different lengths (e.g. one pitch per frame)")
    ap.add_argument("--select", choices=["even", "spectral"], default="even",
                    help="which table frames to use: evenly spaced, or maximally different (spectral)")
    ap.add_argument("--npy", help=".npy array (n_frames, n_samples)")
    ap.add_argument("--name", help="instrument name (required unless --report)")
    ap.add_argument("--n-frames", type=int, default=12, help="frames to build from a vitaltable (max 12)")
    ap.add_argument("--root", choices=["auto", "keep"], default="keep",
                    help="'auto' picks the cycle length (=root note) from the frames' brightness")
    ap.add_argument("--target-centroid", type=float, default=600.0,
                    help="desired audible centroid in Hz for --root auto (default 600)")
    ap.add_argument("--root-min", type=float, default=41.2, help="lowest root the auto picker may choose (Hz)")
    ap.add_argument("--root-max", type=float, default=261.63,
                    help="highest root the auto picker may choose (Hz; default C-4 — never brighter than that)")
    ap.add_argument("--lowpass", type=float, default=0.0,
                    help="band-limit the frames to this frequency (Hz) at the chosen root, "
                         "with a soft rolloff; use it to tame bright growl/bass tables")
    ap.add_argument("--taper", type=float, default=0.5, help="fraction of the kept band that fades out")
    ap.add_argument("--report", action="store_true", help="print the brightness/root analysis and exit")
    ap.add_argument("--cycle-len", type=int, default=169,
                    help="samples per cycle when extracting (169 = C-4 @44.1k)")
    ap.add_argument("--resample-cycle", type=int, help="band-limit resample frame dirs to this cycle length")
    ap.add_argument("--spacing", type=int, default=2, help="envelope lines between gate peaks")
    ap.add_argument("--gate-amp", type=float, default=1.0)
    ap.add_argument("--gate-offset", type=float, default=0.0)
    ap.add_argument("--base-volume", type=float, default=0.0,
                    help="frame SampleMixer Volume the gate modulates (0 = gate from silence)")
    ap.add_argument("--base-note", type=int)
    ap.add_argument("--finetune", type=int)
    ap.add_argument("-o", "--outdir", default="/tmp/wt_out")
    ap.add_argument("--install", action="store_true",
                    help="copy into 'User Library/Instruments/Wavetables/'")
    a = ap.parse_args()
    if not a.name and not a.report:
        ap.error("--name is required unless you are just --report-ing")

    os.makedirs(a.outdir, exist_ok=True)
    src = a.source or a.vitaltable or a.wavetable or a.frames
    if src:
        cycle = a.cycle_len or a.resample_cycle
        bright = None
        if a.root == "auto" or a.report:
            native, _, _ = load_source(src, 0, 0, frame_size=a.frame_size, table=a.table,
                                       select=a.select, allow_mixed=a.mixed_lengths)
            import numpy as _np
            clen, bright, want, f0 = auto_root(_np.atleast_2d(native), a.target_centroid,
                                               a.root_min, a.root_max)
            if a.report:
                print(f"\n{bright and ''}")
                root_report(os.path.basename(src), _np.atleast_2d(native), clen, bright)
                print(f"    (unclamped ideal root would be {want:6.2f} Hz)"
                      + ("  [clamped]" if abs(want - f0) > 1e-6 else ""))
                print(f"    -> suggested: --cycle-len {clen} --root keep\n")
                return
            cycle = clen
            print(f"  auto root: brightness {bright:.1f} -> {cycle} samples/cycle "
                  f"({44100/cycle:.1f} Hz), centroid {bright*44100/cycle:.0f} Hz")
        frames, sr, cycle = load_source(src, a.n_frames, cycle,
                                        frame_size=a.frame_size, table=a.table, select=a.select,
                                        allow_mixed=a.mixed_lengths)
        if a.lowpass:
            import numpy as _np
            f0 = sr / float(cycle or len(_np.atleast_2d(frames)[0]))
            frames = lowpass_frames(_np.atleast_2d(frames), f0, a.lowpass, a.taper)
            kept = max(2, int(a.lowpass / max(f0, 1e-9)))
            print(f"  lowpass: {a.lowpass:.0f} Hz at root {f0:.1f} Hz -> keeping "
                  f"{kept} harmonics ({kept*f0:.0f} Hz ceiling)")
    elif a.npy:
        import numpy as np
        src = a.npy
        frames = np.load(a.npy)
        sr, cycle = SR, len(frames[0])
    else:
        raise SystemExit("need --vitaltable, --frames or --npy")

    out = os.path.join(a.outdir, re.sub(r"[^\w. (),-]+", "_", a.name) + ".xrni")
    build(frames, a.name, sr, cycle, out, spacing=a.spacing, gate_amp=a.gate_amp,
          jobs=a.jobs,
          gate_offset=a.gate_offset, base_volume=a.base_volume, base_note=a.base_note,
          finetune=a.finetune, source=src)
    validate(out)
    write_manifest(out, name=a.name, source=src, n_frames=len(frames), cycle_len=cycle,
                   sr=sr, select=a.select, spacing=a.spacing, gate_amp=a.gate_amp,
                   gate_offset=a.gate_offset, base_volume=a.base_volume)
    if a.install:
        dest_dir = os.path.expanduser("~/.local/share/Renoise/User Library/Instruments/Wavetables")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(out))
        shutil.copy2(out, dest)
        print(f"  installed -> {dest}")


if __name__ == "__main__":
    main()
