# Changelog

All notable changes to Film Frame Crop.

## 1.4.0 (2026-11-20)

### Added
- **Crop Selected Like Active Photo** (File > Plug-in Extras). Crop one frame
  of a roll by hand, select it with the others (clicking it last, so it is the
  active photo), and the rest are cropped to match: the same size, in the same
  position relative to each frame.
  - When a frame is detected at a different size from the reference, the crop
    is anchored on the edge the plugin is sure of (a clear step, or a gap
    between frames), so one misread edge no longer spoils the crop.
  - Leftover room is shared in the same proportion as in your crop.
  - A crop never reaches past the frame; on a smaller frame it is trimmed to fit.
  - Frames rotated 90 degrees relative to the reference get the crop turned to
    match, centred on the frame.
  - The hand-cropped photo keeps its crop.

### Unchanged
- Automatic cropping (Crop Selected Scans) gives the same results as 1.3.

## 1.3.0 (2026-11-20)

Better crops when the film strip runs off the edge of the scan, and when the
edge of the film shows inside the holder.

### Fixed
- **Gaps between frames are no longer included.** When the strip runs off the
  side of the scan, there is no holder on that side to mark where the frame
  ends. The plugin used to take the clear gap between two frames, and often a
  slice of the next frame, as part of the photo. It now recognises the gap (a
  band of plain, clear film running the full length of the frame) and crops
  where the picture begins. Seen on five of six test scans, on one or both sides.
- **The thin bright edge of the film is no longer included.** Along the top and
  bottom of the strip, a narrow band of clear film (the rebate) runs between the
  picture and the holder. Where the frame touched the holder, that band could
  stay inside the crop. The plugin now steps across it to where the picture starts.
- **Pale picture is not mistaken for a gap.** Flat, light areas next to a gap,
  such as pavement or sky, are darker than clear film on a negative, so they
  are kept as picture.
- **A scratch or line inside a gap no longer confuses it.** A hairline running
  down the gap used to split it in two, so only half was recognised.

Of 20 earlier test scans, 16 crop exactly as in 1.2; the other four are
slightly tighter, where 1.2 had left film edge or gap inside the crop.

## 1.2.0 (2026-11-05)

### Changed
- Released under the GPL-3.0 licence, with a LICENSE file.
- New plug-in identifier (com.filmframecrop.lightroom), so it cannot clash with
  other plug-ins. Remove the old version in Plug-in Manager before adding this one.
- The download now contains a single, ready-made FilmFrameCrop.lrplugin folder.
- README rewritten.

## 1.1.0 (2026-10-22)

### Improved
- Edges are placed at the colour step between frame and film base, measured
  from the holder inwards, for tighter crops on camera scans.
- Tilt is measured from how sharp the frame's edges become when it is
  straightened, without a bias towards 0 degrees.
- Film type defaults to Negative; auto-detect could be misled by a dark holder.

## 1.0.0 (2026-10-22)

- First release: automatic cropping of film scans to the exposed frame, with
  straightening, inset, aspect ratio and debug images.
