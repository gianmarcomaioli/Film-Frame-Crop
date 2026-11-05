--[[
Film Frame Crop - automatically crops film scans to the exposed frame.

Menu items appear under File > Plug-in Extras (available in every module).
]]

return {
    LrSdkVersion = 10.0,
    LrSdkMinimumVersion = 6.0,

    LrToolkitIdentifier = "com.filmframecrop.lightroom",
    LrPluginName = "Film Frame Crop",

    LrExportMenuItems = {
        {
            title = "Film Frame Crop: Crop Selected Scans",
            file = "CropSelected.lua",
            enabledWhen = "photosSelected",
        },
        {
            title = "Film Frame Crop: Settings...",
            file = "SettingsDialog.lua",
        },
    },

    LrPluginInfoProvider = "PluginInfo.lua",

    VERSION = { major = 1, minor = 2, revision = 0 },
}
