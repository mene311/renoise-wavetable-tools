--[[
  zipwriter.lua — the smallest zip writer that Renoise will read.

  Store only (no compression): sample data inside an instrument does not need it, and a
  deflate encoder has no business being hand written. Renoise binds the files in SampleData/
  to sample slots by the SampleNN index in the entry name (the rest of the name is cosmetic
  and the extension is never referenced in the XML), so entries are written in slot order.

  Two details that bite:
    * CRC32 must be right; zlib readers reject a bad one. Computed here with arithmetic
      only, so it does not depend on a `bit` library being present.
    * the central directory needs the offsets of every local header, so entries are
      buffered as they are added and only written out when the archive closes.

  Usage:
    local z = ZipWriter.new()
    z:add("Instrument.xml", xml_string)
    z:add("SampleData/Sample00 (frame 01).wav", wav_string)
    z:save("/path/to/out.xrni")      -- returns true, or nil + message
]]

local ZipWriter = {}
ZipWriter.__index = ZipWriter

-- CRC32 ---------------------------------------------------------------------------
-- 32 bit XOR, built from arithmetic only. Subtracting instead (the `a - b - 1` idiom) is
-- NOT xor and silently produces a wrong checksum, which makes every zip reader reject the
-- archive. Slow but correct, and these archives are small.
local function bxor32(a, b)
  local x, bitval = 0, 1
  for _ = 1, 32 do
    local abit, bbit = a % 2, b % 2
    if abit ~= bbit then x = x + bitval end
    a = math.floor(a / 2); b = math.floor(b / 2)
    if a == 0 and b == 0 then break end
    bitval = bitval * 2
  end
  return x
end

local crc_table
local function build_crc_table()
  crc_table = {}
  for n = 0, 255 do
    local c = n
    for _ = 1, 8 do
      local low = c % 2
      c = math.floor(c / 2)
      if low == 1 then c = bxor32(c, 0xEDB88320) end
    end
    crc_table[n] = c
  end
end

local function crc32(s)
  if not crc_table then build_crc_table() end
  local crc = 0xFFFFFFFF
  for i = 1, #s do
    local byte = string.byte(s, i)
    local idx = bxor32(crc % 256, byte)
    crc = bxor32(math.floor(crc / 256), crc_table[idx])
  end
  return bxor32(crc, 0xFFFFFFFF)
end

-- little endian integer packing ----------------------------------------------------
local function u16(n)
  return string.char(n % 256, math.floor(n / 256) % 256)
end

local function u32(n)
  n = n % 0x100000000
  return string.char(n % 256, math.floor(n / 256) % 256,
                     math.floor(n / 65536) % 256, math.floor(n / 16777216) % 256)
end

-- writer ---------------------------------------------------------------------------
function ZipWriter.new()
  return setmetatable({ entries = {} }, ZipWriter)
end

function ZipWriter:add(path, data, is_text)
  local name = path
  local payload = data
  if is_text then
    -- text files in a zip are convention-ally UTF-8 without a BOM; nothing to do, but
    -- keep the parameter so callers can be explicit about intent
    payload = data
  end
  self.entries[#self.entries + 1] = {
    name = name,
    data = payload,
    crc = crc32(payload),
    size = #payload,
  }
end

function ZipWriter:get_data()
  local out, central = {}, {}
  local offset = 0
  for _, e in ipairs(self.entries) do
    local name = e.name
    local header = "PK\003\004"          -- local file header
      .. u16(20)                          -- version needed: 2.0
      .. u16(0x0800)                      -- flags: names are UTF-8
      .. u16(0)                           -- method 0 = store
      .. u16(0) .. u16(0x21)              -- time 00:00, date 1980-01-01 (0 is invalid)
      .. u32(e.crc) .. u32(e.size) .. u32(e.size)
      .. u16(#name) .. u16(0)             -- name length, extra length
      .. name
    out[#out + 1] = header
    out[#out + 1] = e.data
    central[#central + 1] = "PK\001\002"  -- central directory header
      .. u16(20) .. u16(20) .. u16(0x0800) .. u16(0)
      .. u16(0) .. u16(0x21)
      .. u32(e.crc) .. u32(e.size) .. u32(e.size)
      .. u16(#name) .. u16(0) .. u16(0)
      .. u16(0) .. u16(0) .. u32(0)
      .. u32(offset)
      .. name
    offset = offset + #header + #e.data
  end
  local central_data = table.concat(central)
  local end_record = "PK\005\006"
    .. u16(0) .. u16(0)
    .. u16(#self.entries) .. u16(#self.entries)
    .. u32(#central_data) .. u32(offset) .. u16(0)
  return table.concat(out) .. central_data .. end_record
end

function ZipWriter:save(path)
  local data = self:get_data()
  local f, err = io.open(path, "wb")
  if not f then return nil, "could not open " .. tostring(path) .. " for writing: " .. tostring(err) end
  f:write(data)
  f:close()
  return true, #data
end

return ZipWriter
