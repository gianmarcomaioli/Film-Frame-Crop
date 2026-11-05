#!/usr/bin/env python3
"""
Film Frame Crop - detection helper for the Lightroom Classic plugin.

Lightroom renders each selected photo to a small, uncropped JPEG. This script
finds the exposed frame in each JPEG and writes Lightroom crop values
(CropLeft, CropTop, CropRight, CropBottom, CropAngle) to a result file, which
the plugin then applies.

Usage:
    python3 detect_crop.py --check
    python3 detect_crop.py --job JOB.txt --out RESULT.txt [options]

Job file: one line per image, tab separated:
    <id> <TAB> <path to rendered JPEG> <TAB> <Lightroom orientation code, e.g. AB>

Result file: one line per image, tab separated:
    <id> <TAB> ok <TAB> left <TAB> top <TAB> right <TAB> bottom <TAB> angle <TAB> note
    <id> <TAB> fail <TAB> <reason>

Requires: numpy, opencv-python  (python3 -m pip install numpy opencv-python)
"""

import argparse
import math
import os
import sys
import traceback

import numpy as np
import cv2

WORK_LONG_EDGE = 1200          # analysis resolution (pixels, long edge)

STANDARD_RATIOS = {
    "3:2": 3 / 2,
    "4:3": 4 / 3,
    "1:1": 1.0,
    "7:6": 7 / 6,
    "5:4": 5 / 4,
    "16:9": 16 / 9,
    "65:24": 65 / 24,
}
AUTO_SNAP_TOLERANCE = 0.03     # snap to a standard ratio if within 3 %


# --------------------------------------------------------------------------
# Image input / output
# --------------------------------------------------------------------------

def read_image(path):
    # np.fromfile + imdecode copes with non-ASCII paths on Windows.
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not read rendered image")
    return img


def write_image(path, img):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if ok:
        buf.tofile(path)


# --------------------------------------------------------------------------
# Geometry helpers
#
# A frame is described as (cx, cy, w, h, theta):
#   centre (cx, cy) in pixels, width w along u = (cos t, sin t),
#   height h along v = (-sin t, cos t), theta in degrees.
# Image y points down, so a positive theta is a clockwise tilt on screen.
# --------------------------------------------------------------------------

def axes(theta):
    t = math.radians(theta)
    return np.array([math.cos(t), math.sin(t)]), np.array([-math.sin(t), math.cos(t)])


def rect_corners(rect):
    """Corners in order: top-left, top-right, bottom-right, bottom-left (as seen when straightened)."""
    cx, cy, w, h, theta = rect
    u, v = axes(theta)
    c = np.array([cx, cy])
    return np.array([
        c - u * w / 2 - v * h / 2,
        c + u * w / 2 - v * h / 2,
        c + u * w / 2 + v * h / 2,
        c - u * w / 2 + v * h / 2,
    ])


def rect_from_box_points(pts):
    """Convert cv2.boxPoints output to (cx, cy, w, h, theta) with theta in [-45, 45]."""
    pts = np.asarray(pts, dtype=float)
    c = pts.mean(axis=0)
    e1 = pts[1] - pts[0]
    e2 = pts[2] - pts[1]
    best = None
    for e, other in ((e1, e2), (e2, e1)):
        a = math.degrees(math.atan2(e[1], e[0]))
        # fold the direction into (-90, 90]
        while a <= -90:
            a += 180
        while a > 90:
            a -= 180
        if -45 <= a <= 45 and (best is None or abs(a) < abs(best[2])):
            best = (np.linalg.norm(e), np.linalg.norm(other), a)
    w, h, a = best
    return (float(c[0]), float(c[1]), float(w), float(h), float(a))


def deskew(img, centre, theta, interp=cv2.INTER_NEAREST):
    """Rotate img so a frame tilted by theta becomes axis aligned (same canvas, same centre)."""
    M = cv2.getRotationMatrix2D((float(centre[0]), float(centre[1])), theta, 1.0)
    return cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), flags=interp,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def unrotate_point(pt, centre, theta):
    """Map a point from deskewed coordinates back to the original image."""
    u, v = axes(theta)
    d = np.asarray(pt, dtype=float) - np.asarray(centre, dtype=float)
    return np.asarray(centre, dtype=float) + d[0] * u + d[1] * v


# --------------------------------------------------------------------------
# Lightroom orientation
#
# Lightroom names orientations with two letters. A, B, C, D are the displayed
# corner positions (top-left, top-right, bottom-right, bottom-left), and the
# code says where the stored image's top-left and top-right corners end up.
# AB = normal, BC = 90 deg CW, CD = 180, DA = 90 deg CCW, BA/DC/AD/CB = mirrored.
# --------------------------------------------------------------------------

_POS = {"A": (0.0, 0.0), "B": (1.0, 0.0), "C": (1.0, 1.0), "D": (0.0, 1.0)}
_NEIGHBOURS = {"A": "BD", "B": "AC", "C": "BD", "D": "CA"}


def orientation_affine(code):
    code = (code or "AB").strip().upper()
    if len(code) != 2 or code[0] not in _POS or code[1] not in _NEIGHBOURS[code[0]]:
        code = "AB"
    p0 = np.array(_POS[code[0]])
    p1 = np.array(_POS[code[1]])
    other = [c for c in _NEIGHBOURS[code[0]] if c != code[1]][0]
    p2 = np.array(_POS[other])
    # displayed = p0 + s * (p1 - p0) + t * (p2 - p0), (s, t) = stored normalised coords
    return np.column_stack([p1 - p0, p2 - p0]), p0


def stored_to_displayed(pt, code):
    A, p0 = orientation_affine(code)
    return p0 + A @ np.asarray(pt, dtype=float)


def displayed_to_stored(pt, code):
    A, p0 = orientation_affine(code)
    return np.linalg.solve(A, np.asarray(pt, dtype=float) - p0)


def rect_to_lightroom(rect, width, height, orientation, flip_angle=False):
    """
    Lightroom stores a crop as two opposite corners of the (possibly tilted) crop
    rectangle, normalised to the stored, un-oriented image, plus CropAngle: the
    clockwise tilt of the crop in the displayed frame. Opposite corners and an
    angle define the rectangle uniquely.
    """
    corners = rect_corners(rect)
    stored = [displayed_to_stored((x / width, y / height), orientation) for x, y in corners]
    sums = [p[0] + p[1] for p in stored]
    i = int(np.argmin(sums))
    tl, br = stored[i], stored[(i + 2) % 4]
    angle = rect[4]
    if flip_angle:
        angle = -angle
    clamp = lambda x: float(min(1.0, max(0.0, x)))
    return clamp(tl[0]), clamp(tl[1]), clamp(br[0]), clamp(br[1]), float(angle)


def lightroom_to_rect(left, top, right, bottom, angle, width, height, orientation):
    """Inverse of rect_to_lightroom, following the same model (used for testing)."""
    p1 = stored_to_displayed((left, top), orientation) * [width, height]
    p2 = stored_to_displayed((right, bottom), orientation) * [width, height]
    u, v = axes(angle)
    d = p2 - p1
    w, h = d @ u, d @ v
    c = (p1 + p2) / 2
    return (float(c[0]), float(c[1]), float(abs(w)), float(abs(h)), float(angle))


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

def border_mask(shape, frac):
    h, w = shape[:2]
    b = max(2, int(round(min(h, w) * frac)))
    m = np.zeros((h, w), dtype=bool)
    m[:b, :] = True
    m[-b:, :] = True
    m[:, :b] = True
    m[:, -b:] = True
    return m


def guess_film_type(lab):
    """Negatives have a bright (clear) film base, slides a dark one."""
    L = lab[..., 0]
    h, w = L.shape
    centre = L[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
    band = L[border_mask(L.shape, 0.12)]
    band = band[band > 10]          # ignore an opaque holder around the film
    if len(band) < 100:
        return "negative"
    return "negative" if np.median(band) > np.median(centre) else "positive"


def estimate_film_base(lab, film):
    """
    Estimate the colour of the unexposed film around the frame by clustering
    the outer band of the scan. For negatives the base is the brightest
    sizeable cluster (nothing in a negative is clearer than its base); for
    slides it is the darkest.
    """
    band = lab[border_mask(lab.shape, 0.10)].reshape(-1, 3)
    L = band[:, 0]
    chroma = np.hypot(band[:, 1], band[:, 2])
    keep = ~((L > 97) & (chroma < 6))                  # clipped light / backlight
    if film == "negative":
        keep &= L > 8                                  # black holder
    pts = band[keep] if keep.sum() > 200 else band
    rng = np.random.default_rng(0)
    if len(pts) > 20000:
        pts = pts[rng.choice(len(pts), 20000, replace=False)]
    pts = pts.astype(np.float32)
    k = 4
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.2)
    cv2.setRNGSeed(1)
    _, labels, centres = cv2.kmeans(pts, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    share = np.bincount(labels.ravel(), minlength=k) / float(len(labels))
    candidates = [i for i in range(k) if share[i] >= 0.06] or list(range(k))
    if film == "negative":
        idx = max(candidates, key=lambda i: centres[i][0])
    else:
        idx = min(candidates, key=lambda i: centres[i][0])
    # refine: median of band pixels close to the chosen centre
    d = np.linalg.norm(pts - centres[idx], axis=1)
    near = pts[d < 10]
    base = np.median(near, axis=0) if len(near) > 50 else centres[idx]
    return base.astype(np.float32)


def frame_mask(img, film, sensitivity):
    """Boolean mask of pixels that look like exposed image rather than base, holder or light."""
    blur = cv2.GaussianBlur(img, (0, 0), 1.5)
    lab = cv2.cvtColor(blur.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)
    if film == "auto":
        film = guess_film_type(lab)
    base = estimate_film_base(lab, film)
    dE = np.linalg.norm(lab - base, axis=2)
    dE = cv2.GaussianBlur(dE, (0, 0), 1.0)

    # Texture: local standard deviation of lightness. The film base is almost
    # perfectly flat, while picture areas carry grain and detail even where
    # their colour is close to the base (thin shadows on a negative).
    Lraw = cv2.cvtColor(img.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)[..., 0]
    k = 5
    mean = cv2.blur(Lraw, (k, k))
    tex = np.sqrt(np.maximum(cv2.blur(Lraw * Lraw, (k, k)) - mean * mean, 0))

    # Thresholds from the base itself: pixels in the outer band that are close
    # to the base colour and flat.
    band = border_mask(dE.shape, 0.12)
    sel = band & (dE < 8)
    base_tex = np.median(tex[sel]) if sel.sum() > 200 else 0.8
    base_dE = np.median(dE[sel]) if sel.sum() > 200 else 1.5
    s = max(0.25, sensitivity)
    tex_thresh = max(1.2, 2.2 * base_tex + 0.4) / s
    col_thresh = max(4.0, 3.0 * base_dE + 2.0) / s

    L = lab[..., 0]
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    background = (dE < col_thresh) & (tex < tex_thresh)          # film base
    if film == "negative":
        background |= L > base[0] + 6.0                         # light past the film
        background |= L < min(12.0, 0.2 * base[0])              # opaque holder
    else:
        background |= (L > 97) & (chroma < 6)                   # backlight past the slide

    # Everything that is background *and connected to the edge of the scan*
    # is outside the frame. Whatever it encloses is the frame, so flat areas
    # inside the picture cannot cut the crop short.
    bg = cv2.morphologyEx(background.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels = cv2.connectedComponents(bg, connectivity=4)
    edge_labels = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    edge_labels = edge_labels[edge_labels > 0]
    outside = np.isin(labels, edge_labels)
    mask = ~outside
    return mask, ~background, film, base, (col_thresh, tex_thresh)


def largest_component(mask):
    m = mask.astype(np.uint8)
    h, w = m.shape
    # opening removes thin bright/dark lines along the holder and strip edges
    k_open = max(5, int(round(min(h, w) * 0.012)) | 1)
    k_close = max(5, int(round(min(h, w) * 0.008)) | 1)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k_open, k_open)))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k_close, k_close)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    comp = (labels == i).astype(np.uint8)
    # fill holes (dark shadows inside a negative look like base)
    contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(comp)
    cv2.drawContours(filled, contours, -1, 1, thickness=-1)
    return filled, max(contours, key=cv2.contourArea)


def edge_profile(seg, run):
    """Index of the first position in each row of seg where `run` consecutive mask pixels start; -1 if none."""
    if seg.shape[1] < run:
        return np.full(seg.shape[0], -1)
    c = np.cumsum(np.pad(seg.astype(np.int32), ((0, 0), (1, 0))), axis=1)
    win = c[:, run:] - c[:, :-run]
    hit = win >= run
    first = np.argmax(hit, axis=1)
    first[~hit.any(axis=1)] = -1
    return first


def robust_slope(pos, coord):
    """Fit pos = a*coord + b, discarding outliers; returns (a, n_used) or (None, 0)."""
    ok = pos >= 0
    pos, coord = pos[ok].astype(float), coord[ok].astype(float)
    if len(pos) < 20:
        return None, 0
    for _ in range(3):
        a, b = np.polyfit(coord, pos, 1)
        r = pos - (a * coord + b)
        mad = np.median(np.abs(r - np.median(r))) + 0.5
        keep = np.abs(r) < 3 * mad
        if keep.sum() < 20:
            break
        pos, coord = pos[keep], coord[keep]
    a, b = np.polyfit(coord, pos, 1)
    return a, len(pos)


def edge_positions(m, x0, x1, y0, y1, run):
    """
    In an axis-aligned (deskewed) mask, find per-row / per-column edge positions
    of the frame whose rough bounds are x0..x1, y0..y1. Returns dict of
    edge -> (positions in image coordinates, coordinate along the edge).
    """
    h, w = m.shape
    fw, fh = x1 - x0, y1 - y0
    margin = int(round(0.05 * max(fw, fh))) + run
    inner = 0.35

    rows = np.arange(int(y0 + 0.15 * fh), int(y1 - 0.15 * fh))
    cols = np.arange(int(x0 + 0.15 * fw), int(x1 - 0.15 * fw))
    rows = rows[(rows >= 0) & (rows < h)]
    cols = cols[(cols >= 0) & (cols < w)]
    out = {}

    a, b = max(0, int(x0) - margin), min(w, int(x0 + inner * fw))
    p = edge_profile(m[rows, a:b], run)
    out["left"] = (np.where(p >= 0, p + a, -1), rows)

    a, b = max(0, int(x1 - inner * fw)), min(w, int(x1) + margin)
    p = edge_profile(m[rows, a:b][:, ::-1], run)
    out["right"] = (np.where(p >= 0, b - p, -1), rows)

    a, b = max(0, int(y0) - margin), min(h, int(y0 + inner * fh))
    p = edge_profile(m[a:b, cols].T, run)
    out["top"] = (np.where(p >= 0, p + a, -1), cols)

    a, b = max(0, int(y1 - inner * fh)), min(h, int(y1) + margin)
    p = edge_profile(m[a:b, cols].T[:, ::-1], run)
    out["bottom"] = (np.where(p >= 0, b - p, -1), cols)
    return out


def refine_angle(mask, rect, run):
    """Measure the residual tilt of the four edges after deskewing; returns a correction in degrees."""
    cx, cy, w, h, theta = rect
    m = deskew(mask, (cx, cy), theta)
    e = edge_positions(m, cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2, run)
    estimates, weights = [], []
    for name in ("left", "right"):
        a, n = robust_slope(*e[name])
        if a is not None:
            estimates.append(-math.degrees(math.atan(a)))
            weights.append(n)
    for name in ("top", "bottom"):
        a, n = robust_slope(*e[name])
        if a is not None:
            estimates.append(math.degrees(math.atan(a)))
            weights.append(n)
    if not estimates:
        return 0.0
    estimates, weights = np.array(estimates), np.array(weights, dtype=float)
    med = np.median(estimates)
    keep = np.abs(estimates - med) < 0.75
    if keep.any():
        estimates, weights = estimates[keep], weights[keep]
    return float(np.average(estimates, weights=weights))


def refine_edges(mask, rect, run):
    """Locate the four edges precisely in the deskewed mask; returns an updated rect."""
    cx, cy, w, h, theta = rect
    m = deskew(mask, (cx, cy), theta)
    e = edge_positions(m, cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2, run)
    found = {}
    for name, (pos, _) in e.items():
        good = pos[pos >= 0]
        if len(good) >= 10:
            # a high/low percentile rather than the median keeps the crop inside
            # the frame when the film edge is slightly curved or uneven
            q = 75 if name in ("left", "top") else 25
            found[name] = float(np.percentile(good, q))
    x0 = found.get("left", cx - w / 2)
    x1 = found.get("right", cx + w / 2)
    y0 = found.get("top", cy - h / 2)
    y1 = found.get("bottom", cy + h / 2)
    if x1 - x0 < 0.5 * w or y1 - y0 < 0.5 * h:
        return rect
    c = unrotate_point(((x0 + x1) / 2, (y0 + y1) / 2), (cx, cy), theta)
    return (float(c[0]), float(c[1]), float(x1 - x0), float(y1 - y0), theta)


def _find_edge(cov, start, outward):
    """
    cov: fraction of picture-like pixels per column (or row) of the deskewed scan.
    Walk outward from `start` until a clear stretch of film base is reached, then
    come back in to the first position where picture-like pixels persist.
    outward = -1 (towards index 0) or +1.
    """
    n = len(cov)
    run = max(4, int(round(0.012 * n)))
    low = 0.06
    start = int(min(n - 1, max(0, start)))
    # 1. find the base band outside the frame
    i, count, outer = start, 0, None
    while 0 <= i < n:
        count = count + 1 if cov[i] < low else 0
        if count >= run:
            outer = i - outward * (run - 1)      # innermost position of the base run
            break
        i += outward
    if outer is None:
        return None
    # 2. picture level between the base band and the starting point
    a, b = sorted((outer, start))
    seg = cov[a:b + 1]
    inner = cov[max(0, start - 3 * run): start + 1] if outward == 1 else cov[start: start + 3 * run]
    level = max(np.median(seg[seg >= low]) if (seg >= low).any() else 0.0,
                np.median(inner) if len(inner) else 0.0)
    thr = max(0.08, 0.35 * level)
    # 3. walk back in to where the picture persists
    j, count = outer, 0
    while 0 <= j < n and (j - start) * outward <= run:
        count = count + 1 if cov[j] >= thr else 0
        if count >= run:
            return j + outward * (run - 1)       # outermost position of the persistent run
        j -= outward
    return None


def refine_edges_profile(pix, rect):
    """
    Place each edge using coverage profiles: the share of picture-like pixels in
    every column/row of the deskewed scan, averaged along the edge. Flat, pale
    picture areas that touch the frame edge still leave a clear step here,
    because the rest of the edge carries picture detail and the base does not.
    """
    cx, cy, w, h, theta = rect
    m = deskew(pix.astype(np.uint8), (cx, cy), theta).astype(np.float32)
    H, W = m.shape
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    r0, r1 = int(max(0, y0 + 0.1 * h)), int(min(H, y1 - 0.1 * h))
    c0, c1 = int(max(0, x0 + 0.1 * w)), int(min(W, x1 - 0.1 * w))
    if r1 - r0 < 20 or c1 - c0 < 20:
        return rect
    colcov = m[r0:r1, :].mean(axis=0)
    rowcov = m[:, c0:c1].mean(axis=1)
    L = _find_edge(colcov, x0, -1)
    R = _find_edge(colcov, x1, +1)
    T = _find_edge(rowcov, y0, -1)
    B = _find_edge(rowcov, y1, +1)
    nx0 = float(L) if L is not None else x0
    nx1 = float(R + 1) if R is not None else x1
    ny0 = float(T) if T is not None else y0
    ny1 = float(B + 1) if B is not None else y1
    if nx1 - nx0 < 0.5 * w or ny1 - ny0 < 0.5 * h:
        return rect
    c = unrotate_point(((nx0 + nx1) / 2, (ny0 + ny1) / 2), (cx, cy), theta)
    return (float(c[0]), float(c[1]), float(nx1 - nx0), float(ny1 - ny0), theta)


def estimate_angle_projection(L, rect, max_angle):
    """
    Find the tilt that makes the straight structures around the frame (frame
    edges, film edges) line up with the image axes: rotate a crop around the
    frame and pick the angle whose row and column averages are sharpest.
    """
    cx, cy, w, h, _ = rect
    H, W = L.shape
    half = 0.5 * 1.15 * math.hypot(w, h)
    x0, x1 = int(max(0, cx - half)), int(min(W, cx + half))
    y0, y1 = int(max(0, cy - half)), int(min(H, cy + half))
    crop = L[y0:y1, x0:x1].astype(np.float32)
    f = 800.0 / max(crop.shape)
    if f < 1:
        crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    else:
        f = 1.0
    ccx, ccy = (cx - x0) * f, (cy - y0) * f
    # analyse only the frame plus a margin, so the holder edges far out matter less
    hw, hh = 0.5 * w * f * 1.04, 0.5 * h * f * 1.04

    def score(a):
        M = cv2.getRotationMatrix2D((float(ccx), float(ccy)), a, 1.0)
        # a half-pixel shift makes every angle (0 included) resample the image,
        # so interpolation blur does not favour exactly 0 degrees
        M[0, 2] += 0.5
        M[1, 2] += 0.5
        r = cv2.warpAffine(crop, M, (crop.shape[1], crop.shape[0]), flags=cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_REPLICATE)
        rx0, rx1 = int(max(0, ccx - hw)), int(min(r.shape[1], ccx + hw))
        ry0, ry1 = int(max(0, ccy - hh)), int(min(r.shape[0], ccy + hh))
        # use the middle 70 % of the span so corners and neighbours count less
        sx0, sx1 = int(ccx - 0.35 * w * f), int(ccx + 0.35 * w * f)
        sy0, sy1 = int(ccy - 0.35 * h * f), int(ccy + 0.35 * h * f)
        cols = r[max(0, sy0):sy1, rx0:rx1].mean(axis=0)
        rows = r[ry0:ry1, max(0, sx0):sx1].mean(axis=1)
        return float(np.sum(np.diff(cols) ** 2) + np.sum(np.diff(rows) ** 2))

    angles = np.arange(-max_angle, max_angle + 1e-9, 0.25)
    best = max(angles, key=score)
    fine = np.arange(best - 0.3, best + 0.3001, 0.05)
    best = max(fine, key=score)
    return float(best)


def _step_edge(prof, base, start, outward, base_L):
    """
    prof: averaged Lab per column/row (N x 3) in the deskewed scan.
    Find the film-base band just outside the frame, then the outermost clear
    colour step between that band and `start` (the provisional edge).
    """
    n = len(prof)
    start = int(min(n - 1, max(0, start)))
    L = prof[:, 0]
    # 1. walk outward to where the film ends (holder or light)
    i = start
    while 0 <= i < n:
        if L[i] < 0.5 * base_L or L[i] > base_L + 6:
            break
        i += outward
    outer = i - outward * 6                       # step back past the blurred boundary
    if (outer - start) * outward < 4:
        return None
    # 2. gradient of the averaged colour
    d = 2
    g = np.zeros(n)
    g[d:n - d] = np.linalg.norm(prof[2 * d:] - prof[:-2 * d], axis=1)
    # slide inward off the shoulder of the holder/light edge to the first valley
    e = int(min(n - d - 1, max(d, outer)))
    while 0 < e - outward < n and (e - start) * outward > 0 and g[e - outward] <= g[e]:
        e -= outward
    margin = int(round(0.03 * n))
    a, b = sorted((e, start - outward * margin))
    a, b = max(d, a), min(n - d - 1, b)
    if b - a < 6:
        return None
    win = g[a:b + 1]
    # a step must stand well clear of the noise in the flattest part of the window
    order = list(range(len(win) - 1, -1, -1)) if outward == 1 else list(range(len(win)))
    thr = max(0.4, 6.0 * float(np.percentile(win, 20)))
    # outermost local maximum above the threshold
    for k in order:
        if win[k] >= thr and win[k] >= win[max(0, k - 1)] and win[k] >= win[min(len(win) - 1, k + 1)]:
            pos = a + k
            # the band outside the step must look like film base
            lo, hi = sorted((pos, outer))
            band = prof[lo + 2: hi - 1]
            if len(band) >= 2 and np.median(np.linalg.norm(band - base, axis=1)) < 8:
                return pos
            return None
    return None


def refine_edges_step(lab, base, rect):
    """Snap each edge to the colour step between frame and film base."""
    cx, cy, w, h, theta = rect
    H, W = lab.shape[:2]
    rot = deskew(lab, (cx, cy), theta, interp=cv2.INTER_LINEAR)
    valid = deskew(np.ones((H, W), np.float32), (cx, cy), theta) > 0.5
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    r0, r1 = int(max(0, y0 + 0.12 * h)), int(min(H, y1 - 0.12 * h))
    c0, c1 = int(max(0, x0 + 0.12 * w)), int(min(W, x1 - 0.12 * w))
    if r1 - r0 < 20 or c1 - c0 < 20:
        return rect

    def avg(region, vmask, axis):
        s = (region * vmask[..., None]).sum(axis=axis)
        c = vmask.sum(axis=axis)[..., None]
        return s / np.maximum(c, 1)

    colprof = avg(rot[r0:r1, :], valid[r0:r1, :], 0)
    rowprof = avg(rot[:, c0:c1], valid[:, c0:c1], 1)
    bL = float(base[0])
    L = _step_edge(colprof, base, x0, -1, bL)
    R = _step_edge(colprof, base, x1, +1, bL)
    T = _step_edge(rowprof, base, y0, -1, bL)
    B = _step_edge(rowprof, base, y1, +1, bL)
    nx0 = float(L) if L is not None else x0
    nx1 = float(R) if R is not None else x1
    ny0 = float(T) if T is not None else y0
    ny1 = float(B) if B is not None else y1
    if nx1 - nx0 < 0.5 * w or ny1 - ny0 < 0.5 * h:
        return rect
    c = unrotate_point(((nx0 + nx1) / 2, (ny0 + ny1) / 2), (cx, cy), theta)
    return (float(c[0]), float(c[1]), float(nx1 - nx0), float(ny1 - ny0), theta)


def apply_aspect(rect, aspect):
    cx, cy, w, h, theta = rect
    if aspect in (None, "", "free"):
        return rect, None
    long_, short = max(w, h), min(w, h)
    current = long_ / short
    if aspect == "auto":
        name = min(STANDARD_RATIOS, key=lambda k: abs(current / STANDARD_RATIOS[k] - 1))
        if abs(current / STANDARD_RATIOS[name] - 1) > AUTO_SNAP_TOLERANCE:
            return rect, None
    else:
        name = aspect
    target = STANDARD_RATIOS.get(name)
    if not target:
        return rect, None
    if current > target:
        long_ = short * target          # too long: trim the long side
    else:
        short = long_ / target          # too square: trim the short side
    if w >= h:
        w, h = long_, short
    else:
        w, h = short, long_
    return (cx, cy, w, h, theta), name


def fit_inside(rect, width, height):
    """Trim the rectangle until all four corners lie inside the image."""
    cx, cy, w, h, theta = rect
    u, v = axes(theta)
    step = max(width, height) / 2000.0
    for _ in range(4000):
        corners = rect_corners((cx, cy, w, h, theta))
        bad = [(i, p) for i, p in enumerate(corners)
               if p[0] < -1e-6 or p[1] < -1e-6 or p[0] > width + 1e-6 or p[1] > height + 1e-6]
        if not bad:
            break
        i, _ = bad[0]
        su = -1 if i in (0, 3) else 1   # corner on the left (-) or right (+) side
        sv = -1 if i in (0, 1) else 1   # corner on the top (-) or bottom (+) side
        # pull in the two edges that meet at the offending corner
        w -= step
        h -= step
        c = np.array([cx, cy]) - su * u * step / 2 - sv * v * step / 2
        cx, cy = float(c[0]), float(c[1])
        if w < 10 or h < 10:
            break
    return (cx, cy, w, h, theta)


def detect_frame(img, film="auto", sensitivity=1.0, max_angle=5.0, inset_pct=1.0,
                 aspect="free"):
    """Return (rect in img pixel coords, info dict)."""
    H, W = img.shape[:2]
    scale = WORK_LONG_EDGE / float(max(H, W))
    work = cv2.resize(img, (int(round(W * scale)), int(round(H * scale))),
                      interpolation=cv2.INTER_AREA) if scale < 1 else img.copy()
    if scale >= 1:
        scale = 1.0
    h, w = work.shape[:2]

    mask, pix, film_used, base, thresh = frame_mask(work, film, sensitivity)
    lc = largest_component(mask)
    if lc is None:
        raise RuntimeError("no frame found")
    comp, contour = lc
    if cv2.contourArea(contour) < 0.15 * w * h:
        raise RuntimeError("frame not found (largest region is too small)")

    hull = cv2.convexHull(contour)
    rect = rect_from_box_points(cv2.boxPoints(cv2.minAreaRect(hull)))
    run = max(3, int(round(min(h, w) * 0.004)))

    lab = cv2.cvtColor(cv2.GaussianBlur(work, (0, 0), 1.0).astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)
    if max_angle <= 0:
        x, y, bw, bh = cv2.boundingRect(contour)
        rect = (x + bw / 2.0, y + bh / 2.0, float(bw), float(bh), 0.0)
    else:
        a = estimate_angle_projection(lab[..., 0], rect, max_angle)
        rect = rect[:4] + (a,)

    rect = refine_edges(comp, rect, run)
    for _ in range(2):
        rect = refine_edges_profile(pix, rect)
    for _ in range(2):
        rect = refine_edges_step(lab, base, rect)

    inset = inset_pct / 100.0 * min(rect[2], rect[3])
    rect = (rect[0], rect[1], rect[2] - 2 * inset, rect[3] - 2 * inset, rect[4])
    rect, snapped = apply_aspect(rect, aspect)
    rect = fit_inside(rect, w, h)

    # back to the resolution of the rendered image
    full = (rect[0] / scale, rect[1] / scale, rect[2] / scale, rect[3] / scale, rect[4])
    info = {"film": film_used, "threshold": thresh, "ratio": snapped,
            "work": work, "mask": comp, "work_rect": rect}
    return full, info


def save_debug(path, info):
    work = info["work"].copy()
    overlay = work.copy()
    overlay[info["mask"] > 0] = (overlay[info["mask"] > 0] * 0.6 + np.array([0, 90, 0]) * 0.4).astype(np.uint8)
    pts = rect_corners(info["work_rect"]).astype(np.int32)
    cv2.polylines(overlay, [pts], True, (0, 0, 255), 2, cv2.LINE_AA)
    col, tex = info["threshold"]
    label = "%s  angle %.2f  col %.1f  tex %.2f%s" % (info["film"], info["work_rect"][4], col, tex,
                                                     ("  " + info["ratio"]) if info["ratio"] else "")
    cv2.putText(overlay, label, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(overlay, label, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    write_image(path, overlay)


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def run_job(args):
    results = []
    with open(args.job, "r", encoding="utf-8") as f:
        lines = [ln.rstrip("\r\n") for ln in f if ln.strip()]
    for ln in lines:
        parts = ln.split("\t")
        pid = parts[0]
        try:
            path = parts[1]
            orientation = parts[2] if len(parts) > 2 else "AB"
            img = read_image(path)
            H, W = img.shape[:2]
            rect, info = detect_frame(img, film=args.film, sensitivity=args.sensitivity,
                                      max_angle=args.max_angle, inset_pct=args.inset,
                                      aspect=args.aspect)
            l, t, r, b, a = rect_to_lightroom(rect, W, H, orientation, args.flip_angle)
            note = info["film"] + ((" " + info["ratio"]) if info["ratio"] else "")
            results.append("\t".join([pid, "ok"] + ["%.6f" % x for x in (l, t, r, b, a)] + [note]))
            if args.debug_dir:
                save_debug(os.path.join(args.debug_dir, "%s_debug.jpg" % pid), info)
        except Exception as e:  # report and carry on with the next photo
            msg = str(e).replace("\t", " ").replace("\n", " ") or e.__class__.__name__
            results.append("\t".join([pid, "fail", msg]))
            if args.verbose:
                traceback.print_exc()
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(results) + "\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="print versions and exit")
    p.add_argument("--job")
    p.add_argument("--out")
    p.add_argument("--film", default="auto", choices=["auto", "negative", "positive"])
    p.add_argument("--sensitivity", type=float, default=1.0)
    p.add_argument("--max-angle", type=float, default=5.0)
    p.add_argument("--inset", type=float, default=1.0, help="percent of the short side")
    p.add_argument("--aspect", default="free", choices=["free", "auto"] + list(STANDARD_RATIOS))
    p.add_argument("--flip-angle", action="store_true")
    p.add_argument("--debug-dir")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    if args.check:
        print("ok python %s numpy %s opencv %s" % (sys.version.split()[0], np.__version__, cv2.__version__))
        return 0
    if not args.job or not args.out:
        p.error("--job and --out are required")
    run_job(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
