-- Panel shown in File > Plug-in Manager.

local SettingsUI = require "SettingsUI"

return {
    sectionsForTopOfDialog = function(f, _)
        return {
            {
                title = "Film Frame Crop",
                synopsis = "Settings",
                SettingsUI.build(f),
            },
        }
    end,
}
