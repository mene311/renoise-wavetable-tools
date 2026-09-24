/*
  wt-builder.js — build Renoise gate-scan wavetable instruments entirely in the browser.

  Mirrors renoise-wavetable-tools/wt_xrni.py, because that output is validated against
  Renoise's own RenoiseInstrument34.xsd. Where the two disagree, this file is wrong.

  Sources it reads:
    .vitaltable / .vital  Vital JSON. Frames live either in keyframes[].wave_data
                          (base64 float32) or in component.audio_file (base64 int16 PCM
                          chopped by window_size).
    .wav                  Serum-style wavetable: N frames of frameSize samples, PCM 16/24/32
                          bit or 32 bit float. Parsed by hand rather than via Web Audio,
                          because decodeAudioData resamples to the audio context rate.
    .npy                  not supported in the browser.

  What it produces: an .xrni (zip, store only) containing Instrument.xml plus one WAV per
  frame in SampleData/.
*/
(function (global) {
  "use strict";

  // ---------------------------------------------------------------- small utils
  function b64ToBytes(b64) {
    const bin = atob(b64.replace(/\s+/g, ""));
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ------------------------------------------------------------------- tuning
  // Renoise plays a sample at 2^((played - base_note)/12) * 2^(transpose/12) *
  // 2^(finetune/1200), so a sample that is FLAT of its note needs a POSITIVE finetune.
  function tuning(sampleRate, cycleLen) {
    const f0 = sampleRate / cycleLen;
    const exact = 57 + 12 * Math.log2(f0 / 440);
    const round = (x) => {
      const f = Math.floor(x), d = x - f;
      if (d > 0.5) return f + 1;
      if (d < 0.5) return f;
      return f % 2 === 0 ? f : f + 1;
    };
    let note = round(exact);                      // cents come off the unclamped note
    const cents = round((note - exact) * 100);
    let noteClamped = false, centsClamped = false;
    if (note < 0) { note = 0; noteClamped = true; }
    if (note > 119) { note = 119; noteClamped = true; }
    let finetune = cents;
    if (finetune > 127) { finetune = 127; centsClamped = true; }
    if (finetune < -128) { finetune = -128; centsClamped = true; }
    return { f0, exact, baseNote: note, finetune, noteClamped, centsClamped };
  }

  // --------------------------------------------------------------- wav reading
  function parseWav(bytes) {
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const tag = (o) => String.fromCharCode(dv.getUint8(o), dv.getUint8(o + 1),
      dv.getUint8(o + 2), dv.getUint8(o + 3));
    if (tag(0) !== "RIFF" || tag(8) !== "WAVE") throw new Error("not a RIFF/WAVE file");
    let offset = 12, fmt = null, data = null;
    while (offset + 8 <= bytes.length) {
      const id = tag(offset), size = dv.getUint32(offset + 4, true);
      const body = offset + 8;
      if (id === "fmt ") {
        fmt = {
          format: dv.getUint16(body, true),
          channels: dv.getUint16(body + 2, true),
          sampleRate: dv.getUint32(body + 4, true),
          bits: dv.getUint16(body + 14, true),
        };
      } else if (id === "data") {
        data = { start: body, size: Math.min(size, bytes.length - body) };
      }
      offset = body + size + (size % 2);
    }
    if (!fmt || !data) throw new Error("WAV is missing fmt or data");
    const bytesPerSample = fmt.bits / 8;
    const frames = Math.floor(data.size / (bytesPerSample * fmt.channels));
    const out = new Float64Array(frames);
    for (let i = 0; i < frames; i++) {
      const o = data.start + i * bytesPerSample * fmt.channels;
      let v;
      if (fmt.format === 3) {                       // IEEE float
        v = dv.getFloat32(o, true);
      } else if (fmt.bits === 16) {
        v = dv.getInt16(o, true) / 32768;
      } else if (fmt.bits === 24) {
        const b0 = dv.getUint8(o), b1 = dv.getUint8(o + 1), b2 = dv.getUint8(o + 2);
        let x = (b2 << 16) | (b1 << 8) | b0;
        if (x & 0x800000) x -= 0x1000000;
        v = x / 8388608;
      } else if (fmt.bits === 32) {
        v = dv.getInt32(o, true) / 2147483648;
      } else {
        throw new Error("unsupported WAV bit depth " + fmt.bits);
      }
      out[i] = v;
    }
    return { samples: out, sampleRate: fmt.sampleRate, channels: fmt.channels };
  }

  // ------------------------------------------------------- vital table reading
  function vitalTables(json) {
    const tables = json && json.settings ? (json.settings.wavetables || []) : [json];
    return tables.filter(Boolean);
  }

  function decodeVitalComponent(component, frameSize) {
    if (component.audio_file) {
      const raw = b64ToBytes(component.audio_file);
      const sizes = [];
      if (frameSize) sizes.push(frameSize);
      if (component.window_size) sizes.push(Math.round(component.window_size));
      sizes.push(2048, 4096, 1024, 512, 256);
      for (const ws of [...new Set(sizes)]) {
        for (const skip of [0, 1, 4]) {
          const int16 = Math.floor((raw.length - skip) / 2);
          if (int16 > 0 && int16 % ws === 0) {
            const frames = [];
            const dv = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
            for (let f = 0; f < int16 / ws; f++) {
              const frame = new Float64Array(ws);
              for (let i = 0; i < ws; i++) {
                frame[i] = dv.getInt16(skip + (f * ws + i) * 2, true) / 32768;
              }
              frames.push(frame);
            }
            return { frames, sampleRate: component.audio_sample_rate || 44100 };
          }
        }
      }
      throw new Error("audio_file size is not a multiple of any known frame size");
    }
    const frames = [];
    for (const kf of component.keyframes || []) {
      if (!kf.wave_data) continue;
      const raw = b64ToBytes(kf.wave_data);
      const dv = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
      const n = Math.floor(raw.length / 4);
      const frame = new Float64Array(n);
      for (let i = 0; i < n; i++) frame[i] = dv.getFloat32(i * 4, true);
      frames.push(frame);
    }
    if (!frames.length) throw new Error("component has no audio");
    return { frames, sampleRate: 44100 };
  }

  function readVital(bytes) {
    const json = JSON.parse(new TextDecoder().decode(bytes));
    for (const table of vitalTables(json)) {
      for (const group of table.groups || []) {
        for (const component of group.components || []) {
          if (component.type === "Wave Source" || component.type === "Audio File Source") {
            const got = decodeVitalComponent(component);
            return { frames: got.frames, sampleRate: got.sampleRate, kind: component.type };
          }
        }
      }
    }
    throw new Error("no decodable audio component in this Vital file");
  }

  // ------------------------------------------------------- cycle / frame maths
  // Ideal band-limited resample of one cycle to nOut samples (harmonics up to nOut/2).
  function bandlimitResample(cycle, nOut) {
    const n = cycle.length;
    const out = new Float64Array(nOut);
    const keep = Math.floor(nOut / 2);
    // keep both Fourier coefficients per harmonic; folding them into amplitude and phase
    // flips the sign of the sine part
    for (let k = 1; k <= keep; k++) {
      let a = 0, b = 0;
      for (let i = 0; i < n; i++) {
        const ang = (2 * Math.PI * k * i) / n;
        a += cycle[i] * Math.cos(ang);
        b += cycle[i] * Math.sin(ang);
      }
      a = (2 * a) / n;
      b = (2 * b) / n;
      for (let i = 0; i < nOut; i++) {
        const ang = (2 * Math.PI * k * i) / nOut;
        out[i] += a * Math.cos(ang) + b * Math.sin(ang);
      }
    }
    return out;
  }

  // the Python builder normalises every frame to peak 1.0 before embedding it
  function normalize(frame) {
    let peak = 0;
    for (let i = 0; i < frame.length; i++) peak = Math.max(peak, Math.abs(frame[i]));
    if (!(peak > 0)) return frame;
    const out = new Float64Array(frame.length);
    for (let i = 0; i < frame.length; i++) out[i] = frame[i] / peak;
    return out;
  }

  // gcd of the significant harmonics: 1 = the frame is one cycle, 8 = it repeats 8 times
  function detectCycles(frame) {
    const n = frame.length;
    const bins = Math.min(64, Math.floor(n / 2));
    const mags = [];
    for (let k = 1; k <= bins; k++) {
      let re = 0, im = 0;
      for (let i = 0; i < n; i++) {
        const a = (2 * Math.PI * k * i) / n;
        re += frame[i] * Math.cos(a);
        im -= frame[i] * Math.sin(a);
      }
      mags.push(Math.hypot(re, im));
    }
    const max = Math.max(...mags);
    if (!(max > 0)) return 1;
    const significant = mags.map((m, i) => (m > 0.02 * max ? i + 1 : 0)).filter(Boolean);
    const gcd = (a, b) => (b ? gcd(b, a % b) : a);
    let g = 0;
    for (const b of significant) { g = gcd(g, b); if (g === 1) return 1; }
    return Math.max(1, g);
  }

  function tableCycles(frames) {
    const counts = frames.map(detectCycles);
    const tally = new Map();
    for (const c of counts) tally.set(c, (tally.get(c) || 0) + 1);
    let best = 1, bestN = 0;
    for (const [c, n] of tally) if (n > bestN) { best = c; bestN = n; }
    return best > 1 && bestN >= Math.max(2, Math.floor(frames.length / 2)) ? best : 1;
  }

  function oneCycle(frame, cycles) {
    const g = cycles || detectCycles(frame);
    if (g <= 1) return frame;
    const n = Math.floor(frame.length / g);
    const out = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      let sum = 0;
      for (let k = 0; k < g; k++) sum += frame[k * n + i];
      out[i] = sum / g;
    }
    return out;
  }

  // choose which table frames to use
  function pickFrames(frames, want, mode) {
    const N = frames.length;
    if (want >= N) return frames.slice();
    if (mode === "spectral") {                       // farthest first on coarse spectra
      const spectra = frames.map((f) => {
        const bins = Math.min(64, Math.floor(f.length / 2));
        const mag = new Float64Array(bins);
        for (let k = 1; k <= bins; k++) {
          let re = 0, im = 0;
          for (let i = 0; i < f.length; i++) {
            const a = (2 * Math.PI * k * i) / f.length;
            re += f[i] * Math.cos(a); im -= f[i] * Math.sin(a);
          }
          mag[k - 1] = Math.hypot(re, im);
        }
        const sum = mag.reduce((a, b) => a + b, 0) || 1;
        return Array.from(mag, (v) => v / sum);
      });
      let loudest = 0, loudestPeak = -1;
      frames.forEach((f, i) => {
        const peak = Math.max(...Array.from(f, Math.abs));
        if (peak > loudestPeak) { loudestPeak = peak; loudest = i; }
      });
      const chosen = [loudest];
      const dist = new Array(N).fill(Infinity);
      while (chosen.length < want) {
        const last = spectra[chosen[chosen.length - 1]];
        for (let i = 0; i < N; i++) {
          if (chosen.includes(i)) continue;
          let d = 0;
          for (let k = 0; k < last.length; k++) d += Math.abs(last[k] - spectra[i][k]);
          dist[i] = Math.min(dist[i], d);
        }
        let pick = -1, best = -Infinity;
        for (let i = 0; i < N; i++) {
          if (chosen.includes(i)) continue;
          if (dist[i] > best) { best = dist[i]; pick = i; }
        }
        chosen.push(pick);
      }
      return chosen.sort((a, b) => a - b).map((i) => frames[i]);
    }
    const out = [];
    for (let i = 0; i < want; i++) {
      if (want === 1) { out.push(frames[0]); continue; }
      const p = (i * (N - 1)) / (want - 1);
      const lo = Math.floor(p), hi = Math.min(lo + 1, N - 1), t = p - lo;
      const blended = new Float64Array(frames[lo].length);
      for (let k = 0; k < blended.length; k++) {
        blended[k] = frames[lo][k] * (1 - t) + frames[hi][k] * t;
      }
      out.push(blended);
    }
    return out;
  }

  // ------------------------------------------------------------------ zip reading
  // Local file headers only; store and deflate (the latter via DecompressionStream, which
  // every current browser has). Used for dropping a zip of wavetables onto the page.
  async function listZip(bytes) {
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const out = [];
    let at = 0;
    while (at + 30 <= bytes.length && dv.getUint32(at, true) === 0x04034b50) {
      const method = dv.getUint16(at + 8, true);
      const size = dv.getUint32(at + 18, true);
      const nameLen = dv.getUint16(at + 26, true);
      const extraLen = dv.getUint16(at + 28, true);
      const name = new TextDecoder().decode(bytes.subarray(at + 30, at + 30 + nameLen));
      const start = at + 30 + nameLen + extraLen;
      const data = bytes.subarray(start, start + size);
      if (method === 0) {
        out.push({ name, data });
      } else if (typeof DecompressionStream !== "undefined") {
        const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
        out.push({ name, data: new Uint8Array(await new Response(stream).arrayBuffer()) });
      }
      at = start + size;
    }
    return out;
  }

  // ----------------------------------------------------------------- wav write
  function wav16(frame, sampleRate) {
    const n = frame.length;
    const buf = new ArrayBuffer(44 + n * 2);
    const dv = new DataView(buf);
    const put = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
    put(0, "RIFF"); dv.setUint32(4, 36 + n * 2, true); put(8, "WAVE");
    put(12, "fmt "); dv.setUint32(16, 16, true);
    dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
    dv.setUint32(24, sampleRate, true); dv.setUint32(28, sampleRate * 2, true);
    dv.setUint16(32, 2, true); dv.setUint16(34, 16, true);
    put(36, "data"); dv.setUint32(40, n * 2, true);
    for (let i = 0; i < n; i++) {
      let v = frame[i];
      if (v > 1) v = 1; else if (v < -1) v = -1;
      dv.setInt16(44 + i * 2, Math.round(v * 32767), true);
    }
    return new Uint8Array(buf);
  }

  // -------------------------------------------------------------------- zip
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c >>> 0;
    }
    return t;
  })();

  function crc32(bytes) {
    let crc = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) {
      crc = CRC_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
    }
    return (crc ^ 0xFFFFFFFF) >>> 0;
  }

  function textBytes(s) { return new TextEncoder().encode(s); }

  function zipStore(entries) {
    const chunks = [], central = [];
    let offset = 0;
    const u16 = (n) => [n & 255, (n >>> 8) & 255];
    const u32 = (n) => [n & 255, (n >>> 8) & 255, (n >>> 16) & 255, (n >>> 24) & 255];
    const dosDate = [0x21, 0x00];                    // 1980-01-01, little endian
    for (const e of entries) {
      const name = textBytes(e.name);
      const data = e.data;
      const crc = crc32(data);
      const head = new Uint8Array([
        ...textBytes("PK\x03\x04"),
        ...u16(20), ...u16(0x0800), ...u16(0), 0, 0, ...dosDate,
        ...u32(crc), ...u32(data.length), ...u32(data.length),
        ...u16(name.length), ...u16(0),      // name length, extra length
      ]);
      chunks.push(head, name, data);
      central.push(new Uint8Array([
        ...textBytes("PK\x01\x02"),
        ...u16(20), ...u16(20), ...u16(0x0800), ...u16(0), 0, 0, ...dosDate,
        ...u32(crc), ...u32(data.length), ...u32(data.length),
        ...u16(name.length), 0, 0, 0, 0,   // name, extra, comment
        ...u16(0), ...u16(0), ...u32(0),   // disk, internal attrs, external attrs
        ...u32(offset),
      ]), name);
      offset += head.length + name.length + data.length;
    }
    let centralSize = 0;
    for (const c of central) centralSize += c.length;
    const end = new Uint8Array([
      ...textBytes("PK\x05\x06"), ...u16(0), ...u16(0),
      ...u16(entries.length), ...u16(entries.length),
      ...u32(centralSize), ...u32(offset), ...u16(0),
    ]);
    const parts = [...chunks, ...central, end];
    let total = 0;
    for (const p of parts) total += p.length;
    const out = new Uint8Array(total);
    let at = 0;
    for (const p of parts) { out.set(p, at); at += p.length; }
    return out;
  }

  // --------------------------------------------------------------------- xml
  function param(name, value, viz) {
    return `        <${name}><Value>${value}</Value><Visualization>${viz || "Device only"}</Visualization></${name}>`;
  }

  function gateLfoXml(index, frameCount, spacing, destTrack) {
    const L = frameCount * spacing;
    const peak = (index - 1) * spacing;
    const points = [];
    for (let x = 0; x <= L; x++) {
      let d = (x - peak) % L;
      if (d > L / 2) d -= L;
      const v = Math.max(0, 1 - Math.abs(d) / spacing);
      points.push(`        <Point>${x},${v.toFixed(6)},0.0</Point>`);
    }
    return [
      `      <LfoDevice type="LfoDevice">`,
      `        <CustomDeviceName>gate ${String(index).padStart(2, "0")}</CustomDeviceName>`,
      `        <IsActive><Value>1.0</Value><Visualization>Device only</Visualization></IsActive>`,
      param("DestTrack", destTrack), param("DestEffect", "0"), param("DestParameter", "2"),
      param("Amplitude", "1"), param("Offset", "0"),
      param("Frequency", "9.99999997e-07"), param("Type", "4"),
      `        <CustomEnvelope>`,
      `          <PlayMode>Lines</PlayMode><Length>${L}</Length>`,
      `          <ValueQuantum>0.0</ValueQuantum><Polarity>Unipolar</Polarity>`,
      `          <Points>`, points.join("\n"), `          </Points>`,
      `        </CustomEnvelope>`,
      `        <CustomEnvelopeOneShot>false</CustomEnvelopeOneShot>`,
      `        <UseAdjustedEnvelopeLength>true</UseAdjustedEnvelopeLength>`,
      `      </LfoDevice>`,
    ].join("\n");
  }

  function mixerXml(name, volume) {
    return [
      `      <SampleMixerDevice type="SampleMixerDevice">`,
      `        <CustomDeviceName>${esc(name)}</CustomDeviceName>`,
      param("IsActive", "1.0"), param("Panning", "0.5"),
      param("Volume", volume, "Mixer and Device"),
      param("PostPanning", "0.5"), param("PostVolume", "1.0"),
      `      </SampleMixerDevice>`,
    ].join("\n");
  }

  function sendXml(dest) {
    return [
      `      <SendDevice type="SendDevice">`,
      param("IsActive", "1.0"), param("SendAmount", "1.0", "Mixer and Device"),
      param("SendPan", "0.5"), param("DestSendTrack", dest),
      `        <MuteSource>true</MuteSource>`,
      `        <SmoothParameterChanges>true</SmoothParameterChanges>`,
      `        <ApplyPostVolume>true</ApplyPostVolume>`,
      `      </SendDevice>`,
    ].join("\n");
  }

  // infrastructure only: LFO -> Hydra input, Hydra out 1 -> macro 1, LFO off, Key Tracker on
  // the LFO's reset. Every other destination is left for the user.
  function sweepRigXml() {
    const shape = [];
    for (let i = 0; i <= 15; i++) {
      const v = Math.abs(1 - 2 * (i / 15));
      shape.push(`        <Point>${i},${v.toFixed(4)},0.0</Point>`);
    }
    const lfo = [
      `      <LfoDevice type="LfoDevice">`,
      `        <CustomDeviceName>SWEEP</CustomDeviceName>`,
      param("IsActive", "0.0"),
      param("DestTrack", "-1"), param("DestEffect", "2"), param("DestParameter", "1.0"),
      param("Amplitude", "1.0"), param("Offset", "0.0"), param("Frequency", "16.0"),
      param("Type", "4"),
      `        <CustomEnvelope>`,
      `          <PlayMode>Lines</PlayMode><Length>16</Length>`,
      `          <ValueQuantum>0.0</ValueQuantum><Polarity>Unipolar</Polarity>`,
      `          <Points>`, shape.join("\n"), `          </Points>`,
      `        </CustomEnvelope>`,
      `        <CustomEnvelopeOneShot>false</CustomEnvelopeOneShot>`,
      `        <UseAdjustedEnvelopeLength>true</UseAdjustedEnvelopeLength>`,
      `      </LfoDevice>`,
    ].join("\n");

    const hydra = [`      <HydraDevice type="HydraDevice">`, `        <CustomDeviceName>HYDRA</CustomDeviceName>`,
      param("IsActive", "1.0"), `        <VisiblePages>1</VisiblePages>`,
      param("InputValue", "0.0", "Mixer and Device")];
    for (let i = 1; i <= 9; i++) {
      const eff = i === 1 ? "3" : "-1", par = i === 1 ? "1" : "-1";
      hydra.push(param(`Out${i}DestTrack`, "-1"), param(`Out${i}DestEffect`, eff),
        param(`Out${i}DestParameter`, par), param(`Out${i}Min`, "0.0"),
        param(`Out${i}Max`, "1.0"), `        <Out${i}Scaling>Linear</Out${i}Scaling>`);
    }
    hydra.push(`      </HydraDevice>`);

    const macros = [`      <InstrumentMacroDevice type="InstrumentMacroDevice">`,
      `        <CustomDeviceName>INSTR MACRO</CustomDeviceName>`, param("IsActive", "1.0")];
    for (let i = 0; i < 8; i++) macros.push(param(`ParameterValue${i}`, "0.5"));
    macros.push(param("PitchbendValue", "0.5"), param("ModulationValue", "0.0"),
      param("ChannelPressureValue", "0.0"), param("PhraseProgrammValue", "1.0"),
      `        <LinkedInstrument>-1</LinkedInstrument>`, `      </InstrumentMacroDevice>`);

    const kt = [`      <KeyTrackingDevice type="KeyTrackingDevice">`,
      `        <CustomDeviceName>KT -&gt; RESET</CustomDeviceName>`, param("IsActive", "1.0"),
      `        <SrcInstrument>-1</SrcInstrument>`, `        <DestScaling>Linear</DestScaling>`,
      `        <KeyTrackingMode>Clamp</KeyTrackingMode>`,
      `        <KeyTrackingMin>36</KeyTrackingMin>`, `        <KeyTrackingMax>72</KeyTrackingMax>`,
      param("DestTrack", "-1"), param("DestEffect", "1"), param("DestParameter", "8"),
      param("DestMin", "0.0"), param("DestMax", "1.0"), `      </KeyTrackingDevice>`];

    return [lfo, hydra.join("\n"), macros.join("\n"), kt.join("\n")].join("\n");
  }

  function instrumentXml(opts) {
    const n = opts.frameCount, len = opts.frameLength, t = opts.tuning;
    const sumIndex = n + 1;

    const samples = [];
    for (let i = 1; i <= n; i++) {
      samples.push([
        `<Sample>`,
        `<Name>${esc(opts.frameNames ? opts.frameNames[i - 1] : "frame " + i)}</Name>`,
        `<Finetune>${t.finetune}</Finetune>`,
        `<Oversample>true</Oversample><InterpolationMode>Cubic</InterpolationMode>`,
        `<LoopMode>Forward</LoopMode><LoopRelease>false</LoopRelease>`,
        `<LoopStart>0</LoopStart><LoopEnd>${len}</LoopEnd>`,
        `<SingleSliceTriggerEnabled>true</SingleSliceTriggerEnabled>`,
        `<IsAlias>false</IsAlias><MuteGroupIndex>-1</MuteGroupIndex>`,
        `<ModulationSetIndex>0</ModulationSetIndex>`,
        `<DeviceChainIndex>${i}</DeviceChainIndex>`,
        `<Mapping><Layer>Note-On Layer</Layer><BaseNote>${t.baseNote}</BaseNote>`,
        `<NoteStart>0</NoteStart><NoteEnd>119</NoteEnd><MapKeyToPitch>true</MapKeyToPitch>`,
        `<VelocityStart>0</VelocityStart><VelocityEnd>127</VelocityEnd>`,
        `<MapVelocityToVolume>true</MapVelocityToVolume></Mapping>`,
        `<DisplayStart>0</DisplayStart><DisplayLength>${len}</DisplayLength>`,
        `<SelectionRangeStart>-1</SelectionRangeStart><SelectionRangeEnd>-1</SelectionRangeEnd>`,
        `<SelectedChannel>L+R</SelectedChannel><VZoomFactor>1.0</VZoomFactor>`,
        `</Sample>`,
      ].join(""));
    }

    const gateDevs = [mixerXml("GATES", "1.0")];
    for (let i = 1; i <= n; i++) gateDevs.push(gateLfoXml(i, n, opts.spacing || 2, i));
    const chains = [{ name: "GATES", devices: gateDevs.join("\n") }];
    for (let i = 1; i <= n; i++) {
      chains.push({ name: `FRAME ${String(i).padStart(2, "0")}`,
        devices: mixerXml("Mixer", "0.0") + "\n" + sendXml(sumIndex) });
    }
    let sumDevs = mixerXml("Mixer", "1.0");
    if (opts.withSweep) sumDevs += "\n" + sweepRigXml();
    chains.push({ name: "SUM", devices: sumDevs });

    const chainXml = chains.map((c) => [
      `<DeviceChain>`, `<Devices>`, c.devices, `</Devices>`,
      `<Name>${esc(c.name)}</Name><RoutingIndex>-1</RoutingIndex>`, `</DeviceChain>`,
    ].join("")).join("");

    const mappings = [];
    for (let i = 1; i <= n; i++) {
      mappings.push(`<Mapping><DestChainType>SampleDSP</DestChainType><DestChainIndex>0</DestChainIndex><DestDeviceIndex>${i}</DestDeviceIndex><DestParameterIndex>8</DestParameterIndex><Min>0.0</Min><Max>1.0</Max><Scaling>Linear</Scaling></Mapping>`);
    }

    return `<?xml version="1.0" encoding="UTF-8"?>` +
      `<RenoiseInstrument doc_version="34">` +
      `<SelectedPresetName>Init</SelectedPresetName>` +
      `<SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>` +
      `<SelectedPresetIsModified>true</SelectedPresetIsModified>` +
      `<Name>${esc(opts.name)}</Name>` +
      `<CopyIntoNewSampleNameCounter>0</CopyIntoNewSampleNameCounter>` +
      `<CopyIntoNewInstrumentNameCounter>0</CopyIntoNewInstrumentNameCounter>` +
      `<GlobalProperties>` +
      `<Macro0><Value>0.0</Value><Visualization>Device only</Visualization><Name>WT Position</Name>` +
      `<Mappings>${mappings.join("")}</Mappings></Macro0>` +
      `<Macro1><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 2</Name></Macro1>` +
      `<Macro2><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 3</Name></Macro2>` +
      `<Macro3><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 4</Name></Macro3>` +
      `<Macro4><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 5</Name></Macro4>` +
      `<Macro5><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 6</Name></Macro5>` +
      `<Macro6><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 7</Name></Macro6>` +
      `<Macro7><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 8</Name></Macro7>` +
      `<PitchbendMacro><Value>50</Value><Visualization>Device only</Visualization><Name>Pitchbend</Name></PitchbendMacro>` +
      `<ModulationWheelMacro><Value>0.0</Value><Visualization>Device only</Visualization><Name>Modulation</Name></ModulationWheelMacro>` +
      `<ChannelPressureMacro><Value>0.0</Value><Visualization>Device only</Visualization><Name>Channel Pressure</Name></ChannelPressureMacro>` +
      `<MacrosVisible>true</MacrosVisible><Volume>1.0</Volume><Transpose>0</Transpose>` +
      `<MtsEspTuning>false</MtsEspTuning><Scale>None</Scale><ScaleKey>C</ScaleKey>` +
      `<Quantize>None</Quantize><Monophonic>false</Monophonic><MonophonicGlide>0</MonophonicGlide>` +
      `<ShowCommentsAfterLoading>false</ShowCommentsAfterLoading><BeatsPerMin>140</BeatsPerMin>` +
      `</GlobalProperties>` +
      `<MidiInputProperties><Channel>-1</Channel><NoteRangeStart>0</NoteRangeStart>` +
      `<NoteRangeEnd>119</NoteRangeEnd><AssignedTrack>-1</AssignedTrack></MidiInputProperties>` +
      `<PhraseGenerator><PlaybackSync>false</PlaybackSync><PlaybackMode>Selective</PlaybackMode>` +
      `<SelectedPhraseIndex>-1</SelectedPhraseIndex><PhraseMap><SelectedMappingIndex>-1</SelectedMappingIndex></PhraseMap></PhraseGenerator>` +
      `<SampleGenerator><Samples>${samples.join("")}</Samples><SelectedSampleIndex>0</SelectedSampleIndex>` +
      `<ModulationSets><ModulationSet><SelectedPresetName>Init</SelectedPresetName>` +
      `<SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary><SelectedPresetIsModified>false</SelectedPresetIsModified>` +
      `<Devices><SampleMixerModulationDevice type="SampleMixerModulationDevice">` +
      param("IsActive", "1.0") + param("Volume", "1.0") + param("Panning", "0.0") +
      param("Pitch", "0.0") + `<PitchModulationRange>12</PitchModulationRange>` +
      param("Cutoff", "63.5") + param("Resonance", "63.5") + param("Drive", "0.0") +
      `</SampleMixerModulationDevice></Devices><Name>Set 01</Name><FilterType>0</FilterType>` +
      `<FilterBankVersion>3</FilterBankVersion></ModulationSet></ModulationSets>` +
      `<SelectedModulationSetIndex>0</SelectedModulationSetIndex>` +
      `<DeviceChains>${chainXml}</DeviceChains><SelectedDeviceChainIndex>0</SelectedDeviceChainIndex>` +
      `<KeyzoneOverlappingMode>Play All</KeyzoneOverlappingMode>` +
      `<SplitMap><SelectedPresetName>Init</SelectedPresetName><SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>` +
      `<SelectedPresetIsModified>false</SelectedPresetIsModified></SplitMap></SampleGenerator>` +
      `<PluginGenerator><Channel>0</Channel><Transpose>0</Transpose><Volume>1.0</Volume><OutputRoutings/>` +
      `<MidiOutputRoutingIndex>-1</MidiOutputRoutingIndex><AutoSuspend>true</AutoSuspend>` +
      `<AliasInstrumentIndex>-1</AliasInstrumentIndex><AliasFxIndices>-1,-1</AliasFxIndices></PluginGenerator>` +
      `<MidiGenerator><Channel>0</Channel><InstrumentType>LineIn Ret</InstrumentType><Delay>0</Delay>` +
      `<Program>-1</Program><Bank>-1</Bank><BankOrder>MSB, LSB</BankOrder><Transpose>0</Transpose>` +
      `<Length>8000</Length></MidiGenerator><ActiveGeneratorTab>Samples</ActiveGeneratorTab>` +
      `</RenoiseInstrument>`;
  }

  // ------------------------------------------------------------------ the build
  // opts: { bytes, filename, name, frames, select, cycleLen, withSweep, spacing }
  function buildFromWavetable(opts) {
    const isVital = /\.(vitaltable|vital)$/i.test(opts.filename);
    const source = isVital ? readVital(opts.bytes) : (() => {
      const wav = parseWav(opts.bytes);
      const sizes = [2048, 4096, 1024, 512, 256];
      const size = sizes.find((s) => wav.samples.length % s === 0 && wav.samples.length / s >= 2);
      if (!size) throw new Error("file length is not an even number of known frame sizes");
      const count = wav.samples.length / size;
      const frames = [];
      for (let f = 0; f < count; f++) frames.push(wav.samples.slice(f * size, (f + 1) * size));
      return { frames, sampleRate: wav.sampleRate, kind: "wavetable wav", channels: wav.channels };
    })();

    const cycles = tableCycles(source.frames);
    const prepared = source.frames.map((f) => oneCycle(f, cycles));
    const want = Math.min(opts.frames || 12, 12, prepared.length);
    const picked = pickFrames(prepared, want, opts.select || "even");
    const cycleLen = opts.cycleLen || 169;
    const resampled = picked.map((f) => normalize(bandlimitResample(f, cycleLen)));
    const t = tuning(source.sampleRate, cycleLen);

    const names = resampled.map((_, i) => `frame ${String(i + 1).padStart(2, "0")}`);
    const xml = instrumentXml({
      name: opts.name || (opts.filename || "wavetable").replace(/\.[^.]+$/, "") + " WT",
      frameCount: resampled.length, frameLength: cycleLen,
      sampleRate: source.sampleRate, tuning: t,
      withSweep: !!opts.withSweep, spacing: opts.spacing || 2, frameNames: names,
    });

    const entries = [{ name: "Instrument.xml", data: textBytes(xml) }];
    resampled.forEach((frame, i) => {
      entries.push({
        name: `SampleData/Sample${String(i).padStart(2, "0")} (frame ${String(i + 1).padStart(2, "0")}).wav`,
        data: wav16(frame, source.sampleRate),
      });
    });

    return {
      xrni: zipStore(entries), xml,
      previewCycle: Array.from(resampled[0]),
      report: {
        source: opts.filename, kind: source.kind,
        tableFrames: source.frames.length, cycles,
        frames: resampled.length, cycleLen,
        tuning: t, sampleRate: source.sampleRate,
      },
    };
  }

  const api = {
    buildFromWavetable, tuning, parseWav, readVital, detectCycles, oneCycle, normalize,
    pickFrames, bandlimitResample, instrumentXml, zipStore, wav16, crc32, esc, listZip,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  global.WTBuilder = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
