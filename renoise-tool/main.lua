--[[
  Wavetable Instrument Builder — build a gate-scan wavetable instrument from a wavetable
  that is already sitting in a sample slot.

  Why it writes a file instead of building the instrument through the API: an instrument's
  macro mappings are read-only in the scripting API (`renoise.InstrumentMacro.mappings` is
  documented READ-ONLY), and instrument chains cannot be automated by anything except a
  macro. So the macro that walks the table has to exist in the file, which means writing a
  complete .xrni and loading it. Everything else — frames, tuning, chains, gates — would be
  possible through the API, but a half-built instrument is no use to anyone.

  Usage: load a wavetable as a sample (Renoisewill happily load a 2048 x N wavetable .wav),
  select it, then run this tool from the Tools menu or its keybinding.
]]

local WTLib = require("wtlib")
local ZipWriter = require("zipwriter")

local TOOL_NAME = "Wavetable Instrument Builder"
local MAX_FRAMES = 12          -- Renoise allows 12 voices per note column
local PREFERRED_FRAMES = { 12, 8, 6, 4, 3, 2 }
local DEFAULT_FRAME_LENGTH = 2048

-------------------------------------------------------------------------------- helpers

local function read_scalar(v)
  if type(v) == "table" then return v[1] end
  return v
end

local function suggested_frame_count(total_frames)
  for _, n in ipairs(PREFERRED_FRAMES) do
    if total_frames % n == 0 then return n end
  end
  return 4
end

local function fmt(x, digits)
  return string.format("%." .. (digits or 3) .. "f", x)
end

-- Read the first sample of the selected instrument as a wavetable and chop it into frames.
-- Returns frames, info, or nil plus a message.
local function read_frames(frame_count, explicit_sample)
  local song = renoise.song()
  local sample = explicit_sample or song.selected_sample
  if not sample then
    return nil, "Select a sample first (the wavetable you want to convert)."
  end
  local buffer = sample.sample_buffer
  if not buffer or not buffer.has_sample_data then
    return nil, "The selected sample holds no audio data."
  end
  local total = buffer.number_of_frames
  local rate = buffer.sample_rate
  if total < 8 then
    return nil, "The selected sample is too short to hold frames."
  end
  local channels = buffer.number_of_channels
  local frame_length = math.floor(total / frame_count)
  if frame_length < 4 then
    return nil, "Not enough audio for " .. frame_count .. " frames."
  end
  local used = frame_length * frame_count
  local base = 1                 -- buffer indices are documented as 1..number_of_frames

  local frames = {}
  for i = 1, frame_count do
    local frame = {}
    for f = 1, frame_length do
      local index = (i - 1) * frame_length + (f - 1) + base
      local v = read_scalar(buffer:sample_data(1, index)) or 0
      frame[f] = v
    end
    frames[i] = frame
  end

  return frames, {
    name = sample.name or "wavetable",
    total_frames = total,
    used_frames = used,
    trimmed = total - used,
    sample_rate = rate,
    channels = channels,
    frame_length = frame_length,
    frame_count = frame_count,
  }
end

-- Build the instrument and write it out. Returns a report table, or nil plus a message.
-- `source` is optional: {sample = renoise.Sample, label = string} to build something other than
-- the selected sample.
local function build(frame_count, with_sweep, instrument_name, out_path, source)
  local frames, info = read_frames(frame_count, source and source.sample)
  if not frames then return nil, info end

  local tuning = WTLib.tuning(info.sample_rate, info.frame_length)

  local names = {}
  for i = 1, frame_count do
    names[i] = string.format("frame %02d", i)
  end

  local xml = WTLib.instrument_xml({
    name = instrument_name,
    frame_count = frame_count,
    frame_length = info.frame_length,
    sample_rate = info.sample_rate,
    tuning = tuning,
    with_sweep = with_sweep,
    frame_names = names,
  })

  local zip = ZipWriter.new()
  zip:add("Instrument.xml", xml)
  for i = 1, frame_count do
    local wav = WTLib.wav16(frames[i], info.sample_rate)
    zip:add(string.format("SampleData/Sample%02d (frame %02d).wav", i - 1, i), wav)
  end
  local ok, bytes = zip:save(out_path)
  if not ok then return nil, bytes end

  -- what the frames look like, so the report can warn about surprises
  local crossings, max_crossings = 0, 0
  for i = 1, frame_count do
    local c = WTLib.count_upward_crossings(frames[i])
    crossings = crossings + c
    if c > max_crossings then max_crossings = c end
  end

  return {
    info = info,
    tuning = tuning,
    bytes = bytes,
    path = out_path,
    avg_crossings = crossings / frame_count,
    max_crossings = max_crossings,
    with_sweep = with_sweep,
  }
end

local show_result   -- defined below; build_batch (above it) calls it

-- What a batch run can walk over. Song samples are the natural unit: a wavetable is one
-- sample, and Renoise loads each wavetable file as one sample.
local function collect_sources(mode)
  local song = renoise.song()
  local sources = {}
  if mode == "sample" then
    local sample = song.selected_sample
    if sample then sources[1] = { sample = sample, label = sample.name or "wavetable" } end
  elseif mode == "instrument" then
    local instrument = song.selected_instrument
    if instrument then
      for _, sample in ipairs(instrument.samples) do
        if sample.sample_buffer and sample.sample_buffer.has_sample_data then
          sources[#sources + 1] = { sample = sample, label = sample.name or ("sample " .. #sources) }
        end
      end
    end
  else -- "song"
    for _, instrument in ipairs(song.instruments) do
      for _, sample in ipairs(instrument.samples) do
        if sample.sample_buffer and sample.sample_buffer.has_sample_data then
          sources[#sources + 1] = { sample = sample,
            label = (instrument.name ~= "" and instrument.name or "instrument")
                    .. " - " .. (sample.name or ("sample " .. #sources)) }
        end
      end
    end
  end
  return sources
end

-- Batch: one instrument per source, written into a folder the user picks.
local function build_batch(mode, frame_count, with_sweep, suffix, load_first)
  local sources = collect_sources(mode)
  if #sources == 0 then
    renoise.app():show_warning("Nothing to convert in that scope.")
    return
  end
  local folder = renoise.app():prompt_for_path("Choose a folder for the instruments")
  if not folder or folder == "" then return end
  local built, failed, first_path = 0, {}, nil
  for _, source in ipairs(sources) do
    local name = source.label .. suffix
    name = name:gsub("[/\\:*?\"<>|]", "-")
    local path = folder .. "/" .. name .. ".xrni"
    local report, message = build(frame_count, with_sweep, name, path, source)
    if report then
      built = built + 1
      first_path = first_path or path
    else
      failed[#failed + 1] = source.label .. ": " .. tostring(message)
    end
  end
  if first_path and load_first then
    renoise.app():load_instrument(first_path)
  end
  local lines = { built .. " of " .. #sources .. " instruments written to " .. folder }
  for i = 1, math.min(#failed, 6) do lines[#lines + 1] = failed[i] end
  if #failed > 6 then lines[#lines + 1] = ("… and %d more failures"):format(#failed - 6) end
  show_result(nil, table.concat(lines, "\n"))
end

-------------------------------------------------------------------------------- the dialog

show_result = function(report, message)
  local text = {}
  if message then text[#text + 1] = message end
  if report then
    local i, t = report.info, report.tuning
    text[#text + 1] = ("Frames:            %d x %d samples"):format(i.frame_count, i.frame_length)
    text[#text + 1] = ("Source:            %s, %d Hz, %d channel(s)"):format(i.name, i.sample_rate, i.channels)
    text[#text + 1] = ("Used:              %d of %d samples"):format(i.used_frames, i.total_frames)
    if i.trimmed > 0 then
      text[#text + 1] = ("Note:              %d trailing samples dropped (length did not divide evenly)"):format(i.trimmed)
    end
    text[#text + 1] = ("Frame pitch:       %s Hz (note %.2f)"):format(fmt(t.f0, 2), t.exact_note)
    text[#text + 1] = ("Tuning:            BaseNote %d, Finetune %+d cents"):format(t.base_note, t.finetune)
    if t.note_clamped or t.cents_clamped then
      text[#text + 1] = "Note:              tuning was clamped, this cycle length sits outside the note range"
    end
    text[#text + 1] = ("Sweep template:    %s"):format(report.with_sweep and "yes" or "no")
    text[#text + 1] = ("Written:           %s (%d KB)"):format(report.path, math.floor(report.bytes / 1024))
    if report.max_crossings > 8 then
      text[#text + 1] = ("Warning:           frames cross zero up to %d times, which usually means the"):format(report.max_crossings)
      text[#text + 1] = "                   frames hold more than one cycle. The instrument will sound sharp."
    end
  end
  renoise.app():show_message(TOOL_NAME .. "\n\n" .. table.concat(text, "\n"))
end

local function on_run()
  local song = renoise.song()
  local sample = song.selected_sample
  if not sample or not sample.sample_buffer or not sample.sample_buffer.has_sample_data then
    renoise.app():show_warning("Select the sample that holds the wavetable first.")
    return
  end
  local total = sample.sample_buffer.number_of_frames

  local vb = renoise.ViewBuilder()
  local DEFAULT_MARGIN = renoise.ViewBuilder.DEFAULT_CONTROL_MARGIN

  local FRAME_CHOICES = { 2, 3, 4, 6, 8, 12 }
  local suggested = suggested_frame_count(total)
  local suggested_index = 1
  for i, v in ipairs(FRAME_CHOICES) do
    if v == suggested then suggested_index = i end
  end
  local frame_popup = vb:popup {
    items = { "2", "3", "4", "6", "8", "12" },
    value = suggested_index,       -- the popup's value is the selected INDEX, not the label
  }
  local SCOPE_CHOICES = { "the selected sample", "every sample in this instrument", "every instrument in the song" }
  local SCOPE_MODES = { "sample", "instrument", "song" }
  local scope_popup = vb:popup { items = SCOPE_CHOICES, value = 1 }
  local sweep_check = vb:checkbox { value = false }
  local load_check = vb:checkbox { value = true }
  local name_field = vb:textfield {
    text = (sample.name or "Wavetable") .. " WT",
    width = 260,
  }

  local info_text = ("Selected sample: %s\n%d samples, %d Hz%s"):format(
    sample.name or "?", total, sample.sample_buffer.sample_rate,
    sample.sample_buffer.number_of_frames % DEFAULT_FRAME_LENGTH == 0
      and ("\nLooks like " .. (total / DEFAULT_FRAME_LENGTH) .. " frames of 2048 samples.")
      or "\nFrame length is derived from the sample length and the frame count.")

  local content = vb:column {
    margin = DEFAULT_MARGIN,
    spacing = DEFAULT_MARGIN,
    views = {
    vb:text { text = info_text, width = 340 },
    vb:row {
      views = {
        vb:text { text = "Frames:", width = 70 },
        frame_popup,
        vb:text { text = "  (12 is the ceiling in Renoise)", width = 200 },
      },
    },
    vb:row { views = { vb:text { text = "Convert:", width = 70 }, scope_popup } },
    vb:row { views = { vb:text { text = "Name:", width = 70 }, name_field } },
    vb:row { views = { sweep_check, vb:text { text = "  add the sweep template (LFO, Hydra, macros, reset)" } } },
    vb:row { views = { load_check, vb:text { text = "  load the instrument when it is written" } } },
    vb:row {
      views = {
      vb:button {
        text = "Build and save...",
        width = 130,
        notifier = function()
          local path = renoise.app():prompt_for_filename_to_write("xrni",
            "Save the wavetable instrument")
          if not path or path == "" then return end
          local frame_count = FRAME_CHOICES[frame_popup.value] or suggested
          local report, message = build(frame_count, sweep_check.value,
                                        name_field.text, path)
          if not report then
            renoise.app():show_error(message or "Build failed.")
            return
          end
          if load_check.value then
            renoise.app():load_instrument(path)
          end
          show_result(report)
        end
      },
      vb:button {
        text = "Build all…",
        width = 110,
        notifier = function()
          build_batch(SCOPE_MODES[scope_popup.value] or "sample",
                      FRAME_CHOICES[frame_popup.value] or suggested,
                      sweep_check.value, " WT", true)
        end
      },
      vb:button {
        text = "Cancel",
        notifier = function() renoise.app():show_status("Cancelled") end
      },
      },
    },
    },
  }

  renoise.app():show_custom_dialog(TOOL_NAME, content)
end

-------------------------------------------------------------------------------- wiring

renoise.tool():add_menu_entry {
  name = "Main Menu:Tools:" .. TOOL_NAME .. "...",
  invoke = on_run,
}

renoise.tool():add_keybinding {
  name = "Global:Tools:" .. TOOL_NAME,
  invoke = on_run,
}
