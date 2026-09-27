--[[
  load_test.lua — load the Renoise tool under a stubbed Renoise scripting API.

  Why this exists: a tool that is syntactically valid can still be dead on arrival,
  because Renoise evaluates the chunk and calls `renoise()` at load time. `luac -p`
  proves nothing about that. This harness stubs the parts of the API the tool touches,
  installs the tool the way Renoise does (a directory named <Id>.xrnx, `require` on its
  own files), runs the init path and reports every error.

  It is the only check available when Renoise is already running and must not be
  restarted — which is the normal case on this machine.

  Usage:  luajit tests/load_test.lua            (from the repo root)
          luarocks-free, only stock LuaJIT / Lua 5.1
]]

local TOOL_DIR = arg[1] or "renoise-tool"

-------------------------------------------------------------------------------- report

local failures = {}
local checks = 0

local function check(name, fn)
  checks = checks + 1
  local ok, err = pcall(fn)
  if ok then
    print(string.format("  ok   %s", name))
  else
    print(string.format("  FAIL %s\n       %s", name, tostring(err)))
    failures[#failures + 1] = name .. ": " .. tostring(err)
  end
end

-------------------------------------------------------------------------------- stubs

-- A value that answers any key with another stub, is callable, and is comparable.
-- Deep chains are what the tool actually does (`buffer.has_sample_data`,
-- `song.selected_sample.sample_buffer...`), so the stub has to be lazy.
local function stub(name)
  local cache = {}
  local mt = {}
  mt.__index = function(_, k)
    if not cache[k] then cache[k] = stub(name .. "." .. tostring(k)) end
    return cache[k]
  end
  mt.__call = function(_, ...) return stub(name .. "()") end
  mt.__tostring = function() return name end
  mt.__eq = function() return true end
  -- arithmetic / comparison: the LFO math does real sums on stubbed fields
  mt.__add = function() return 0 end
  mt.__sub = function() return 0 end
  mt.__mul = function() return 0 end
  mt.__div = function() return 0 end
  mt.__lt = function() return false end
  mt.__le = function() return true end
  return setmetatable({}, mt)
end

local recorded = { dialogs = {}, statuses = {}, errors = {} }

local renoise = stub("renoise")
-- The pieces whose behaviour the tool branches on need real answers, not stubs.
renoise.song = function() return stub("song") end
renoise.app = function()
  return {
    show_status_message = function(msg) recorded.statuses[#recorded.statuses + 1] = tostring(msg) end,
    show_error_message = function(msg) recorded.errors[#recorded.errors + 1] = tostring(msg) end,
    show_message_box = function(t) recorded.dialogs[#recorded.dialogs + 1] = tostring(t) end,
  }
end
renoise.tool = function()
  return {
    available_keybinding_actions = {},
    add_menu_entry = function(entry) recorded.menu = entry end,
    add_timer = function() end,
    add_keybinding = function() end,
    remove_keybinding = function() end,
    add_app_idle_observable = function() end,
    add_track_observable = function() end,
    add_song_observable = function() end,
  }
end
renoise.ViewBuilder = function()
  return {
    panel = function() return stub("panel") end,
    column = function() return stub("column") end,
    row = function() return stub("row") end,
    text = function() return stub("text") end,
    button = function() return stub("button") end,
    checkbox = function() return stub("checkbox") end,
    popup = function() return stub("popup") end,
    multiline_text = function() return stub("multiline_text") end,
    horizontal_aligner = function() return stub("horizontal_aligner") end,
    vertical_aligner = function() return stub("vertical_aligner") end,
  }
end

_G.renoise = renoise

-- `require` resolves relative to the tool directory, exactly as Renoise does.
local loader = package.loaders[2]
package.loaders[2] = function(mod)
  local path = TOOL_DIR .. "/" .. mod .. ".lua"
  local f = io.open(path, "r")
  if f then f:close(); return loader(path:gsub("%.lua$", "")) end
  return loader(mod)
end

-------------------------------------------------------------------------------- run

print("load_test: " .. TOOL_DIR)

check("main.lua lints (loadfile)", function()
  assert(loadfile(TOOL_DIR .. "/main.lua"))
end)

check("dependencies resolve (wtlib, zipwriter)", function()
  local f = io.open(TOOL_DIR .. "/wtlib.lua", "r"); assert(f, "wtlib.lua missing"); f:close()
  local z = io.open(TOOL_DIR .. "/zipwriter.lua", "r"); assert(z, "zipwriter.lua missing"); z:close()
end)

check("manifest.xml parses and matches the directory name", function()
  local f = assert(io.open(TOOL_DIR .. "/manifest.xml"), "manifest.xml missing")
  local xml = f:read("*a"); f:close()
  local id = xml:match("<Id>%s*([^%s<]+)")
  local version = xml:match("<Version>%s*([^%s<]+)")
  local api = xml:match("<ApiVersion>%s*([^%s<]+)")
  local name = xml:match("<Name>%s*([^<]+)")
  assert(id, "no <Id>")
  assert(version, "no <Version>")
  assert(api, "no <ApiVersion>")
  assert(name, "no <Name>")
  assert(id == "com.meneses.WavetableBuilder", "unexpected Id: " .. id)
  assert(api == "6.2", "ApiVersion should be 6.2 (Renoise 3.5.4), got " .. api)
  print(string.format("       Id=%s  Version=%s  ApiVersion=%s", id, version, api))
end)

-- wtlib and zipwriter must load and expose the tables main.lua indexes into.
check("wtlib loads and exposes its api", function()
  local ok, wtlib = pcall(require, "wtlib")
  assert(ok, tostring(wtlib))
  assert(type(wtlib) == "table", "wtlib must return a table")
  assert(next(wtlib) ~= nil, "wtlib returned an empty table")
end)

check("zipwriter loads and exposes its api", function()
  local ok, zw = pcall(require, "zipwriter")
  assert(ok, tostring(zw))
  assert(type(zw) == "table", "zipwriter must return a table")
  assert(next(zw) ~= nil, "zipwriter returned an empty table")
end)

-- The real prize: run the entry point with the stubbed API. If Renoise were to
-- call this and it threw, the tool would appear in the browser but do nothing.
check("entry point runs against the stubbed api", function()
  local chunk = assert(loadfile(TOOL_DIR .. "/main.lua"))
  local ok, err = pcall(chunk)
  assert(ok, "evaluating main.lua threw: " .. tostring(err))
end)

-------------------------------------------------------------------------------- verdict

print(string.format("\n%d checks, %d failed", checks, #failures))
if #failures > 0 then
  for _, f in ipairs(failures) do print("  " .. f) end
  os.exit(1)
end
print("load_test: PASS")
