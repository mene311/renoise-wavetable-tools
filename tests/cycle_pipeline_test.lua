-- End-to-end: simulate read_frames' pipeline on a table the OLD code mangled,
-- and confirm the new one produces single-cycle frames of equal length.
package.path = (arg and arg[0] and arg[0]:match("^(.*)/[^/]*$") or ".") .. "/../renoise-tool/?.lua;" .. package.path
local W = require("wtlib")

-- A 256-frame Serum-style table, 2048 samples per frame, each frame = 4 cycles.
-- (This is exactly the "many frames + multi-cycle" case that sounded sharp.)
local FRAMES, FLEN, CYC = 256, 2048, 4
local samples = {}
for f = 0, FRAMES-1 do
  for i = 1, FLEN do
    local k = (i-1) % (FLEN/CYC)          -- position within one cycle
    local harmonic = 1 + (f % 7)          -- each frame slightly richer
    local v = math.sin(2*math.pi*k/(FLEN/CYC))
    v = v + 0.3*math.sin(2*math.pi*harmonic*k/(FLEN/CYC))
    samples[f*FLEN + i] = v * (1 - 0.3*f/FRAMES)
  end
end
print(string.format("source: %d frames x %d samples, %d cycles per frame (total %d)",
  FRAMES, FLEN, CYC, #samples))

------------------------------------------------------------------ the new pipeline
local native = W.find_frame_size(samples)
print("find_frame_size ->", native)
assert(native == FLEN, "expected the native frame size to be found")

local ncount = math.floor(#samples / native)
local cycles = nil
local single = {}
for i = 1, ncount do
  local fr = {}
  for f = 1, native do fr[f] = samples[(i-1)*native + f] end
  if not cycles then
    local c = W.detect_cycles(fr)
    if c > 1 then cycles = c end
  end
  single[i] = fr
end
cycles = cycles or 1
print("detected cycles per frame ->", cycles)
assert(cycles == CYC, "expected " .. CYC .. " cycles, got " .. cycles)

for i = 1, ncount do single[i] = W.one_cycle(single[i], cycles) end
local picked, idxs = W.select_frames(single, 12)
print(string.format("picked %d of %d frames, indices %s", #picked, ncount, table.concat(idxs, ",")))

local out = {}
local len0 = #picked[1]
for i = 1, #picked do out[i] = W.bandlimit_resample(picked[i], len0) end

------------------------------------------------------------ assertions on the result
local bad_len, bad_cyc = 0, 0
for i = 1, #out do
  if #out[i] ~= len0 then bad_len = bad_len + 1 end
  if W.detect_cycles(out[i]) > 1 then bad_cyc = bad_cyc + 1 end
end
print()
print(string.format("written frames: %d x %d samples", #out, len0))
print(string.format("  wrong length : %d   (must be 0)", bad_len))
print(string.format("  multi-cycle  : %d   (must be 0)", bad_cyc))

-- Note: NOT asserted on count_upward_crossings. A single cycle of a harmonically rich
-- waveform crosses zero more than once, and that is the waveform, not a defect. The
-- frames here carry a 4th or 6th harmonic, so they cross twice. detect_cycles is the
-- measure that matters.

if bad_len ~= 0 then error("frames do not share a length") end
if bad_cyc ~= 0 then error("a written frame still holds more than one cycle") end

print()
print("E2E: PASS — every frame is one cycle, all the same length")
