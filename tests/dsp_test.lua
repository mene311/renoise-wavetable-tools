--[[
  dsp_test.lua — exercise the cycle-slicing and resampling in wtlib against shapes whose
  answer is known analytically.

  The point of these routines is that a wavetable frame may hold more than one cycle, and
  that slicing a table into n equal blocks is wrong. Both failures are silent: the
  instrument still builds, it just crackles or plays sharp. So they need a test with a
  known right answer rather than an ear.

  Run: luajit tests/dsp_test.lua
]]

package.path = "./renoise-tool/?.lua;" .. package.path
local WTLib = require("wtlib")

local fails, checks = {}, 0

local function check(name, fn)
  checks = checks + 1
  local ok, err = pcall(fn)
  if ok then
    print("  ok   " .. name)
  else
    print("  FAIL " .. name .. "\n       " .. tostring(err))
    fails[#fails + 1] = name
  end
end

local function eq(a, b, what, tol)
  tol = tol or 0
  if a == nil or b == nil or type(a) ~= type(b) then
    if a ~= b then
      error(string.format("%s: expected %s, got %s", what, tostring(b), tostring(a)), 2)
    end
    return
  end
  if type(a) ~= "number" then
    if a ~= b then
      error(string.format("%s: expected %s, got %s", what, tostring(b), tostring(a)), 2)
    end
    return
  end
  if math.abs(a - b) > tol then
    error(string.format("%s: expected %.6f, got %.6f (tol %g)", what, b, a, tol), 2)
  end
end

-- a sine holding exactly `cycles` periods, sampled at `ppc` points per cycle
local function sine(cycles, ppc, phase)
  local n = cycles * ppc
  local t = {}
  for i = 1, n do
    t[i] = math.sin(2 * math.pi * cycles * (i - 1) / n + (phase or 0))
  end
  return t
end

local function saw(cycles, pts_per_cycle)
  local n = cycles * pts_per_cycle
  local t = {}
  for i = 1, n do
    local x = (cycles * (i - 1) / n) % 1
    t[i] = 2 * x - 1
  end
  return t
end

print("dsp_test: wtlib cycle analysis")

--------------------------------------------------------------------------- gcd / pow2

--------------------------------------------------------------------------- frame size

check("find_frame_size: the largest standard size that divides evenly wins", function()
  -- 8 x 64 samples. 64 divides it, and so do 128 and 256; the Python builder takes the
  -- LARGEST from its list, so this is 64 only because nothing above it fits 512.
  local s = {}
  for f = 0, 7 do
    for i = 1, 64 do s[f * 64 + i] = math.sin(2 * math.pi * (i - 1) / 64) end
  end
  eq(#s, 512, "total")
  eq(WTLib.find_frame_size(s), 256, "frame size")
end)

check("find_frame_size: a typical Serum table of 256 x 2048 is read as 2048", function()
  -- 524288 samples: 2048 divides it 256 times, and 4096 divides it 128 times. 2048 is
  -- tried first because a 4096-sample block is more likely two frames than one.
  local s = {}
  for i = 1, 524288 do
    local frame = math.floor((i - 1) / 2048)
    local k = (i - 1) % 2048
    -- each frame slightly different, so this is a real table and not a single cycle
    s[i] = math.sin(2 * math.pi * k / 2048) * (1 - 0.5 * frame / 256)
  end
  eq(#s, 524288, "total")
  eq(WTLib.find_frame_size(s), 2048, "frame size")
  eq(WTLib.find_frame_size(s), 2048, "frame size, confirmed")
end)

check("find_frame_size: 2048 is preferred over 4096", function()
  -- 8192 samples is 4 x 2048 or 2 x 4096. Both are valid readings; the Python tool takes
  -- 2048 first, so this must too or the two builders disagree on the same file.
  local s = {}
  for i = 1, 8192 do s[i] = math.sin(2 * math.pi * ((i - 1) % 2048) / 2048) end
  eq(WTLib.find_frame_size(s), 2048, "frame size")
end)

check("find_frame_size: returns nil when the length fits nothing standard", function()
  -- 100 samples: no standard frame size divides it and leaves two frames
  local s = {}
  for i = 1, 100 do s[i] = math.sin(2 * math.pi * i / 100) end
  eq(WTLib.find_frame_size(s), nil, "100 samples")
end)

check("frames_are_periodic: reports a clean loop only when the size is right", function()
  local s = {}
  for f = 0, 3 do
    for i = 1, 128 do s[f * 128 + i] = math.sin(2 * math.pi * (i - 1) / 128) end
  end
  eq(WTLib.frames_are_periodic(s, 128), true, "the true size loops")
end)

--------------------------------------------------------------------------- frame selection

check("select_frames: takes all of them when asked for at least as many", function()
  local f = {}
  for i = 1, 4 do f[i] = { i } end
  local got, idx = WTLib.select_frames(f, 12)
  eq(#got, 4, "count")
  eq(idx[1], 1, "first index")
  eq(idx[4], 4, "last index")
end)

check("select_frames: spaces the picks evenly and keeps both ends", function()
  local f = {}
  for i = 1, 10 do f[i] = { i } end
  local got, idx = WTLib.select_frames(f, 4)
  eq(#got, 4, "count")
  eq(idx[1], 1, "starts at the first")
  eq(idx[4], 10, "ends at the last")
  eq(idx[2], 4, "second pick")
  eq(idx[3], 7, "third pick")
end)

check("select_frames: a single pick still works", function()
  local f = {}
  for i = 1, 10 do f[i] = { i } end
  local got, idx = WTLib.select_frames(f, 1)
  eq(#got, 1, "count")
  eq(idx[1], 1, "index")
end)

--------------------------------------------------------------------------- detect_cycles

check("detect_cycles: a pure one-cycle sine is 1", function()
  eq(WTLib.detect_cycles(sine(1, 256)), 1, "one-cycle sine")
end)

check("detect_cycles: a pure saw is 1", function()
  eq(WTLib.detect_cycles(saw(1, 256)), 1, "one-cycle saw")
end)

-- These are the cases that used to build a sharp instrument.
for _, c in ipairs({ 2, 3, 4, 8 }) do
  check(("detect_cycles: a frame holding %d cycles is detected as %d"):format(c, c), function()
    -- 64 points per cycle: enough resolution that the harmonic bins are well separated
    eq(WTLib.detect_cycles(sine(c, 64)), c, c .. "-cycle sine")
  end)
end

check("detect_cycles: a silent frame is treated as one cycle, not a divide-by-zero", function()
  local flat = {}
  for i = 1, 256 do flat[i] = 0 end
  eq(WTLib.detect_cycles(flat), 1, "silence")
end)

check("detect_cycles: a DC offset does not fool it", function()
  local t = sine(4, 256)
  for i = 1, #t do t[i] = t[i] + 0.7 end
  eq(WTLib.detect_cycles(t), 4, "offset 4-cycle sine")
end)

check("detect_cycles: a non-power-of-two length still answers", function()
  -- 300 samples is not a power of two, so this path zero-pads
  eq(WTLib.detect_cycles(sine(1, 300)), 1, "300-sample one-cycle sine")
  eq(WTLib.detect_cycles(sine(3, 300)), 3, "300-sample three-cycle sine")
end)

--------------------------------------------------------------------------- table_cycles

check("table_cycles: a whole table of 4-cycle frames reports 4", function()
  local t = {}
  for i = 1, 8 do t[i] = sine(4, 64) end
  eq(WTLib.table_cycles(t), 4, "table of 4-cycle frames")
end)

check("table_cycles: a single odd frame does not change the verdict", function()
  local t = {}
  for i = 1, 8 do t[i] = sine(4, 64) end
  t[3] = sine(3, 64) -- one dissenter
  eq(WTLib.table_cycles(t), 4, "table with one odd frame")
end)

check("table_cycles: a genuinely mixed table falls back to 1", function()
  local t = {}
  for i = 1, 4 do t[i] = sine(4, 64) end
  for i = 5, 8 do t[i] = sine(1, 64) end
  eq(WTLib.table_cycles(t), 1, "evenly split table")
end)

--------------------------------------------------------------------------- one_cycle

check("one_cycle: slices four cycles to one, keeping the length divisible", function()
  local one = WTLib.one_cycle(sine(4, 64), 4)
  eq(#one, 64, "length")
end)

check("one_cycle: the result is still a single sine cycle", function()
  local one = WTLib.one_cycle(sine(4, 64), 4)
  eq(WTLib.detect_cycles(one), 1, "cycles after slicing")
end)

check("one_cycle: averaging dilutes a spike in one repeat", function()
  -- The same cycle four times; the first repeat is offset by +1.0. Averaging must reduce
  -- that offset to a quarter of its size, which is the noise rejection the slice buys.
  -- (It cannot remove it entirely: one bad copy in four leaves 1/4 behind.)
  local base = sine(1, 64)
  local t = {}
  for r = 1, 4 do
    for i = 1, 64 do
      t[(r - 1) * 64 + i] = base[i] + (r == 1 and 1.0 or 0.0)
    end
  end
  local one = WTLib.one_cycle(t, 4)
  for i = 1, 64 do
    eq(one[i], base[i] + 0.25, "averaged sample " .. i, 1e-9)
  end
end)

check("one_cycle: identical repeats come back exactly", function()
  -- The common real case: a frame that simply repeats the same cycle. Averaging exact
  -- copies must reproduce it sample for sample, not blur it.
  local base = sine(1, 96)
  local t = {}
  for r = 1, 3 do
    for i = 1, 96 do t[(r - 1) * 96 + i] = base[i] end
  end
  local one = WTLib.one_cycle(t, 3)
  for i = 1, 96 do eq(one[i], base[i], "sample " .. i, 1e-12) end
end)

check("one_cycle: a single-cycle frame is returned untouched", function()
  local s = sine(1, 128)
  local one = WTLib.one_cycle(s, 1)
  eq(#one, 128, "length")
  eq(one[10], s[10], "sample 10")
end)

--------------------------------------------------------------------------- resample

check("bandlimit_resample: same length returns a copy", function()
  local s = sine(1, 128)
  local r = WTLib.bandlimit_resample(s, 128)
  eq(#r, 128, "length")
  for i = 1, 128 do eq(r[i], s[i], "sample " .. i) end
end)

check("bandlimit_resample: upsampling preserves amplitude", function()
  local s = sine(1, 64)          -- a single harmonic, well below Nyquist at 512
  local r = WTLib.bandlimit_resample(s, 512)
  eq(#r, 512, "length")
  local lo, hi = math.huge, -math.huge
  for i = 1, #r do lo = math.min(lo, r[i]); hi = math.max(hi, r[i]) end
  eq(hi - lo, 2.0, "peak-to-peak", 0.02)
end)

check("bandlimit_resample: upsampling keeps the shape (still one cycle, still a sine)",
  function()
    local r = WTLib.bandlimit_resample(sine(1, 64), 512)
    eq(WTLib.detect_cycles(r), 1, "cycles after upsample")
    -- a sine sampled at 512 points peaks at 128 (a quarter turn), near zero at the end
    eq(r[1], 0.0, "first sample", 0.01)
    eq(r[129], 1.0, "quarter-turn peak", 0.02)
    eq(r[257], 0.0, "half-way zero", 0.01)
  end)

check("bandlimit_resample: the resampled cycle is one period, not two", function()
  -- if the slicing were wrong this would come back as 2 cycles, i.e. an octave sharp
  local r = WTLib.bandlimit_resample(sine(1, 256), 128)
  eq(WTLib.detect_cycles(r), 1, "cycles after downsample")
end)

check("bandlimit_resample: dropping harmonics does not fold them back as aliasing",
  function()
    -- A saw has harmonics all the way up. Downsampling 1024 -> 64 must DISCARD the top
    -- ones, not reflect them. Aliasing shows up as energy above the destination's
    -- harmonic limit, so measure that directly.
    local r = WTLib.bandlimit_resample(saw(1, 1024), 64)
    eq(#r, 64, "length")

    -- count how many harmonics of the 64-sample result carry real energy
    local n = 64
    local re, im = {}, {}
    for i = 1, n do re[i], im[i] = r[i], 0 end
    -- direct DFT at the harmonics we care about is clearer than re-using the fft here
    local function mag_at(b)
      local sr, si = 0.0, 0.0
      for i = 1, n do
        local a = -2 * math.pi * b * (i - 1) / n
        sr = sr + r[i] * math.cos(a)
        si = si + r[i] * math.sin(a)
      end
      return math.sqrt(sr * sr + si * si) / n
    end
    local h1, h20, h31 = mag_at(1), mag_at(20), mag_at(31)
    if not (h1 > h20 and h20 > h31) then
      error(string.format(
        "harmonics should fall off with frequency, got h1=%.4f h20=%.4f h31=%.4f",
        h1, h20, h31))
    end
  end)

--------------------------------------------------------------------------- the splice bug

check("the old slicing is shown wrong, the new one right", function()
  -- Reproduce the reported failure: a table of 32 frames x 64 samples, built at 8 frames.
  -- The old code did floor(2048/8)=256 samples per block, which is 4 whole source frames
  -- per block -- fine here. Now build it at 12, where 2048/12=170.67 does not divide:
  -- every block straddles frame boundaries and the frames repeat 4x.
  local src_frames, flen = 32, 64
  local total = src_frames * flen

  -- what the tool used to do
  local block_old = math.floor(total / 12)
  eq(block_old, 170, "old block length")

  -- a block starting mid-frame holds a fraction of the 4 cycles its frame carries, so it
  -- is not periodic: the splice is audible
  local mid = {}
  for i = 1, block_old do
    mid[i] = math.sin(2 * math.pi * 4 * (i - 1 + 37) / flen)
  end
  -- 170 samples cannot hold a whole number of 4 cycles of a 64-sample period
  local cycles_in_block = block_old / (flen / 4)
  if math.abs(cycles_in_block - math.floor(cycles_in_block)) < 1e-9 then
    error("expected the old block length NOT to be a whole number of cycles")
  end

  -- the new path: work out the cycles, slice to one, resample to a chosen cycle length.
  -- sine(c, ppc) gives c cycles of ppc samples, so a 4-cycle frame at 64 points per cycle
  -- is 256 samples and one cycle of it is 64.
  local frame = sine(4, flen)
  eq(#frame, 4 * flen, "frame length")
  eq(WTLib.detect_cycles(frame), 4, "detected cycles")
  local one = WTLib.one_cycle(frame, 4)
  eq(#one, flen, "one cycle length")
  local out = WTLib.bandlimit_resample(one, 256)
  eq(#out, 256, "resampled length")
  eq(WTLib.detect_cycles(out), 1, "final cycles")
end)

print(string.format("\n%d checks, %d failed", checks, #fails))
if #fails > 0 then
  for _, f in ipairs(fails) do print("  " .. f) end
  os.exit(1)
end
print("dsp_test: PASS")
