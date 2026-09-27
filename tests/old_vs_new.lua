-- Same source table through OLD and NEW logic, so the difference is visible rather than
-- asserted. This is the repro the user reported.
package.path = (arg and arg[0] and arg[0]:match("^(.*)/[^/]*$") or ".") .. "/../renoise-tool/?.lua;" .. package.path
local W = require("wtlib")

local FRAMES, FLEN, CYC = 256, 2048, 4
local samples = {}
for f = 0, FRAMES-1 do
  for i = 1, FLEN do
    local k = (i-1) % (FLEN/CYC)
    local v = math.sin(2*math.pi*k/(FLEN/CYC)) + 0.3*math.sin(2*math.pi*(1+f%7)*k/(FLEN/CYC))
    samples[f*FLEN+i] = v * (1 - 0.3*f/FRAMES)
  end
end
local N = 12
print(string.format("source: %d frames x %d samples, %d cycles/frame, total %d", FRAMES, FLEN, CYC, #samples))
print()

-- OLD: floor(total/N) blocks, no cycle handling at all
local flen_old = math.floor(#samples / N)
local old_cyc, old_len = 0, flen_old
for i = 1, N do
  local fr = {}
  for f = 1, flen_old do fr[f] = samples[(i-1)*flen_old + f] end
  local c = W.detect_cycles(fr)
  if c > old_cyc then old_cyc = c end
end
print("OLD (what shipped until now)")
print(string.format("   frames   : %d x %d samples", N, old_len))
print(string.format("   cycles   : up to %d per frame  <- instrument plays %dx sharp", old_cyc, old_cyc))
local mid = (flen_old) % (FLEN/CYC)
print(string.format("   slice at : sample %d, which is offset %d into a %d-sample cycle -> mid-cycle",
  flen_old, mid, FLEN/CYC))
print()

-- NEW
local native = W.find_frame_size(samples)
local ncount = math.floor(#samples / native)
local cycles
local single = {}
for i = 1, ncount do
  local fr = {}
  for f = 1, native do fr[f] = samples[(i-1)*native + f] end
  if not cycles then local c = W.detect_cycles(fr); if c > 1 then cycles = c end end
  single[i] = fr
end
cycles = cycles or 1
for i = 1, ncount do single[i] = W.one_cycle(single[i], cycles) end
local picked = W.select_frames(single, N)
local out = {}
for i = 1, #picked do out[i] = W.bandlimit_resample(picked[i], #picked[1]) end
local new_cyc = 0
for i = 1, #out do new_cyc = math.max(new_cyc, W.detect_cycles(out[i])) end

print("NEW")
print(string.format("   frame size found : %d (source is %d)", native, FLEN))
print(string.format("   frames           : %d x %d samples", #out, #out[1]))
print(string.format("   cycles           : %d per frame  <- one cycle, so it plays at pitch", new_cyc))
print(string.format("   frame length     : %d = %d/%d, an exact single cycle", #out[1], FLEN, CYC))
