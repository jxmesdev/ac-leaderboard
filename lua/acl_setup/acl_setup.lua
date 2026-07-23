-- BL Setup Capture -- companion app for the Bradford Leaderboard.
--
-- Writes the CURRENTLY RUNNING car setup (via CSP's ac.stringifyCurrentSetup)
-- to apps/python/ac_leaderboard/current_setup.ini whenever it changes, so
-- recorded laps store the EXACT setup they were driven on -- including
-- unsaved pit-menu tweaks. The python app deletes the file at session start
-- and reads it when a lap records; if this app is disabled or CSP is too
-- old, the leaderboard falls back to the most-recently-saved setup file.
--
-- Everything is wrapped in pcall: worst case this app writes nothing.

local TARGET = ac.getFolder(ac.FolderID.ACAppsPython) .. '/ac_leaderboard/current_setup.ini'
local last = nil
local acc = 0
local status = 'waiting for setup data…'

local function capture(dt)
  acc = acc + dt
  if acc < 2 then return end
  acc = 0
  if ac.stringifyCurrentSetup == nil then
    status = 'CSP too old: update CSP for live setup capture'
    return
  end
  local ok, cs = pcall(ac.stringifyCurrentSetup)
  if not ok or type(cs) ~= 'string' or #cs < 10 then
    status = 'no setup data yet'
    return
  end
  if cs ~= last then
    local ok2 = pcall(io.save, TARGET, cs)
    if ok2 then
      last = cs
      status = 'live setup captured'
    else
      status = 'could not write ' .. TARGET
    end
  end
end

function script.update(dt)
  capture(dt)
end

function script.windowMain(dt)
  ui.text('BL Setup Capture')
  ui.text('Status: ' .. status)
  ui.textWrapped('Keeps the leaderboard fed with the exact setup you are running. Safe to leave this window closed.')
end
