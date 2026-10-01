#!/usr/bin/env python3
"""Build greetings.css, PREVIEW.md and the resized emoji for the Bonjourr greeting engine.

    pip install -r src/requirements.txt
    python src/build.py            # rebuild CSS + preview, encode any missing emoji
    python src/build.py --force    # also re-download and re-encode every emoji

Everything that decides *what* is shown lives in src/config.json.
This script only turns that config into CSS.
"""
import base64, io, json, os, re, sys, urllib.parse, urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / 'src/config.json').read_text(encoding='utf-8'))
CACHE = ROOT / 'src/.cache'
EMOJI_DIR = ROOT / 'emoji'
FORCE = '--force' in sys.argv
PX = CFG['emoji_size_css_px']        # displayed emoji size in CSS px
# One file per screen scale, so the browser never has to resize an animation.
# (Firefox resizes animated images with a cheap filter -> jagged edges. Static images are fine.)
SCALES = CFG.get('emoji_scales', [1, 1.25, 1.5, 1.75, 2, 2.5])
QUALITY = CFG.get('emoji_quality', 92)   # animated AVIF; 92 is visually lossless at a third of lossless WebP's size
JSDELIVR_LIMIT_MB = 50                   # jsDelivr refuses GitHub repos bigger than this
STATIC = set(CFG.get('static_instead_of_animated', []))

# ── emoji sources ────────────────────────────────────────────────────────────
# Microsoft's official, MIT-licensed animated set: resized here and committed to emoji/.
MS_ANIM = 'https://media.githubusercontent.com/media/microsoft/fluentui-emoji-animated/main/assets/'
# Designs that only exist on Emojipedia: linked to, never re-hosted.
EP = 'https://em-content.zobj.net/source/'
EP3D = '473'   # Emojipedia's "Windows 11 26H2" 3D Fluent set (512px static; browsers shrink static images cleanly)
TEAMS = {      # Microsoft Teams animations with no MIT source (256px; Firefox shrinks these less cleanly)
    '🫡': 'microsoft-teams/400/saluting-face_1fae1.png',
    '🫣': 'microsoft-teams/400/face-with-peeking-eye_1fae3.png',
}
# Microsoft's folder names (they don't always match the Unicode name, e.g. "Face savoring food").
MS_FOLDER = {
    '🧐': 'Face with monocle', '😲': 'Astonished face', '☕': 'Hot beverage', '👀': 'Eyes',
    '😋': 'Face savoring food', '😉': 'Winking face', '🥱': 'Yawning face', '🥸': 'Disguised face',
    '🥳': 'Partying face', '😮‍💨': 'Face exhaling', '🦉': 'Owl', '🐦': 'Bird',
    '🫵': 'Index pointing at the viewer/Default', '😸': 'Grinning cat with smiling eyes',
    '🕵️‍♂️': 'Man detective/Default', '👂': 'Ear/Default', '🌝': 'Full moon face', '😪': 'Sleepy face',
    '😎': 'Smiling face with sunglasses', '🎉': 'Party popper', '🤔': 'Thinking face', '🧠': 'Brain',
    '🫠': 'Melting face', '🥹': 'Face holding back tears',
}
# Emojipedia slugs for the static 3D Fluent designs.
EP_SLUG = {
    '📣': 'megaphone', '🫖': 'teapot', '🍕': 'pizza', '🧳': 'luggage', '📑': 'bookmark-tabs',
    '💼': 'briefcase', '🥡': 'takeout-box', '🍜': 'steaming-bowl', '📆': 'tear-off-calendar',
    '✨': 'sparkles', '🫩': 'face-with-bags-under-eyes', '🫪': 'distorted-face',
    '🫡': 'saluting-face', '🫣': 'face-with-peeking-eye',
}


def cp(e):
    return '-'.join(f'{ord(c):x}' for c in e)


def kind(e):
    """'ms' = re-hosted Microsoft animation, 'teams' = linked Teams animation, '3d' = linked static 3D."""
    if e in STATIC and e in EP_SLUG: return '3d'
    if e in MS_FOLDER: return 'ms'
    if e in TEAMS: return 'teams'
    if e in EP_SLUG: return '3d'
    return None


def slug(e):
    """File name stem for a re-hosted emoji, e.g. 'face-with-monocle'."""
    return re.sub(r'[^a-z0-9]+', '-', MS_FOLDER[e].split('/')[0].lower()).strip('-')


def emoji_file(e, s):
    return f'emoji/{slug(e)}@{s:g}x.avif'


def fetch(url, refresh=FORCE):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / re.sub(r'[^A-Za-z0-9._-]', '_', url.split('/assets/')[-1].split('/source/')[-1])
    if refresh or not f.exists():
        print('  download', url, flush=True)
        with urllib.request.urlopen(url, timeout=60) as r:
            f.write_bytes(r.read())
    return f


def ms_anim_url(e):
    folder = MS_FOLDER[e]
    stem = folder.split('/')[0].lower().replace(' ', '_') + '_animated' + ('_default' if '/' in folder else '')
    return MS_ANIM + urllib.parse.quote(folder) + f'/animated/{stem}.png'


def needs_encoding(e):
    from PIL import Image
    for s in SCALES:
        f = ROOT / emoji_file(e, s)
        try:
            if FORCE or Image.open(f).size != (round(PX * s),) * 2:
                return True
        except OSError:
            return True
    return False


def encode(e):
    """Resize every frame with Lanczos to each screen scale; store as animated AVIF (full-res colour, 4:4:4)."""
    from PIL import Image, ImageSequence
    src = Image.open(fetch(ms_anim_url(e), refresh=False))   # already downloaded by build_emoji
    frames = [(f.convert('RGBA').copy(), int(round(f.info.get('duration', 42)))) for f in ImageSequence.Iterator(src)]
    sizes = []
    for s in SCALES:
        px = round(PX * s)
        imgs = [f.resize((px, px), Image.LANCZOS) for f, _ in frames]
        out = ROOT / emoji_file(e, s)
        tmp = out.with_suffix('.tmp')
        imgs[0].save(tmp, 'AVIF', save_all=True, append_images=imgs[1:], duration=[d for _, d in frames],
                     loop=0, quality=QUALITY, speed=4, subsampling='4:4:4')
        os.replace(tmp, out)
        sizes.append(out.stat().st_size // 1024)
    return f'  {e} {slug(e)}: ' + ' / '.join(f'{k} KB' for k in sizes)


def build_emoji():
    from PIL import features
    if not features.check('avif'):
        sys.exit('Pillow was built without AVIF support: pip install -U "pillow>=12"')
    todo = sorted({g['emoji'] for g in CFG['greetings'].values() if kind(g['emoji']) == 'ms' and needs_encoding(g['emoji'])})
    if not todo:
        return
    EMOJI_DIR.mkdir(exist_ok=True)
    for e in todo:  # download first (sequential, polite), then encode in parallel
        fetch(ms_anim_url(e))
    with ProcessPoolExecutor() as pool:
        for line in pool.map(encode, todo):
            print(line, flush=True)


def tidy_emoji():
    """Delete files no greeting uses any more, and warn before the folder outgrows jsDelivr."""
    keep = {ROOT / emoji_file(g['emoji'], s) for g in CFG['greetings'].values() if kind(g['emoji']) == 'ms' for s in SCALES}
    for f in EMOJI_DIR.glob('*.*'):
        if f.suffix in ('.avif', '.webp', '.tmp') and f not in keep:
            f.unlink()
    mb = sum(f.stat().st_size for f in keep if f.exists()) / 1e6
    print(f'emoji/ {mb:.1f} MB')
    if mb > JSDELIVR_LIMIT_MB - 8:
        print(f'WARNING: jsDelivr serves repos up to {JSDELIVR_LIMIT_MB} MB. Lower emoji_quality or drop a scale.')


def image_css(e):
    k = kind(e)
    if k == 'ms':
        return 'image-set(' + ','.join(f'url({emoji_file(e, s)}) {s:g}x' for s in SCALES) + ')'
    if k == 'teams':
        return f'image-set(url({EP}{TEAMS[e]}) {256 / PX:.4g}x)'
    return f'image-set(url({EP}microsoft-3D-fluent/{EP3D}/{EP_SLUG[e]}_{cp(e)}.png) {512 / PX:.4g}x)'


# ── probe font: turns hour / minute / weekday text into exact box sizes ─────
def probe_font_b64():
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
    U = 50                                            # 50 units at 80px = 4px per step
    w = {'M': 1, 'T': 2, 'h': 2, 'W': 3, 'F': 5, 'S': 6, 't': 1}   # Mon1 Tue2 Wed3 Thu4 Fri5 Sun6 Sat7
    order = ['.notdef', 'z'] + [f'd{k}' for k in range(1, 10)] + [f'L{c}' for c in w]
    cmap = {ord('0'): 'z', **{ord(str(k)): f'd{k}' for k in range(1, 10)}, **{ord(c): f'L{c}' for c in w}}
    for c in 'ondayuesri':
        cmap[ord(c)] = 'z'
    adv = {'.notdef': 0, 'z': 0, **{f'd{k}': k * U for k in range(1, 10)}, **{f'L{c}': v * U for c, v in w.items()}}
    fb = FontBuilder(1000, isTTF=True); fb.setupGlyphOrder(order); fb.setupCharacterMap(cmap)
    empty = TTGlyphPen(None).glyph(); p = TTGlyphPen(None)
    p.moveTo((0, 0)); p.lineTo((1, 0)); p.lineTo((1, 1)); p.closePath()
    fb.setupGlyf({g: (p.glyph() if g == '.notdef' else empty) for g in order})
    fb.setupHorizontalMetrics({g: (adv[g], 0) for g in order})
    fb.setupHorizontalHeader(ascent=0, descent=0)
    fb.setupNameTable({'familyName': 'P', 'styleName': 'R'}, mac=False)
    fb.setupOS2(sTypoAscender=0, sTypoDescender=0, sTypoLineGap=0, usWinAscent=0, usWinDescent=0)
    fb.setupPost(keepGlyphNames=False)
    D = '[z ' + ' '.join(f'd{k}' for k in range(1, 10)) + ']'
    # kern: "1x"/"2x" hours become 4px per hour. ss01 (minutes): cancels the tens digit -> 4px per last digit.
    addOpenTypeFeaturesFromString(fb.font, f"""languagesystem DFLT dflt; languagesystem latn dflt; @D={D};
        feature kern {{ pos d1 @D 450; pos d2 @D 900; }} kern;
        feature ss01 {{ pos d1 @D -500; pos d2 @D -1000; pos d3 @D -150; pos d4 @D -200; pos d5 @D -250; }} ss01;""")
    from fontTools.misc.timeTools import timestampFromString   # fixed date -> identical output every build
    fb.font['head'].created = fb.font['head'].modified = timestampFromString('Thu Jan  1 00:00:00 2026')
    fb.font.recalcTimestamp = False
    fb.font.flavor = 'woff2'; b = io.BytesIO(); fb.font.save(b)
    return base64.b64encode(b.getvalue()).decode()


# ── CSS ──────────────────────────────────────────────────────────────────────
DAYCODE = {'Mon': 1, 'Tue': 2, 'Wed': 3, 'Thu': 4, 'Fri': 5, 'Sun': 6, 'Sat': 7}
U = 4  # px per hour / per weekday code / per minute digit


def hours(a, b):
    c = []
    if a > 0: c.append(f'(width>{U * a - 2}px)')
    if b < 24: c.append(f'(width<{U * b - 2}px)')
    return ' and '.join(c) or '(width>=0px)'


def text_css(t):
    parts = t.split('{name}')
    out = []
    for i, p in enumerate(parts):
        if p: out.append(json.dumps(p, ensure_ascii=False))
        if i < len(parts) - 1: out.append('var(--name)')
    return ' '.join(out)


def validate():
    """Catch config mistakes before they turn into silently missing greetings."""
    G, err = CFG['greetings'], []
    for k, g in G.items():
        e = g['emoji']
        if kind(e) is None:
            err.append(f'greeting "{k}": no image source for {e} — add it to MS_FOLDER or EP_SLUG in build.py')
        if '"' in g['text'] or '\\' in g['text']:
            err.append(f'greeting "{k}": text may not contain " or \\')
    edge = 0
    for p in CFG['periods']:
        if p['from'] != edge: err.append(f'period "{p["id"]}" starts at {p["from"]}, expected {edge} (periods must cover 0–24 in order)')
        edge = p['to']
        if len(p['slots']) != 10: err.append(f'period "{p["id"]}" needs exactly 10 slots')
        err += [f'period "{p["id"]}": unknown greeting "{v}"' for v in p['slots'] if v not in G]
    if edge != 24: err.append('the last period must end at 24')
    for o in CFG['day_overrides']:
        if o['day'] not in DAYCODE: err.append(f'day override: unknown day "{o["day"]}" (use Mon … Sun)')
        if not 0 <= o['from'] < o['to'] <= 24: err.append(f'day override {o["day"]}: bad hours {o["from"]}–{o["to"]}')
        for i, v in o['slots'].items():
            if not (i.isdigit() and 0 <= int(i) <= 9): err.append(f'day override {o["day"]}: slot "{i}" must be 0–9')
            if v not in G: err.append(f'day override {o["day"]}: unknown greeting "{v}"')
    if err:
        sys.exit('config.json problems:\n  ' + '\n  '.join(err))


def build_css():
    G = CFG['greetings']
    ids = {k: f'g{i}' for i, k in enumerate(G)}          # short internal variable names
    lines = [
        '/* Bonjourr greeting engine — generated by src/build.py from src/config.json. Do not edit by hand. */',
        f'@font-face{{font-family:P;src:url(data:font/woff2;base64,{probe_font_b64()})}}',
        f':root{{--name:{json.dumps(CFG["default_name"])}}}',
        '',
        '/* Active only when the probe clock exists and nothing would make it unreliable;',
        '   otherwise Bonjourr\'s own greeting stays. */',
        '[lang^=en] body:has([data-index="1"]):not(:has(#main.hidden,#greetings.he_hidden,#time.hidden,#time.is-analog,'
        '#time-container.he_hidden,[data-ampm],.auto.clock-date,.cn.clock-date)){--X:visible;--Y:hidden;--P:static}',
        '#greetings{visibility:var(--Y,visible);anchor-name:--g}  /* keeps its space; we draw on top of it */',
        '#time{position:var(--P,relative)}',
        '.clock-region{display:none}',
        '',
        '/* Probe = Bonjourr\'s 2nd world clock. Hour, minute digit and weekday become box sizes. */',
        '[data-index="1"]{position:absolute;position-anchor:--g;position-visibility:always;top:anchor(bottom);'
        'left:anchor(center);display:grid!important;visibility:hidden;',
        '  >:not(.digital,.clock-date),.clock-date>:nth-child(n+2),.digital>:not([class$=h],[class$=m]),.digital-pm{display:none!important}',
        '  .digital,.digital-ampm{font:inherit}',
        '  .digital,.clock-date,.digital>*{grid-area:1/1;margin:0;line-height:0}',
        '  .digital-hh,.digital-mm{font:80px/0 P}',
        '  .clock-date{font:80px/0 P!important}',
        '  .digital{display:grid;place-content:start;container:d/inline-size}',
        '  .digital-mm{writing-mode:sideways-lr;font-feature-settings:"ss01"}',
        '  .digital-ampm{display:block!important;container:t/size}',
        '  .digital-am{display:block!important}',
        '  /* The greeting itself. The transition freezes it for the life of the tab. */',
        '  .digital-am:after{content:none;display:none;position:absolute;left:0;translate:-50% -100%;white-space:nowrap;',
        '    visibility:var(--X,hidden);font-size:var(--greeting-size);line-height:normal;transition:content 1e9s allow-discrete}',
        '}',
        '',
        '/* Greetings */',
        ':root{',
    ]
    for k, g in G.items():
        lines.append(f'  --{ids[k]}:{text_css(g["text"] + " ")} {image_css(g["emoji"])};  /* {k} */')
    lines.append('}')
    lines.append('')
    S = lambda slots: ';'.join(f'--{i}:var(--{ids[v]})' for i, v in slots)
    rules = ['display:block;content:var(--0);']  # the ';' matters: without it the next nested rule is swallowed
    lines.append('/* Slots: 10 per period, picked by the last digit of the minute the tab was opened */')
    for p in CFG['periods']:
        rules.append(f'@container {hours(p["from"], p["to"])}{{{S(enumerate(p["slots"]))}}}')
    for o in CFG['day_overrides']:
        c = DAYCODE[o['day']]
        rules.append(f'@container d ({U * c - 2}px<width<{U * c + 2}px){{@container {hours(o["from"], o["to"])}'
                     f'{{{S((int(i), v) for i, v in o["slots"].items())}}}}}')
    for i in range(1, 10):
        rules.append(f'@container (height>{U * i - 2}px){{content:var(--{i})}}')
    lines.append('[data-index] .digital-am:after{@container d (width<30px){')
    lines += ['  ' + r for r in rules]
    lines.append('}}')
    return '\n'.join(lines) + '\n'


def img_src(e):
    k = kind(e)
    if k == 'ms':
        return emoji_file(e, 1)
    if k == 'teams':
        return EP + TEAMS[e]
    return f'{EP}microsoft-3D-fluent/{EP3D}/{EP_SLUG[e]}_{cp(e)}.png'


def build_preview():
    """PREVIEW.md: every greeting with its emoji, and the schedule (GitHub renders it)."""
    G, name = CFG['greetings'], CFG['default_name']
    src = {'ms': 'Microsoft animated (re-hosted)', 'teams': 'Teams animated (Emojipedia)', '3d': '3D Fluent (Emojipedia)'}
    out = ['# Greeting preview', '',
           '_Generated by `src/build.py` from `src/config.json`. Do not edit by hand._', '',
           '| | Greeting | id | Emoji source |', '|---|---|---|---|']
    for k, g in G.items():
        out.append(f'| <img src="{img_src(g["emoji"])}" width="{PX}" height="{PX}" alt="{g["emoji"]}"> '
                   f'| {g["text"].replace("{name}", name)} | `{k}` | {src[kind(g["emoji"])]} |')
    out += ['', '## Schedule', '',
            'The slot is the last digit of the minute the tab was opened (repeats make a greeting more likely).', '',
            '| Hours | ' + ' | '.join(f':x{i}' for i in range(10)) + ' |', '|---' * 11 + '|']
    for p in CFG['periods']:
        out.append(f'| {p["from"]:02}–{p["to"]:02} {p["id"]} | ' + ' | '.join(f'`{v}`' for v in p['slots']) + ' |')
    for o in CFG['day_overrides']:
        out.append(f'| {o["day"]} {o["from"]:02}–{o["to"]:02} | '
                   + ' | '.join(f'`{o["slots"][str(i)]}`' if str(i) in o['slots'] else '' for i in range(10)) + ' |')
    (ROOT / 'PREVIEW.md').write_text('\n'.join(out) + '\n', encoding='utf-8')


if __name__ == '__main__':
    validate()
    build_emoji()
    tidy_emoji()
    css = build_css()
    (ROOT / 'greetings.css').write_text(css, encoding='utf-8')
    build_preview()
    print(f'greetings.css {len(css)} chars, PREVIEW.md written')
