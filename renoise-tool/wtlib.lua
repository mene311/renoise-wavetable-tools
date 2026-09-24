--[[
  wtlib.lua — the parts of the builder that do not need Renoise: tuning maths, WAV encoding
  and the instrument XML.

  The XML mirrors renoise-wavetable-tools/wt_xrni.py exactly, because that output is checked
  against Renoise's own RenoiseInstrument34.xsd. Anything that differs here is a bug, so keep
  the two in step.

  The architecture it writes:
    chain 0        GATES   SampleMixer + one gate LFO per frame
    chains 1..N    FRAME   SampleMixer (volume 0) + Send (MuteSource) -> SUM
    chain N+1      SUM     SampleMixer (the instrument's output)
    macro 1        "WT Position", mapped to every gate LFO's parameter 8 (its position),
                   which is how the table gets walked
    optional       sweep rig in the SUM chain: SWEEP (LFO, off) -> HYDRA -> INSTR MACRO,
                   plus a Key Tracker on the LFO's reset
]]

local WTLib = {}

-- tuning ---------------------------------------------------------------------------

-- Frame pitch: a cycle of `cycle_len` samples at `sample_rate` has a natural frequency of
-- sample_rate / cycle_len, which is then expressed as a Renoise note plus cents.
--
-- The sign matters and was wrong once: Renoise plays the sample at
-- 2^((played - base_note)/12) * 2^(transpose/12) * 2^(finetune/1200), so a sample that is
-- FLAT of its note needs a POSITIVE finetune to come up to pitch.
function WTLib.tuning(sample_rate, cycle_len)
  -- Python's round() is half to even; math.floor(x + 0.5) is half up, and the difference
  -- shows up as an off-by-one note on exact ties, so mirror Python instead.
  local function pyround(x)
    local f = math.floor(x)
    local d = x - f
    if d > 0.5 then return f + 1 end
    if d < 0.5 then return f end
    return (f % 2 == 0) and f or (f + 1)
  end
  local f0 = sample_rate / cycle_len
  local exact = 57 + 12 * (math.log(f0 / 440) / math.log(2))
  -- cents come off the UNCLAMPED note, exactly like freq_to_note in wt_xrni.py; clamping
  -- first would produce a nonsense finetune for cycles outside the note range
  local note = pyround(exact)
  local cents = pyround((note - exact) * 100)
  local note_clamped, cents_clamped = false, false
  if note < 0 then note, note_clamped = 0, true end
  if note > 119 then note, note_clamped = 119, true end
  if cents > 127 then cents, cents_clamped = 127, true end
  if cents < -128 then cents, cents_clamped = -128, true end
  return {
    f0 = f0, exact_note = exact, base_note = note, finetune = cents,
    note_clamped = note_clamped, cents_clamped = cents_clamped,
  }
end

-- how many cycles a frame holds, cheaply: count upward zero crossings. A single cycle
-- crosses zero once (twice if you count both directions); many crossings mean the frame
-- repeats and the instrument will sound sharp.
function WTLib.count_upward_crossings(frame)
  local crossings, prev = 0, frame[1]
  for i = 2, #frame do
    local v = frame[i]
    if prev <= 0 and v > 0 then crossings = crossings + 1 end
    prev = v
  end
  return crossings
end

-- WAV ------------------------------------------------------------------------------

-- 16 bit mono PCM, which is what the Python builder embeds too (as 16 bit FLAC).
function WTLib.wav16(frame, sample_rate)
  local chunk = {}
  local n = #frame
  local data_bytes = n * 2
  chunk[#chunk + 1] = "RIFF"
  chunk[#chunk + 1] = WTLib.u32(36 + data_bytes)
  chunk[#chunk + 1] = "WAVEfmt "
  chunk[#chunk + 1] = WTLib.u32(16) .. WTLib.u16(1) .. WTLib.u16(1)
  chunk[#chunk + 1] = WTLib.u32(sample_rate)
  chunk[#chunk + 1] = WTLib.u32(sample_rate * 2)
  chunk[#chunk + 1] = WTLib.u16(2) .. WTLib.u16(16)
  chunk[#chunk + 1] = "data" .. WTLib.u32(data_bytes)
  local pcm = {}
  for i = 1, n do
    local v = frame[i]
    if v > 1 then v = 1 elseif v < -1 then v = -1 end
    local s = math.floor(v * 32767 + 0.5)
    if s < 0 then s = s + 65536 end
    pcm[i] = string.char(s % 256, math.floor(s / 256) % 256)
  end
  chunk[#chunk + 1] = table.concat(pcm)
  return table.concat(chunk)
end

function WTLib.u16(n)
  return string.char(n % 256, math.floor(n / 256) % 256)
end

function WTLib.u32(n)
  n = n % 0x100000000
  return string.char(n % 256, math.floor(n / 256) % 256,
                     math.floor(n / 65536) % 256, math.floor(n / 16777216) % 256)
end

-- XML ------------------------------------------------------------------------------

-- names can come from anywhere (a sample name, the user's text field), so escape them
function WTLib.esc(s)
  s = tostring(s)
  s = s:gsub("&", "&amp;")
  s = s:gsub("<", "&lt;")
  s = s:gsub(">", "&gt;")
  s = s:gsub('"', "&quot;")
  return s
end

local function param(name, v, viz, indent)
  local pad = indent or "        "
  return pad .. "<" .. name .. ">"
    .. "<Value>" .. tostring(v) .. "</Value>"
    .. "<Visualization>" .. (viz or "Device only") .. "</Visualization>"
    .. "</" .. name .. ">"
end

-- A gate LFO: a frozen LFO reading a custom unipolar envelope that holds one triangle for
-- this frame, spaced `spacing` lines apart so neighbouring triangles always add up to 1.0.
function WTLib.gate_lfo_xml(index, frame_count, spacing, dest_track, amp, offset)
  local L = frame_count * spacing
  local peak = (index - 1) * spacing
  local points = {}
  for x = 0, L do
    local d = (x - peak) % L
    if d > L / 2 then d = d - L end
    local v = 1 - math.abs(d) / spacing
    if v < 0 then v = 0 end
    points[#points + 1] = "                <Point>" .. x .. "," ..
      string.format("%.6f", v) .. ",0.0</Point>"
  end
  return table.concat({
    '          <LfoDevice type="LfoDevice">',
    '            <SelectedPresetName>Init</SelectedPresetName>',
    '            <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>',
    '            <SelectedPresetIsModified>true</SelectedPresetIsModified>',
    '            <CustomDeviceName>gate ' .. string.format("%02d", index) .. '</CustomDeviceName>',
    '            <IsMaximized>true</IsMaximized>',
    '            <IsSelected>false</IsSelected>',
    param("IsActive", "1.0"),
    param("DestTrack", tostring(dest_track)),
    param("DestEffect", "0"),
    param("DestParameter", "2"),
    param("Amplitude", tostring(amp)),
    param("Offset", tostring(offset)),
    param("Frequency", "9.99999997e-07"),
    param("Type", "4"),
    '            <CustomEnvelope>',
    '              <PlayMode>Lines</PlayMode>',
    '              <Length>' .. L .. '</Length>',
    '              <ValueQuantum>0.0</ValueQuantum>',
    '              <Polarity>Unipolar</Polarity>',
    '              <Points>',
    table.concat(points, "\n"),
    '              </Points>',
    '            </CustomEnvelope>',
    '            <CustomEnvelopeOneShot>false</CustomEnvelopeOneShot>',
    '            <UseAdjustedEnvelopeLength>true</UseAdjustedEnvelopeLength>',
    '          </LfoDevice>',
  }, "\n")
end

function WTLib.mixer_xml(custom_name, volume, volume_viz)
  volume_viz = volume_viz or "Mixer and Device"
  return table.concat({
    '          <SampleMixerDevice type="SampleMixerDevice">',
    '            <SelectedPresetName>Init</SelectedPresetName>',
    '            <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>',
    '            <SelectedPresetIsModified>false</SelectedPresetIsModified>',
    '            <CustomDeviceName>' .. custom_name .. '</CustomDeviceName>',
    '            <IsMaximized>true</IsMaximized>',
    '            <IsSelected>false</IsSelected>',
    param("IsActive", "1.0"),
    param("Panning", "0.5"),
    param("Volume", tostring(volume), volume_viz or "Device only"),
    param("PostPanning", "0.5"),
    param("PostVolume", "1.0"),
    '          </SampleMixerDevice>',
  }, "\n")
end

function WTLib.send_xml(dest)
  return table.concat({
    '          <SendDevice type="SendDevice">',
    '            <SelectedPresetName>Init</SelectedPresetName>',
    '            <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>',
    '            <SelectedPresetIsModified>true</SelectedPresetIsModified>',
    '            <IsMaximized>false</IsMaximized>',
    '            <IsSelected>false</IsSelected>',
    param("IsActive", "1.0"),
    param("SendAmount", "1.0", "Mixer and Device"),
    param("SendPan", "0.5"),
    param("DestSendTrack", tostring(dest)),
    '            <MuteSource>true</MuteSource>',
    '            <SmoothParameterChanges>true</SmoothParameterChanges>',
    '            <ApplyPostVolume>true</ApplyPostVolume>',
    '          </SendDevice>',
  }, "\n")
end

-- The sweep template: infrastructure only, every destination left unassigned except the one
-- link that makes it usable (LFO -> Hydra input, Hydra output 1 -> macro 1). The macro is the
-- only route to the gate parameters from inside an instrument, because instrument chains
-- cannot be automated directly.
function WTLib.sweep_rig_xml()
  local shape = {}
  for i = 0, 15 do
    local v = math.abs(1 - 2 * (i / 15))
    shape[#shape + 1] = "                <Point>" .. i .. "," ..
      string.format("%.4f", v) .. ",0.0</Point>"
  end
  local lfo = table.concat({
    '          <LfoDevice type="LfoDevice">',
    '            <SelectedPresetName>Init</SelectedPresetName>',
    '            <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>',
    '            <SelectedPresetIsModified>true</SelectedPresetIsModified>',
    '            <CustomDeviceName>SWEEP</CustomDeviceName>',
    '            <IsMaximized>true</IsMaximized>',
    '            <IsSelected>false</IsSelected>',
    param("IsActive", "0.0"),   -- ships off
    param("DestTrack", "-1"),
    param("DestEffect", "2"),  -- the Hydra
    param("DestParameter", "1.0"),  -- its input
    param("Amplitude", "1.0"),
    param("Offset", "0.0"),
    param("Frequency", "16.0"),
    param("Type", "4"),
    '            <CustomEnvelope>',
    '              <PlayMode>Lines</PlayMode>',
    '              <Length>16</Length>',
    '              <ValueQuantum>0.0</ValueQuantum>',
    '              <Polarity>Unipolar</Polarity>',
    '              <Points>',
    table.concat(shape, "\n"),
    '              </Points>',
    '            </CustomEnvelope>',
    '            <CustomEnvelopeOneShot>false</CustomEnvelopeOneShot>',
    '            <UseAdjustedEnvelopeLength>true</UseAdjustedEnvelopeLength>',
    '          </LfoDevice>',
  }, "\n")

  local hydra = { '          <HydraDevice type="HydraDevice">',
    '            <SelectedPresetName>Init</SelectedPresetName>',
    '            <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>',
    '            <SelectedPresetIsModified>true</SelectedPresetIsModified>',
    '            <CustomDeviceName>HYDRA</CustomDeviceName>',
    '            <IsMaximized>true</IsMaximized>',
    '            <IsSelected>false</IsSelected>',
    param("IsActive", "1.0"),
    '            <VisiblePages>1</VisiblePages>',
    param("InputValue", "0.0", "Mixer and Device") }
  for i = 1, 9 do
    local eff, par = "-1", "-1"
    if i == 1 then eff, par = "3", "1" end        -- output 1 -> macro 1, the table sweep
    hydra[#hydra + 1] = param("Out" .. i .. "DestTrack", "-1")
    hydra[#hydra + 1] = param("Out" .. i .. "DestEffect", eff)
    hydra[#hydra + 1] = param("Out" .. i .. "DestParameter", par)
    hydra[#hydra + 1] = param("Out" .. i .. "Min", "0.0")
    hydra[#hydra + 1] = param("Out" .. i .. "Max", "1.0")
    hydra[#hydra + 1] = '            <Out' .. i .. 'Scaling>Linear</Out' .. i .. 'Scaling>'
  end
  hydra[#hydra + 1] = '          </HydraDevice>'

  local macros = { '          <InstrumentMacroDevice type="InstrumentMacroDevice">',
    '            <SelectedPresetName>Init</SelectedPresetName>',
    '            <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>',
    '            <SelectedPresetIsModified>true</SelectedPresetIsModified>',
    '            <CustomDeviceName>INSTR MACRO</CustomDeviceName>',
    '            <IsMaximized>true</IsMaximized>',
    '            <IsSelected>false</IsSelected>',
    param("IsActive", "1.0") }
  for i = 0, 7 do
    macros[#macros + 1] = param("ParameterValue" .. i, "0.5")
  end
  macros[#macros + 1] = param("PitchbendValue", "0.5")
  macros[#macros + 1] = param("ModulationValue", "0.0")
  macros[#macros + 1] = param("ChannelPressureValue", "0.0")
  macros[#macros + 1] = param("PhraseProgrammValue", "1.0")
  macros[#macros + 1] = '            <LinkedInstrument>-1</LinkedInstrument>'
  macros[#macros + 1] = '          </InstrumentMacroDevice>'

  local kt = { '          <KeyTrackingDevice type="KeyTrackingDevice">',
    '            <SelectedPresetName>Init</SelectedPresetName>',
    '            <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>',
    '            <SelectedPresetIsModified>true</SelectedPresetIsModified>',
    '            <CustomDeviceName>KT -&gt; RESET</CustomDeviceName>',
    '            <IsMaximized>true</IsMaximized>',
    '            <IsSelected>false</IsSelected>',
    param("IsActive", "1.0"),
    '            <SrcInstrument>-1</SrcInstrument>',
    '            <DestScaling>Linear</DestScaling>',
    '            <KeyTrackingMode>Clamp</KeyTrackingMode>',
    '            <KeyTrackingMin>36</KeyTrackingMin>',
    '            <KeyTrackingMax>72</KeyTrackingMax>',
    param("DestTrack", "-1"),
    param("DestEffect", "1"),      -- the SWEEP LFO
    param("DestParameter", "8"), -- its Reset
    param("DestMin", "0.0"),
    param("DestMax", "1.0"),
    '          </KeyTrackingDevice>' }

  return table.concat({ lfo, table.concat(hydra, "\n"), table.concat(macros, "\n"),
                        table.concat(kt, "\n") }, "\n")
end

-- the whole instrument --------------------------------------------------------------

-- opts = {
--   name            instrument name
--   frame_count     N (2..12)
--   frame_length    samples per frame
--   sample_rate     source rate
--   tuning          table from WTLib.tuning
--   with_sweep      boolean
--   frame_names     optional table of sample names
-- }
function WTLib.instrument_xml(opts)
  local n = opts.frame_count
  local len = opts.frame_length
  local t = opts.tuning
  local sum_index = n + 1

  local samples = {}
  for i = 1, n do
    local sname = (opts.frame_names and opts.frame_names[i]) or string.format("frame %02d", i)
    samples[#samples + 1] = table.concat({
      '        <Sample>',
      '          <SelectedPresetName>Init</SelectedPresetName>',
      '          <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>',
      '          <SelectedPresetIsModified>true</SelectedPresetIsModified>',
      '          <Name>' .. WTLib.esc(sname) .. '</Name>',
      '          <Volume>1.0</Volume>',
      '          <Panning>0.5</Panning>',
      '          <Transpose>0</Transpose>',
      '          <Finetune>' .. t.finetune .. '</Finetune>',
      '          <BeatSyncIsActive>false</BeatSyncIsActive>',
      '          <BeatSyncMode>Repitch</BeatSyncMode>',
      '          <BeatSyncLines>16</BeatSyncLines>',
      '          <OneShotTrigger>false</OneShotTrigger>',
      '          <NewNoteAction>NoteOff</NewNoteAction>',
      '          <Oversample>true</Oversample>',
      '          <InterpolationMode>Cubic</InterpolationMode>',
      '          <AutoSeek>false</AutoSeek>',
      '          <AutoFade>false</AutoFade>',
      '          <LoopMode>Forward</LoopMode>',
      '          <LoopRelease>false</LoopRelease>',
      '          <LoopStart>0</LoopStart>',
      '          <LoopEnd>' .. len .. '</LoopEnd>',
      '          <SingleSliceTriggerEnabled>true</SingleSliceTriggerEnabled>',
      '          <IsAlias>false</IsAlias>',
      '          <MuteGroupIndex>-1</MuteGroupIndex>',
      '          <ModulationSetIndex>0</ModulationSetIndex>',
      '          <DeviceChainIndex>' .. i .. '</DeviceChainIndex>',
      '          <Mapping>',
      '            <Layer>Note-On Layer</Layer>',
      '            <BaseNote>' .. t.base_note .. '</BaseNote>',
      '            <NoteStart>0</NoteStart>',
      '            <NoteEnd>119</NoteEnd>',
      '            <MapKeyToPitch>true</MapKeyToPitch>',
      '            <VelocityStart>0</VelocityStart>',
      '            <VelocityEnd>127</VelocityEnd>',
      '            <MapVelocityToVolume>true</MapVelocityToVolume>',
      '          </Mapping>',
      '          <DisplayStart>0</DisplayStart>',
      '          <DisplayLength>' .. len .. '</DisplayLength>',
      '          <SelectionRangeStart>-1</SelectionRangeStart>',
      '          <SelectionRangeEnd>-1</SelectionRangeEnd>',
      '          <SelectedChannel>L+R</SelectedChannel>',
      '          <VZoomFactor>1.0</VZoomFactor>',
      '        </Sample>',
    }, "\n")
  end

  local chains = {}
  -- GATES
  local gate_devs = { WTLib.mixer_xml("GATES", "1.0") }
  for i = 1, n do
    gate_devs[#gate_devs + 1] = WTLib.gate_lfo_xml(i, n, opts.spacing or 2, i, "1", "0.0")
  end
  chains[#chains + 1] = { name = "GATES", devices = table.concat(gate_devs, "\n") }
  -- FRAME chains
  for i = 1, n do
    chains[#chains + 1] = {
      name = string.format("FRAME %02d", i),
      devices = WTLib.mixer_xml("Mixer", "0.0") .. "\n" ..
                WTLib.send_xml(sum_index),
    }
  end
  -- SUM
  local sum_devs = WTLib.mixer_xml("Mixer", "1.0")
  if opts.with_sweep then sum_devs = sum_devs .. "\n" .. WTLib.sweep_rig_xml() end
  chains[#chains + 1] = { name = "SUM", devices = sum_devs }

  local chain_xml = {}
  for _, c in ipairs(chains) do
    chain_xml[#chain_xml + 1] = table.concat({
      '      <DeviceChain>',
      '        <SelectedPresetName>Init</SelectedPresetName>',
      '        <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>',
      '        <SelectedPresetIsModified>true</SelectedPresetIsModified>',
      '        <Devices>',
      c.devices,
      '        </Devices>',
      '        <Name>' .. WTLib.esc(c.name) .. '</Name>',
      '        <RoutingIndex>-1</RoutingIndex>',
      '      </DeviceChain>',
    }, "\n")
  end

  local mappings = {}
  for i = 1, n do
    mappings[#mappings + 1] = table.concat({
      '          <Mapping>',
      '            <DestChainType>SampleDSP</DestChainType>',
      '            <DestChainIndex>0</DestChainIndex>',
      '            <DestDeviceIndex>' .. i .. '</DestDeviceIndex>',
      '            <DestParameterIndex>8</DestParameterIndex>',
      '            <Min>0.0</Min>',
      '            <Max>1.0</Max>',
      '            <Scaling>Linear</Scaling>',
      '          </Mapping>',
    }, "\n")
  end

  return table.concat({
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<RenoiseInstrument doc_version="34">',
    '  <SelectedPresetName>Init</SelectedPresetName>',
    '  <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>',
    '  <SelectedPresetIsModified>true</SelectedPresetIsModified>',
    '  <Name>' .. WTLib.esc(opts.name) .. '</Name>',
    '  <CopyIntoNewSampleNameCounter>0</CopyIntoNewSampleNameCounter>',
    '  <CopyIntoNewInstrumentNameCounter>0</CopyIntoNewInstrumentNameCounter>',
    '  <GlobalProperties>',
    '    <Macro0>',
    '      <Value>0.0</Value>',
    '      <Visualization>Device only</Visualization>',
    '      <Name>WT Position</Name>',
    '      <Mappings>',
    table.concat(mappings, "\n"),
    '      </Mappings>',
    '    </Macro0>',
    '    <Macro1><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 2</Name></Macro1>',
    '    <Macro2><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 3</Name></Macro2>',
    '    <Macro3><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 4</Name></Macro3>',
    '    <Macro4><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 5</Name></Macro4>',
    '    <Macro5><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 6</Name></Macro5>',
    '    <Macro6><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 7</Name></Macro6>',
    '    <Macro7><Value>50</Value><Visualization>Device only</Visualization><Name>Macro 8</Name></Macro7>',
    '    <PitchbendMacro><Value>50</Value><Visualization>Device only</Visualization><Name>Pitchbend</Name></PitchbendMacro>',
    '    <ModulationWheelMacro><Value>0.0</Value><Visualization>Device only</Visualization><Name>Modulation</Name></ModulationWheelMacro>',
    '    <ChannelPressureMacro><Value>0.0</Value><Visualization>Device only</Visualization><Name>Channel Pressure</Name></ChannelPressureMacro>',
    '    <MacrosVisible>true</MacrosVisible>',
    '    <Volume>1.0</Volume>',
    '    <Transpose>0</Transpose>',
    '    <MtsEspTuning>false</MtsEspTuning>',
    '    <Scale>None</Scale>',
    '    <ScaleKey>C</ScaleKey>',
    '    <Quantize>None</Quantize>',
    '    <Monophonic>false</Monophonic>',
    '    <MonophonicGlide>0</MonophonicGlide>',
    '    <ShowCommentsAfterLoading>false</ShowCommentsAfterLoading>',
    '    <BeatsPerMin>140</BeatsPerMin>',
    '  </GlobalProperties>',
    '  <MidiInputProperties>',
    '    <Channel>-1</Channel>',
    '    <NoteRangeStart>0</NoteRangeStart>',
    '    <NoteRangeEnd>119</NoteRangeEnd>',
    '    <AssignedTrack>-1</AssignedTrack>',
    '  </MidiInputProperties>',
    '  <PhraseGenerator>',
    '    <PlaybackSync>false</PlaybackSync>',
    '    <PlaybackMode>Selective</PlaybackMode>',
    '    <SelectedPhraseIndex>-1</SelectedPhraseIndex>',
    '    <PhraseMap><SelectedMappingIndex>-1</SelectedMappingIndex></PhraseMap>',
    '  </PhraseGenerator>',
    '  <SampleGenerator>',
    '    <Samples>',
    table.concat(samples, "\n"),
    '    </Samples>',
    '    <SelectedSampleIndex>0</SelectedSampleIndex>',
    '    <ModulationSets>',
    '      <ModulationSet>',
    '        <SelectedPresetName>Init</SelectedPresetName>',
    '        <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>',
    '        <SelectedPresetIsModified>false</SelectedPresetIsModified>',
    '        <Devices>',
    '          <SampleMixerModulationDevice type="SampleMixerModulationDevice">',
    '            <IsActive><Value>1.0</Value><Visualization>Device only</Visualization></IsActive>',
    '            <Volume><Value>1.0</Value><Visualization>Device only</Visualization></Volume>',
    '            <Panning><Value>0.0</Value><Visualization>Device only</Visualization></Panning>',
    '            <Pitch><Value>0.0</Value><Visualization>Device only</Visualization></Pitch>',
    '            <PitchModulationRange>12</PitchModulationRange>',
    '            <Cutoff><Value>63.5</Value><Visualization>Device only</Visualization></Cutoff>',
    '            <Resonance><Value>63.5</Value><Visualization>Device only</Visualization></Resonance>',
    '            <Drive><Value>0.0</Value><Visualization>Device only</Visualization></Drive>',
    '          </SampleMixerModulationDevice>',
    '        </Devices>',
    '        <Name>Set 01</Name>',
    '        <FilterType>0</FilterType>',
    '        <FilterBankVersion>3</FilterBankVersion>',
    '      </ModulationSet>',
    '    </ModulationSets>',
    '    <SelectedModulationSetIndex>0</SelectedModulationSetIndex>',
    '    <DeviceChains>',
    table.concat(chain_xml, "\n"),
    '    </DeviceChains>',
    '    <SelectedDeviceChainIndex>0</SelectedDeviceChainIndex>',
    '    <KeyzoneOverlappingMode>Play All</KeyzoneOverlappingMode>',
    '    <SplitMap>',
    '      <SelectedPresetName>Init</SelectedPresetName>',
    '      <SelectedPresetLibrary>Bundled Content</SelectedPresetLibrary>',
    '      <SelectedPresetIsModified>false</SelectedPresetIsModified>',
    '    </SplitMap>',
    '  </SampleGenerator>',
    '  <PluginGenerator>',
    '    <Channel>0</Channel><Transpose>0</Transpose><Volume>1.0</Volume>',
    '    <OutputRoutings/>',
    '    <MidiOutputRoutingIndex>-1</MidiOutputRoutingIndex>',
    '    <AutoSuspend>true</AutoSuspend>',
    '    <AliasInstrumentIndex>-1</AliasInstrumentIndex>',
    '    <AliasFxIndices>-1,-1</AliasFxIndices>',
    '  </PluginGenerator>',
    '  <MidiGenerator>',
    '    <Channel>0</Channel><InstrumentType>LineIn Ret</InstrumentType><Delay>0</Delay>',
    '    <Program>-1</Program><Bank>-1</Bank><BankOrder>MSB, LSB</BankOrder>',
    '    <Transpose>0</Transpose><Length>8000</Length>',
    '  </MidiGenerator>',
    '  <ActiveGeneratorTab>Samples</ActiveGeneratorTab>',
    '</RenoiseInstrument>',
    '',
  }, "\n")
end

return WTLib
