/*
  wt-hash.js — the browser half of the duplicate check.

  Mirrors tools/wt_hash.py in the instruments repository. That file is the reference: it builds
  hashes/index.json, and tests/browser_check.py compares the two implementations on a real
  instrument, because a drift between them would quietly stop catching duplicates.

  Two hashes per frame:

    exact   FNV-1a over the samples quantised to 11 bit, and their count. Two files with
            the same audio match even when one is flac and the other wav.
    shape   the cycle sampled at POINTS evenly spaced points, peak normalised, quantised to 8
            bit. Survives a different cycle length and a different rendering of the same shape,
            which is what catches the same table built with other settings.

  Shape keys are compared with a tolerance rather than for equality, since two renderings of one
  cycle land a fraction of a step apart.
*/
(function (global) {
  "use strict";

  const POINTS = 24;
  const FNV_OFFSET = 0x811c9dc5;
  const FNV_PRIME = 0x01000193;

  // index.json is fetched lazily: only the duplicate check needs it.
  // raw first: it is never stale, which matters because the index is rewritten whenever a
  // donation is filed. jsDelivr is the fallback and serves it gzipped.
  const INDEX_BASES = [
    "https://raw.githubusercontent.com/mene311/renoise-wavetable-instruments/master/hashes/",
    "https://cdn.jsdelivr.net/gh/mene311/renoise-wavetable-instruments@master/hashes/",
  ];
  let indexPromise = null;

  function shapeKey(samples) {
    const n = samples.length;
    const out = new Uint8Array(POINTS);
    if (!n) return out;
    let peak = 0;
    for (let i = 0; i < n; i++) {
      const a = Math.abs(samples[i]);
      if (a > peak) peak = a;
    }
    if (peak === 0) peak = 1;
    for (let k = 0; k < POINTS; k++) {
      const pos = (k * (n - 1)) / (POINTS - 1);
      const i0 = Math.floor(pos);
      const frac = pos - i0;
      const i1 = i0 + 1 < n ? i0 + 1 : n - 1;
      const v = (samples[i0] + (samples[i1] - samples[i0]) * frac) / peak;
      let q = Math.round(v * 127);            // half up, matching python's floor(x + 0.5)
      if (q < -127) q = -127;
      if (q > 127) q = 127;
      out[k] = q & 0xff;
    }
    return out;
  }

  function fnv(parts) {
    let h = FNV_OFFSET;
    for (const part of parts) {
      for (let i = 0; i < part.length; i++) {
        h = Math.imul(h ^ part[i], FNV_PRIME) >>> 0;
      }
    }
    return h.toString(16).padStart(8, "0");
  }

  function exactKey(frames) {
    const parts = [];
    for (const frame of frames) {
      const n = frame.length;
      parts.push(new Uint8Array([n & 255, (n >> 8) & 255, (n >> 16) & 255, (n >> 24) & 255]));
      const q = new Int16Array(n);
      for (let i = 0; i < n; i++) {
        // 11 bit, not 16: two decoders disagree in the last bits of a float sample and at 16 bit
        // that lands either side of a rounding boundary, so the same file hashed two ways.
        let v = Math.round(frame[i] * 2047);
        if (v < -2047) v = -2047;
        if (v > 2047) v = 2047;
        q[i] = v;
      }
      parts.push(new Uint8Array(q.buffer));
    }
    return fnv(parts);
  }

  // Chromium decodes to the audio device rate unless told otherwise, which resamples the cycle
  // (169 samples at 44.1 kHz came back as 183 at 48 kHz) and would make every hash disagree with
  // the ones the repository computed. Read the file's own rate and decode there.
  function fileSampleRate(bytes) {
    if (bytes[0] === 0x66 && bytes[1] === 0x4c && bytes[2] === 0x61 && bytes[3] === 0x43) {
      const rate = (bytes[18] << 12) | (bytes[19] << 4) | (bytes[20] >> 4);   // flac streaminfo
      return rate > 0 ? rate : 0;
    }
    if (bytes[0] === 0x52 && bytes[1] === 0x49) {                              // riff fmt chunk
      return (bytes[24] | (bytes[25] << 8) | (bytes[26] << 16) | (bytes[27] << 24)) >>> 0;
    }
    return 0;
  }

  async function decodeSample(bytes) {
    const format = bytes[0] === 0x52 && bytes[1] === 0x49 ? "wav" : "flac";
    const rate = fileSampleRate(bytes);
    const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    const ctx = rate ? new OfflineAudioContext(1, 1, rate) : new OfflineAudioContext(1, 1, 44100);
    const decoded = await ctx.decodeAudioData(buffer);
    const samples = new Float32Array(decoded.length);
    if (decoded.copyFromChannel) decoded.copyFromChannel(samples, 0);
    else samples.set(decoded.getChannelData(0));
    return { samples, format, rate: decoded.sampleRate };
  }

  function b64ToBytes(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function shapesOf(entry, points) {
    const raw = b64ToBytes(entry.shapes);
    const out = [];
    for (let i = 0; i + points <= raw.length; i += points) out.push(raw.subarray(i, i + points));
    return out;
  }

  function distance(a, b) {
    if (a.length !== b.length) return 999;
    let sum = 0;
    for (let i = 0; i < a.length; i++) {
      const d = (a[i] << 24 >> 24) - (b[i] << 24 >> 24);   // as signed bytes
      sum += Math.abs(d);
    }
    return sum / a.length;
  }

  // What the caller hands in: an array of frames, each an array or typed array of samples.
  function descriptor(frames) {
    const keys = frames.map((f) => shapeKey(f));
    return { keys, key: exactKey(frames), frames: frames.length,
             cycle: frames.length ? frames[0].length : 0 };
  }

  async function loadIndex(onProgress) {
    if (!indexPromise) {
      indexPromise = (async () => {
        let lastError;
        for (const base of INDEX_BASES) {
          try {
            // raw caches for minutes and jsDelivr for much longer, so ask once a day under a
            // name the cache has not seen. The index changes when a donation lands.
            const bust = base.indexOf("raw.githubusercontent") >= 0
              ? "?v=" + new Date().toISOString().slice(0, 10) : "";
            const r = await fetch(base + "index.json" + bust);
            if (!r.ok) throw new Error("HTTP " + r.status);
            const doc = await r.json();
            onProgress && onProgress(doc.count);
            return doc;
          } catch (e) {
            lastError = e;
          }
        }
        indexPromise = null;
        throw new Error("could not load the library index (" + lastError.message + ")");
      })();
    }
    return indexPromise;
  }

  // overlap = share of this instrument's frames that have a close counterpart in that library
  // instrument, so a table built with fewer frames still reads as a duplicate.
  function compare(index, desc, tolerance) {
    const tol = tolerance === undefined ? 3 : tolerance;
    let best = null;
    for (const entry of index.instruments) {
      if (entry.key === desc.key) {
        return { verdict: "identical", overlap: 1, of: entry.name, category: entry.category,
                 frames: entry.frames, matched: entry.frames };
      }
      const theirs = shapesOf(entry, index.points || POINTS);
      if (!theirs.length || !desc.keys.length) continue;
      let matched = 0;
      for (const mine of desc.keys) {
        for (const other of theirs) {
          if (distance(mine, other) <= tol) { matched++; break; }
        }
      }
      const overlap = matched / desc.keys.length;
      if (!best || overlap > best.overlap) {
        best = { overlap, of: entry.name, category: entry.category,
                 frames: entry.frames, matched };
      }
    }
    if (!best) return { verdict: "new", overlap: 0, mine: desc.keys.length };
    best.mine = desc.keys.length;
    best.verdict = best.overlap >= 0.8 ? "variant" : "new";
    return best;
  }

  function describe(result) {
    if (result.verdict === "identical")
      return "already in the library as " + result.of;
    if (result.verdict === "variant")
      return "close to " + result.of + " (" + result.matched + " of " + result.mine +
        " frames match)";
    return "not in the library";
  }

  global.WTHash = { POINTS, shapeKey, exactKey, descriptor, loadIndex, compare, describe,
                    decodeSample, fileSampleRate };
})(typeof globalThis !== "undefined" ? globalThis : this);
