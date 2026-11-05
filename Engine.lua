-- Film Frame Crop: rendering, calling the detector, applying crops.

local LrApplication = import "LrApplication"
local LrDialogs = import "LrDialogs"
local LrExportSession = import "LrExportSession"
local LrFileUtils = import "LrFileUtils"
local LrFunctionContext = import "LrFunctionContext"
local LrLogger = import "LrLogger"
local LrPathUtils = import "LrPathUtils"
local LrProgressScope = import "LrProgressScope"
local LrShell = import "LrShell"
local LrTasks = import "LrTasks"

local prefs = require "Prefs"

local logger = LrLogger("FilmFrameCrop")
logger:enable("logfile")

local Engine = {}

local RENDER_LONG_EDGE = 1600

local PYTHON_CANDIDATES_MAC = {
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
    "/usr/bin/python3",
}
local PYTHON_CANDIDATES_WIN = { "py -3", "python", "python3" }

-- ------------------------------------------------------------------------
-- Shell helpers
-- ------------------------------------------------------------------------

local function quote(s)
    return '"' .. s .. '"'
end

local function shell(cmd)
    -- cmd.exe /c strips one pair of outer quotes, so wrap the whole line.
    if WIN_ENV then
        return '"' .. cmd .. '"'
    end
    return cmd
end

local function pythonPrefix(cmd)
    -- A path to an executable (which may contain spaces) is quoted;
    -- launcher forms such as "py -3" are passed through unchanged.
    if LrFileUtils.exists(cmd) then
        return quote(cmd)
    end
    return cmd
end

local function readText(path)
    local f = io.open(path, "r")
    if not f then
        return nil
    end
    local s = f:read("*a")
    f:close()
    return s
end

local function writeText(path, text)
    local f = assert(io.open(path, "w"))
    f:write(text)
    f:close()
end

local function scriptPath()
    return LrPathUtils.child(_PLUGIN.path, "detect_crop.py")
end

local function tempFile(name)
    return LrPathUtils.child(LrPathUtils.getStandardFilePath("temp"), name)
end

-- ------------------------------------------------------------------------
-- Python discovery
-- ------------------------------------------------------------------------

local function tryPython(cmd)
    local out = tempFile("FilmFrameCrop_check_" .. tostring(os.time()) .. ".txt")
    local line = pythonPrefix(cmd) .. " " .. quote(scriptPath()) .. " --check > " .. quote(out) .. " 2>&1"
    local status = LrTasks.execute(shell(line))
    local text = readText(out) or ""
    LrFileUtils.delete(out)
    local ok = (status == 0) and (text:find("^ok") ~= nil)
    return ok, text
end

-- Returns the python command to use, or nil plus an explanation.
function Engine.findPython()
    local configured = prefs.pythonCommand or ""
    if configured ~= "" then
        local ok, text = tryPython(configured)
        if ok then
            return configured, text
        end
        return nil, "The Python command in the settings did not work:\n" .. configured ..
            "\n\nOutput:\n" .. text
    end
    local list = WIN_ENV and PYTHON_CANDIDATES_WIN or PYTHON_CANDIDATES_MAC
    local last = ""
    for _, cmd in ipairs(list) do
        local ok, text = tryPython(cmd)
        if ok then
            prefs.pythonCommand = cmd
            return cmd, text
        end
        last = text
    end
    return nil, "Could not find Python 3 with OpenCV and NumPy installed.\n\n" ..
        "Install them with:\n    python3 -m pip install numpy opencv-python\n\n" ..
        "then, if needed, enter the full path to python3 in Film Frame Crop: Settings.\n\n" ..
        "Last output:\n" .. last
end

-- ------------------------------------------------------------------------
-- Crop settings helpers
-- ------------------------------------------------------------------------

local CROP_KEYS = { "CropLeft", "CropTop", "CropRight", "CropBottom", "CropAngle" }
local NO_CROP = { CropLeft = 0, CropTop = 0, CropRight = 1, CropBottom = 1, CropAngle = 0 }

local function currentCrop(dev)
    local c = {}
    for _, k in ipairs(CROP_KEYS) do
        c[k] = dev[k] or NO_CROP[k]
    end
    return c
end

local function orientationOf(dev)
    local o = dev.orientation or dev.Orientation
    if type(o) == "string" and #o == 2 then
        return o
    end
    return "AB"
end

local function splitTabs(line)
    local out = {}
    for field in (line .. "\t"):gmatch("([^\t]*)\t") do
        out[#out + 1] = field
    end
    return out
end

local function restoreAll(catalog, items)
    catalog:withWriteAccessDo("Film Frame Crop: restore", function()
        for _, it in ipairs(items) do
            it.photo:applyDevelopSettings(it.original)
        end
    end, { timeout = 60 })
end

-- ------------------------------------------------------------------------
-- Main command
-- ------------------------------------------------------------------------

local function cropPhotos(context)
    LrDialogs.attachErrorDialogToFunctionContext(context)

    local catalog = LrApplication.activeCatalog()
    local selection = catalog:getTargetPhotos()
    if #selection == 0 then
        LrDialogs.message("Film Frame Crop", "Select one or more film scans first.", "info")
        return
    end

    local python, why = Engine.findPython()
    if not python then
        LrDialogs.message("Film Frame Crop: Python not found", why, "critical")
        return
    end

    local items, byId = {}, {}
    for _, photo in ipairs(selection) do
        if photo:getRawMetadata("fileFormat") ~= "VIDEO" then
            local dev = photo:getDevelopSettings()
            local it = {
                photo = photo,
                id = tostring(photo.localIdentifier),
                name = photo:getFormattedMetadata("fileName") or "?",
                original = currentCrop(dev),
                orientation = orientationOf(dev),
            }
            items[#items + 1] = it
            byId[it.id] = it
        end
    end
    if #items == 0 then
        LrDialogs.message("Film Frame Crop", "No still photos in the selection.", "info")
        return
    end

    local progress = LrProgressScope {
        title = "Film Frame Crop",
        functionContext = context,
    }

    local workDir = tempFile("FilmFrameCrop_" .. tostring(os.time()))
    LrFileUtils.createAllDirectories(workDir)
    local debugDir = nil
    if prefs.keepDebug then
        debugDir = LrPathUtils.child(workDir, "debug")
        LrFileUtils.createAllDirectories(debugDir)
    end

    -- 1. Remove existing crops so the render shows the whole scan.
    progress:setCaption("Preparing...")
    catalog:withWriteAccessDo("Film Frame Crop: prepare", function()
        for _, it in ipairs(items) do
            it.photo:applyDevelopSettings(NO_CROP)
        end
    end, { timeout = 60 })

    local ok, err = LrTasks.pcall(function()
        -- 2. Render small uncropped JPEGs.
        progress:setCaption("Rendering previews...")
        local photos = {}
        for _, it in ipairs(items) do
            photos[#photos + 1] = it.photo
        end
        local session = LrExportSession {
            photosToExport = photos,
            exportSettings = {
                LR_format = "JPEG",
                LR_jpeg_quality = 0.85,
                LR_export_colorSpace = "sRGB",
                LR_export_bitDepth = 8,
                LR_size_doConstrain = true,
                LR_size_resizeType = "longEdge",
                LR_size_maxWidth = RENDER_LONG_EDGE,
                LR_size_maxHeight = RENDER_LONG_EDGE,
                LR_size_units = "pixels",
                LR_size_doNotEnlarge = true,
                LR_outputSharpeningOn = false,
                LR_export_destinationType = "specificFolder",
                LR_export_destinationPathPrefix = workDir,
                LR_export_useSubfolder = false,
                LR_collisionHandling = "rename",
                LR_minimizeEmbeddedMetadata = true,
                LR_removeLocationMetadata = true,
                LR_useWatermark = false,
                LR_reimportExportedPhoto = false,
                LR_includeVideoFiles = false,
            },
        }
        local n = 0
        for _, rendition in session:renditions { stopIfCanceled = true } do
            local rendered, pathOrMsg = rendition:waitForRender()
            local it = byId[tostring(rendition.photo.localIdentifier)]
            if it then
                if rendered then
                    it.render = pathOrMsg
                else
                    it.error = "render failed: " .. tostring(pathOrMsg)
                end
            end
            n = n + 1
            progress:setPortionComplete(n * 0.6, #items)
            if progress:isCanceled() then
                error("cancelled")
            end
        end

        -- 3. Detect frames.
        progress:setCaption("Detecting frames...")
        local lines = {}
        for _, it in ipairs(items) do
            if it.render then
                lines[#lines + 1] = it.id .. "\t" .. it.render .. "\t" .. it.orientation
            end
        end
        if #lines == 0 then
            return
        end
        local jobPath = LrPathUtils.child(workDir, "job.txt")
        local outPath = LrPathUtils.child(workDir, "result.txt")
        local logPath = LrPathUtils.child(workDir, "python_log.txt")
        writeText(jobPath, table.concat(lines, "\n") .. "\n")

        local args = {
            pythonPrefix(python), quote(scriptPath()),
            "--job", quote(jobPath), "--out", quote(outPath),
            "--film", prefs.film or "auto",
            "--max-angle", string.format("%.2f", tonumber(prefs.maxAngle) or 5),
            "--inset", string.format("%.2f", tonumber(prefs.inset) or 1),
            "--aspect", quote(prefs.aspect or "free"),
            "--sensitivity", string.format("%.2f", tonumber(prefs.sensitivity) or 1),
        }
        if prefs.flipAngle then
            args[#args + 1] = "--flip-angle"
        end
        if debugDir then
            args[#args + 1] = "--debug-dir"
            args[#args + 1] = quote(debugDir)
            args[#args + 1] = "--verbose"
        end
        local cmd = table.concat(args, " ") .. " > " .. quote(logPath) .. " 2>&1"
        logger:info("running: " .. cmd)
        local status = LrTasks.execute(shell(cmd))
        progress:setPortionComplete(0.9, 1)

        local text = readText(outPath)
        if status ~= 0 or not text then
            error("The detector failed (exit code " .. tostring(status) .. ").\n\n" ..
                (readText(logPath) or ""))
        end
        for line in text:gmatch("[^\r\n]+") do
            local f = splitTabs(line)
            local it = byId[f[1]]
            if it then
                if f[2] == "ok" then
                    it.result = {
                        CropLeft = tonumber(f[3]),
                        CropTop = tonumber(f[4]),
                        CropRight = tonumber(f[5]),
                        CropBottom = tonumber(f[6]),
                        CropAngle = tonumber(f[7]),
                    }
                else
                    it.error = f[3] or "unknown error"
                end
            end
        end
    end)

    if not ok then
        restoreAll(catalog, items)
        progress:done()
        if tostring(err):find("cancelled") then
            return
        end
        LrDialogs.message("Film Frame Crop", "Nothing was changed.\n\n" .. tostring(err), "critical")
        return
    end

    -- 4. Apply the new crops; anything that failed gets its old crop back.
    progress:setCaption("Applying crops...")
    local done, failed = 0, {}
    catalog:withWriteAccessDo("Film Frame Crop", function()
        for _, it in ipairs(items) do
            if it.result then
                it.photo:applyDevelopSettings(it.result)
                done = done + 1
            else
                it.photo:applyDevelopSettings(it.original)
                failed[#failed + 1] = it.name .. ": " .. (it.error or "not processed")
            end
        end
    end, { timeout = 60 })
    progress:done()

    if debugDir then
        LrShell.revealInShell(debugDir)
    else
        LrFileUtils.delete(workDir)
    end

    if #failed > 0 then
        local shown = {}
        for i = 1, math.min(#failed, 15) do
            shown[i] = failed[i]
        end
        if #failed > 15 then
            shown[#shown + 1] = "... and " .. (#failed - 15) .. " more"
        end
        LrDialogs.message("Film Frame Crop",
            string.format("Cropped %d of %d photos. These were left as they were:\n\n%s",
                done, #items, table.concat(shown, "\n")), "warning")
    elseif #items > 1 then
        LrDialogs.showBezel(string.format("Film Frame Crop: cropped %d photos", done))
    end
end

function Engine.run()
    LrFunctionContext.postAsyncTaskWithContext("FilmFrameCrop", cropPhotos)
end

return Engine
