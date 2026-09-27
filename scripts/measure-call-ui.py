#!/usr/bin/env python3
import json
import sys

import numpy as np
from PIL import Image
from scipy import ndimage


def components(mask: np.ndarray, min_area: int, max_area: int = 10000):
    labels, count = ndimage.label(mask)
    found = []
    for label in range(1, count + 1):
        ys, xs = np.where(labels == label)
        area = len(xs)
        if min_area <= area <= max_area:
            found.append({
                "bounds": [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)],
                "area": area,
            })
    return sorted(found, key=lambda item: (item["bounds"][1], item["bounds"][0]))


def measure(path: str):
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    gray = rgb.mean(axis=2)
    header = rgb[:39]
    header_white = np.min(header, axis=2) > 175
    header_components = components(header_white, 2, 220)

    bottom = rgb[420:]
    bottom_gray = gray[420:]
    local = ndimage.gaussian_filter(bottom_gray, sigma=7)
    dark_controls = (bottom_gray < local - 15) & (bottom_gray < 65)
    dark_components = components(dark_controls, 30, 1200)

    red = (bottom[:, :, 0] > 175) & (bottom[:, :, 1] < 95) & (bottom[:, :, 2] < 105)
    red_components = components(red, 40, 1200)

    bottom_white = np.min(bottom, axis=2) > 180
    bottom_white_components = components(bottom_white, 2, 180)
    for group in (dark_components, red_components, bottom_white_components):
        for item in group:
            item["bounds"][1] += 420

    return {
        "path": path,
        "header_white": header_components,
        "bottom_dark": dark_components,
        "bottom_red": red_components,
        "bottom_white": bottom_white_components,
    }


print(json.dumps([measure(path) for path in sys.argv[1:]], ensure_ascii=False, indent=2))
