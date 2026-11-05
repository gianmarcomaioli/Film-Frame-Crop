# Film Frame Crop by @GianmarcoMaioli

A Lightroom Classic plugin that crops film scans to the exposed frame. It
straightens small tilts and trims away the film base, sprocket holes, holder
and neighbouring frames. The crop is an ordinary Lightroom crop:
visible in Develop, adjustable by hand, and undoable in History.
It works on colour negatives, black-and-white negatives and slides.

## Requirements
- Lightroom Classic
- Python 3.8 or later with NumPy and OpenCV:
      py -m pip install numpy opencv-python        (Windows)
      python3 -m pip install numpy opencv-python   (Mac)

## Installing

1. Unzip, and put the `FilmFrameCrop.lrplugin` folder somewhere permanent.
2. In Lightroom: File > Plug-in Manager > Add, and choose that folder.
3. Open File > Plug-in Extras > Film Frame Crop: Settings... and click **Test**.

## Using it
All commands are under **File > Plug-in Extras** and work in any module.

- **Crop Selected Scans** crops each selected photo to its exposed frame.
If a photo can't be cropped, it keeps its previous crop and is listed at the end.

## The Process
For each photo, cropping works in three stages:

1. It briefly clears the crop
(history step "Film Frame Crop: prepare").
2. It renders a small uncropped preview and finds the frame, its edges and its tilt.
3. It applies the new crop, in one step ("Film Frame Crop").

**To undo**, click the history step just before "Film Frame Crop: prepare",
or press Ctrl+Z | Cmd+Z twice. You can also adjust the crop by hand in Develop.

I recommend cropping before converting the negative, so the conversion only
sees the image and not the film base or holder.

## Settings

| Setting | What it does |
|---------|--------------|
| Film type | Negative (default) or Slide. Auto-detect exists but can misjudge scans where a dark holder surrounds the film. |
| Straighten up to | The largest tilt that will be corrected, in degrees. 0 never rotates. |
| Inset | Extra trim, as a percentage of the frame's short side, to remove the soft edge. |
| Aspect ratio | Free keeps the frame as detected. "Snap" uses the nearest standard ratio if it is within 3%. Or force a ratio. |
| Sensitivity | Raise it if crops are too tight. Lower it if film base is left showing. |
| Keep debug images | Saves an overlay of what was detected on each scan and opens the folder afterwards. |
| Reverse straighten direction | A safety valve. Use it only if straightened crops come out tilted the wrong way. |

## How it works

1. **Preview.** The crop is cleared and a 1600-pixel uncropped preview is
rendered, so the whole scan, holder included, can be seen.
2. **Frame.** The film base colour is measured from the edges of the scan: the
clear orange or grey base on negatives, the dark base on slides. Every pixel
that differs from the base, and is neither backlight nor holder, is marked as
image, and the largest such region is taken as the frame.
3. **Tilt.** The angle is found by rotating the frame slightly in both
directions and keeping the angle at which its edges are sharpest.
4. **Edges.** In the straightened image, each edge is located precisely by
walking inward from the holder until the brightness steps from base to image.
5. **Lightroom crop.** The result is converted to Lightroom's own crop values,
two opposite corners in the original, unrotated image plus a clockwise angle,
so camera rotation and mirroring are handled.

## Limitations

- It expects one frame per scan. With a strip of several frames, it crops to the largest.
- If a negative's whole edge is deep shadow, that is the same density as the
base, so the crop can come in slightly on that side.
- Scans with no film base visible at all are cropped to the image edge, minus the inset.
- Now and then a crop leaves a sliver of the frame edge out. Adjust it by hand,
or raise Sensitivity.

## Credits

Film Frame Crop was created by Gianmarco Maioli
find more at Youtube @gianmarcomaioli or Instagram @gianmarcomaioli

Copyright (c) 2026 Gianmarco Maioli
released under GPL-3.0 licence
Film Frame Crop is free and open-source software.
You may use, copy, modify and share it, provided the implementation
of its code remains free and sourceable.
