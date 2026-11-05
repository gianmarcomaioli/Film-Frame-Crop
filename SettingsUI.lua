-- Settings controls, shared by the Settings dialog and the Plug-in Manager panel.

local LrDialogs = import "LrDialogs"
local LrTasks = import "LrTasks"
local LrView = import "LrView"

local prefs = require "Prefs"
local Engine = require "Engine"

local bind = LrView.bind
local share = LrView.share

local SettingsUI = {}

local function label(f, text)
    return f:static_text { title = text, alignment = "right", width = share "ffc_label" }
end

function SettingsUI.build(f)
    return f:column {
        bind_to_object = prefs,
        spacing = f:control_spacing(),

        f:row {
            label(f, "Film type:"),
            f:popup_menu {
                value = bind "film",
                items = {
                    { title = "Auto-detect", value = "auto" },
                    { title = "Negative (colour or black & white)", value = "negative" },
                    { title = "Slide / positive", value = "positive" },
                },
            },
        },

        f:row {
            label(f, "Straighten up to:"),
            f:slider { value = bind "maxAngle", min = 0, max = 15, width = 160 },
            f:edit_field { value = bind "maxAngle", min = 0, max = 45, precision = 1, width_in_digits = 4 },
            f:static_text { title = "degrees (0 = never straighten)" },
        },

        f:row {
            label(f, "Inset:"),
            f:slider { value = bind "inset", min = 0, max = 5, width = 160 },
            f:edit_field { value = bind "inset", min = 0, max = 20, precision = 1, width_in_digits = 4 },
            f:static_text { title = "% of the short side, trims soft frame edges" },
        },

        f:row {
            label(f, "Aspect ratio:"),
            f:popup_menu {
                value = bind "aspect",
                items = {
                    { title = "Free (as detected)", value = "free" },
                    { title = "Snap to nearest standard ratio", value = "auto" },
                    { title = "3:2 (35mm, 6x9)", value = "3:2" },
                    { title = "4:3 (6x4.5, half frame)", value = "4:3" },
                    { title = "1:1 (6x6)", value = "1:1" },
                    { title = "7:6 (6x7)", value = "7:6" },
                    { title = "5:4 (4x5, 6x7.5)", value = "5:4" },
                    { title = "16:9", value = "16:9" },
                    { title = "65:24 (XPan)", value = "65:24" },
                },
            },
        },

        f:row {
            label(f, "Sensitivity:"),
            f:slider { value = bind "sensitivity", min = 0.5, max = 2, width = 160 },
            f:edit_field { value = bind "sensitivity", min = 0.25, max = 4, precision = 2, width_in_digits = 4 },
            f:static_text { title = "raise if crops are too tight, lower if film base is left in" },
        },

        f:separator { fill_horizontal = 1 },

        f:row {
            label(f, "Python command:"),
            f:edit_field { value = bind "pythonCommand", width_in_chars = 34, immediate = true },
            f:push_button {
                title = "Test",
                action = function()
                    LrTasks.startAsyncTask(function()
                        local cmd, text = Engine.findPython()
                        if cmd then
                            LrDialogs.message("Python is working", "Using: " .. cmd .. "\n\n" .. text, "info")
                        else
                            LrDialogs.message("Python problem", text, "critical")
                        end
                    end)
                end,
            },
        },
        f:row {
            label(f, ""),
            f:static_text {
                title = "Leave empty to find Python automatically. Needs numpy and opencv-python.",
                size = "small",
            },
        },

        f:row {
            label(f, ""),
            f:checkbox { title = "Keep debug images (shows what was detected on each scan)", value = bind "keepDebug" },
        },
        f:row {
            label(f, ""),
            f:checkbox {
                title = "Reverse straighten direction (only if crops come out tilted the wrong way)",
                value = bind "flipAngle",
            },
        },
    }
end

return SettingsUI
