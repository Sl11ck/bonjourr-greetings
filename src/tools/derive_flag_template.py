#!/usr/bin/env python3
"""Re-derive src/flag-template.json and src/flag-slab-mask.png (only needed if you want to check or tweak them).

Microsoft draws coloured flags in 3D Fluent as a rounded "slab" (🏳️‍🌈 🏳️‍⚧️ 🏴‍☠️), but never made country flags.
This fits how those slabs are lit: for every pixel, its luminance is modelled as  flat_colour * g + h,
where g and h depend only on which edge is nearest and how far away it is. The flat colour of each region is the
median colour Microsoft's 3D render uses inside it, so the fit only captures the bevel and gradient, not the design.

    pip install numpy scipy pillow resvg-py
    python src/tools/derive_flag_template.py
"""
import io, json, urllib.parse, urllib.request
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, binary_erosion
import resvg_py

ROOT = Path(__file__).resolve().parents[2]
RAW = 'https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/assets/'
FLAGS = {'Rainbow flag': 'rainbow_flag', 'Transgender flag': 'transgender_flag', 'Pirate flag': 'pirate_flag'}
X0, Y0, X1, Y1 = 16, 48, 240, 208          # slab box on the 256 px canvas (same for all three)
MAXD = 16


def get(path):
    return urllib.request.urlopen(RAW + urllib.parse.quote(path), timeout=60).read()


def load(folder, stem):
    d3 = np.array(Image.open(io.BytesIO(get(f'{folder}/3D/{stem}_3d.png'))).convert('RGBA')).astype(float)
    png = bytes(resvg_py.svg_to_bytes(svg_string=get(f'{folder}/Flat/{stem}_flat.svg').decode(), width=256, height=256))
    flat = np.array(Image.open(io.BytesIO(png)).convert('RGBA')).astype(float)   # same 32-unit grid as the 3D render
    return d3, flat


def base_map(d3, flat):
    rgb = flat[..., :3]
    key = rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]
    vals, counts = np.unique(key[flat[..., 3] > 250], return_counts=True)
    pal = np.array([[v // 65536, (v // 256) % 256, v % 256] for v, c in zip(vals, counts) if c > 300], float)
    lab = ((rgb[..., None, :] - pal[None, None]) ** 2).sum(-1).argmin(-1)
    base = np.zeros_like(rgb)
    for i in range(len(pal)):
        core = binary_erosion(lab == i, iterations=4) & (d3[..., 3] > 250)
        base[lab == i] = np.median(d3[..., :3][core], axis=0) if core.sum() > 20 else pal[i]
    edge = np.zeros(lab.shape, bool)
    edge[:-1] |= lab[:-1] != lab[1:]; edge[1:] |= lab[:-1] != lab[1:]
    edge[:, :-1] |= lab[:, :-1] != lab[:, 1:]; edge[:, 1:] |= lab[:, :-1] != lab[:, 1:]
    return base, ~binary_dilation(edge, iterations=3)          # region boundaries never line up exactly: skip them


def main():
    lum = lambda a: (a[..., :3] * [0.2126, 0.7152, 0.0722]).sum(-1) / 255
    data = []
    for folder, stem in FLAGS.items():
        d3, flat = load(folder, stem)
        base, ok = base_map(d3, flat)
        data.append((lum(base), lum(d3), ok))
        if stem == 'rainbow_flag':
            alpha = d3[..., 3]                 # the slab outline every flag gets
    yy, xx = np.mgrid[0:256, 0:256]
    D = np.stack([yy - Y0, Y1 - 1 - yy, xx - X0, X1 - 1 - xx]); side = D.argmin(0); dist = D.min(0)
    g = np.ones((4, MAXD + 1)); h = np.zeros((4, MAXD + 1))
    for s in range(4):
        along = ((xx > X0 + 16) & (xx < X1 - 16)) if s < 2 else ((yy > Y0 + 16) & (yy < Y1 - 16))   # skip corners
        for k in range(MAXD + 1):
            sel = (alpha > 0) & (side == s) & (dist == k) & along
            b = np.concatenate([lb[sel & ok] for lb, _, ok in data]); o = np.concatenate([lo[sel & ok] for _, lo, ok in data])
            (g[s, k], h[s, k]), *_ = np.linalg.lstsq(np.vstack([b, np.ones_like(b)]).T, o, rcond=None)
    Image.fromarray(alpha.astype('uint8'), 'L').save(ROOT / 'src/flag-slab-mask.png', optimize=True)
    tpl = json.loads((ROOT / 'src/flag-template.json').read_text())
    tpl.update(g=np.round(g, 4).tolist(), h=np.round(h, 4).tolist())
    (ROOT / 'src/flag-template.json').write_text(json.dumps(tpl, indent=1))
    print('written src/flag-template.json and src/flag-slab-mask.png')


if __name__ == '__main__':
    main()
