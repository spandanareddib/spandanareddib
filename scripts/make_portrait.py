#!/usr/bin/env python3
"""
Turn a photo into data/portrait.txt (ASCII art used by the hero card).

  python scripts/make_portrait.py my-photo.jpg                 # auto settings
  python scripts/make_portrait.py my-photo.jpg --crop 50,470,670,1140 --cols 84

--crop is left,top,right,bottom in pixels of the original photo (head and shoulders works best).
Needs: pip install pillow
"""
import argparse
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

ap = argparse.ArgumentParser()
ap.add_argument("photo")
ap.add_argument("--crop", help="left,top,right,bottom")
ap.add_argument("--cols", type=int, default=84)
ap.add_argument("--blur", type=float, default=1.6, help="higher = smoother, hides background texture")
ap.add_argument("--cutoff", type=float, default=0.78, help="brightness above this prints as blank")
ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data" / "portrait.txt"))
a = ap.parse_args()

im = Image.open(a.photo).convert("L")
if a.crop:
    im = im.crop(tuple(int(v) for v in a.crop.split(",")))
import numpy as np
arr = np.asarray(im, dtype=float) / 255
smooth = np.asarray(im.filter(ImageFilter.GaussianBlur(a.blur)), dtype=float) / 255
wide = np.asarray(im.filter(ImageFilter.GaussianBlur(max(im.size) / 9)), dtype=float) / 255
# local normalisation: face features (eyes, glasses, lips) pop out of flat skin and dark hair
norm = np.clip(0.55 + (smooth - wide) * 2.6 + (smooth - 0.5) * 0.35, 0, 1)
im = Image.fromarray((norm * 255).astype("uint8"))
rows = int(a.cols * im.size[1] / im.size[0] * 0.5)  # glyphs are about twice as tall as wide
small = im.resize((a.cols, rows), Image.LANCZOS)
ramp = "@%#Xx*+=-:."  # dark -> light
lines = []
for y in range(rows):
    line = ""
    for x in range(a.cols):
        v = small.getpixel((x, y)) / 255
        line += " " if v > a.cutoff else ramp[int(min(v / a.cutoff, 0.999) * len(ramp))]
    lines.append(line.rstrip())
Path(a.out).write_text("\n".join(lines))
print(f"wrote {a.out}: {a.cols} cols x {rows} rows")
