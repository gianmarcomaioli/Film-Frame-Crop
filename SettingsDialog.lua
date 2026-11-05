-- File > Plug-in Extras > Film Frame Crop: Settings...

local LrDialogs = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrView = import "LrView"

local SettingsUI = require "SettingsUI"

LrFunctionContext.postAsyncTaskWithContext("FilmFrameCropSettings", function(context)
    LrDialogs.attachErrorDialogToFunctionContext(context)
    local f = LrView.osFactory()
    LrDialogs.presentModalDialog {
        title = "Film Frame Crop Settings",
        contents = SettingsUI.build(f),
        actionVerb = "Done",
        cancelVerb = "< exclude >",
    }
end)
