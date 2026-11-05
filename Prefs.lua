-- Plugin preferences with defaults.

local LrPrefs = import "LrPrefs"

local prefs = LrPrefs.prefsForPlugin()

local defaults = {
    pythonCommand = "",     -- empty = find automatically
    film = "negative",      -- auto | negative | positive
    maxAngle = 5,           -- largest tilt to straighten, degrees (0 = never)
    inset = 1.0,            -- extra trim, percent of the frame's short side
    aspect = "free",        -- free | auto | 3:2 | 4:3 | 1:1 | 7:6 | 5:4 | 16:9 | 65:24
    sensitivity = 1.0,      -- higher = treats fainter detail as image
    flipAngle = false,      -- troubleshooting: reverse the straighten direction
    keepDebug = false,      -- keep renders and overlay images for inspection
}

for k, v in pairs(defaults) do
    if prefs[k] == nil then
        prefs[k] = v
    end
end

return prefs
