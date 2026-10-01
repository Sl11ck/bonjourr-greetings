#!/usr/bin/env python3
"""Build greetings.css, PREVIEW.md and the emoji images for the Bonjourr greeting engine.

    pip install -r src/requirements.txt
    python src/build.py              # normal build (re-uses src/emoji-lock.json)
    python src/build.py --refresh    # look up every emoji again (newer designs, changed precedence)
    python src/build.py --force      # also re-download and re-encode every image

What is shown, and when, lives in greetings.csv.  How emoji are found lives in src/config.json.
"""
import base64, csv, io, json, os, re, shutil, subprocess, sys, urllib.parse, urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / 'src/config.json').read_text(encoding='utf-8'))
TABLE = ROOT / 'greetings.csv'
LOCK = ROOT / 'src/emoji-lock.json'
CACHE = ROOT / 'src/.cache'
EMOJI_DIR = ROOT / 'emoji'
FORCE = '--force' in sys.argv
REFRESH = FORCE or '--refresh' in sys.argv
CI = os.environ.get('GITHUB_ACTIONS') == 'true'

PX = CFG['emoji_size_css_px']                 # displayed emoji size in CSS px
SCALES = CFG['emoji_scales']                  # one file per screen scale -> the browser never resizes an animation
QUALITY = CFG['emoji_quality']                # AVIF quality (92 = visually lossless)
STYLES = CFG['emoji_styles']                  # e.g. ["3d-animated", "3d", "2d", "system"]
SOURCES = CFG['emoji_sources']                # per style: which source to try first
JSDELIVR_LIMIT_MB = 50                        # jsDelivr refuses GitHub repos bigger than this

SLOTS = 60                                    # one slot per minute of the hour the tab was opened
DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
DAYCODE = {'Mon': 1, 'Tue': 2, 'Wed': 3, 'Thu': 4, 'Fri': 5, 'Sun': 6, 'Sat': 7}   # widths in the probe font
U = 1                                         # probe: px per hour / weekday code / minute

ALL_STYLES = ('3d-animated', '3d', '2d', 'system')
ALL_SOURCES = ('microsoft', 'emojipedia')
UA = {'User-Agent': 'Mozilla/5.0 (bonjourr-greetings build script)'}
WARNINGS = []


def warn(msg):
    WARNINGS.append(msg)
    print(f'::warning::{msg}' if CI else f'WARNING: {msg}', flush=True)


# ── greetings.csv ────────────────────────────────────────────────────────────
DAYNAME = {d.lower(): i for i, d in enumerate(DAYS)}
DAYNAME.update({n: i for i, n in enumerate(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])})
DAYGROUP = {'': range(7), '*': range(7), 'all': range(7), 'daily': range(7), 'everyday': range(7),
            'weekdays': range(5), 'weekday': range(5), 'weekend': range(5, 7), 'weekends': range(5, 7)}


def parse_days(s):
    s = s.strip().lower()
    if s in DAYGROUP:
        return set(DAYGROUP[s])
    out = set()
    for part in filter(None, re.split(r'[\s,;/]+', s)):
        a, _, b = part.partition('-')
        if a not in DAYNAME or (b and b not in DAYNAME):
            raise ValueError(f'unknown day "{part}" (use Mon … Sun, Mon-Fri, weekdays, weekend or *)')
        i, j = DAYNAME[a], DAYNAME[b or a]
        while True:
            out.add(i)
            if i == j: break
            i = (i + 1) % 7
    return out


def parse_hours(s):
    """-> {(day offset, hour)}. The part of a range after midnight belongs to the next day."""
    s = s.strip().lower()
    if s in ('', '*', 'all', 'any'):
        return {(0, h) for h in range(24)}
    out = set()
    for part in filter(None, re.split(r'[\s,;]+', s)):
        m = re.fullmatch(r'(\d{1,2})(?::00)?(?:-(\d{1,2})(?::00)?)?', part)
        if not m:
            raise ValueError(f'bad hours "{part}" (use 05-12, 21-02, 7 or *)')
        a = int(m[1]); b = int(m[2]) if m[2] else a + 1
        if not (0 <= a <= 23 and 0 <= b <= 24) or a == b:
            raise ValueError(f'bad hours "{part}" (hours run 00-24; the end hour is not included)')
        out.update((0, h) for h in range(a, b)) if a < b else \
            out.update([*((0, h) for h in range(a, 24)), *((1, h) for h in range(0, b))])
    return out


def parse_styles(s):
    s = s.strip().lower()
    if not s:
        return tuple(STYLES)
    st = tuple(filter(None, re.split(r'[\s,;>]+', s)))
    bad = [x for x in st if x not in ALL_STYLES]
    if bad:
        raise ValueError(f'unknown style "{bad[0]}" (use {", ".join(ALL_STYLES)})')
    return st


def load_table():
    rows, err = [], []
    text = TABLE.read_text(encoding='utf-8-sig')   # tolerate the BOM Excel adds
    reader = csv.DictReader(io.StringIO(text), skipinitialspace=True)
    reader.fieldnames = [(f or '').strip().lower() for f in reader.fieldnames or []]
    missing = {'greeting', 'emoji', 'days', 'hours', 'weight'} - set(reader.fieldnames)
    if missing:
        sys.exit(f'greetings.csv: missing column(s) {", ".join(sorted(missing))}. '
                 'The first line must be: greeting,emoji,days,hours,weight,style')
    for n, r in enumerate(reader, start=2):
        r = {k: (v or '').strip() for k, v in r.items() if k}
        if not any(r.values()) or r['greeting'].startswith('#'):
            continue                                   # blank line or comment
        try:
            if not r['greeting']:
                raise ValueError('the greeting is empty')
            if re.search(r'[\x00-\x1f\\]', r['greeting']):
                raise ValueError('the greeting may not contain line breaks or backslashes')
            w = float(r['weight'] or 1)
            if w < 0:
                raise ValueError('weight must be 0 or more')
            rows.append({'line': n, 'text': r['greeting'], 'emoji': r['emoji'].replace(' ', ''),
                         'days': parse_days(r['days']), 'hours': parse_hours(r['hours']), 'weight': w,
                         'styles': parse_styles(r.get('style', ''))})
        except ValueError as e:
            err.append(f'line {n}: {e}')
    if err:
        sys.exit('greetings.csv problems:\n  ' + '\n  '.join(err))
    return rows


def key(r):
    return (r['text'], r['emoji'], r['styles'])


# ── schedule: weights -> 60 minute slots for every weekday and hour ─────────
def quantize(pool):
    """Largest-remainder rounding of weights to SLOTS whole slots."""
    total = sum(pool.values())
    exact = {k: w * SLOTS / total for k, w in pool.items()}
    counts = {k: int(x) for k, x in exact.items()}
    order = sorted(pool, key=lambda k: -(exact[k] - counts[k]))      # stable: ties keep table order
    for k in order[:SLOTS - sum(counts.values())]:
        counts[k] += 1
    return counts


def interleave(counts):
    """Spread each greeting over the hour (smooth weighted round-robin), so neighbouring minutes differ."""
    cur, out = dict.fromkeys(counts, 0), []
    for _ in range(SLOTS):
        for k, c in counts.items():
            cur[k] += c
        best = max(counts, key=lambda k: cur[k])                       # first max wins -> deterministic
        cur[best] -= SLOTS
        out.append(best)
    return out


def build_schedule(rows):
    sched, gaps, starved = {}, [], set()
    for d in range(7):
        for h in range(24):
            pool = {}
            for r in rows:
                if r['weight'] > 0 and any((d - o) % 7 in r['days'] for o, hh in r['hours'] if hh == h):
                    pool[key(r)] = pool.get(key(r), 0) + r['weight']
            if not pool:
                gaps.append((d, h)); continue
            counts = quantize(pool)
            starved |= {(k[0], d, h) for k, c in counts.items() if c == 0}
            sched[d, h] = interleave({k: c for k, c in counts.items() if c})
    if gaps:
        sys.exit('greetings.csv: no greeting covers ' + ', '.join(
            f'{DAYS[d]} {a:02}-{b:02}' for d, a, b in runs(gaps)) + '. Add a row for those times.')
    for text in sorted({s[0] for s in starved}):
        warn(f'"{text}" has too small a weight to ever show at some times (under 1 in {SLOTS * 2}).')
    return sched


def runs(cells):
    """[(d,h)] -> [(d, start, end)] runs of consecutive hours."""
    out = []
    for d, h in sorted(cells):
        if out and out[-1][0] == d and out[-1][2] == h:
            out[-1] = (d, out[-1][1], h + 1)
        else:
            out.append((d, h, h + 1))
    return out


# ── emoji lookup ─────────────────────────────────────────────────────────────
# microsoft  = github.com/microsoft/fluentui-emoji(-animated), MIT: downloaded, resized, committed to emoji/
# emojipedia = Emojipedia's newest Microsoft designs: linked to (not re-hosted; they carry no open licence)
MS_REPOS = {'static': 'fluentui-emoji', 'animated': 'fluentui-emoji-animated'}
EP_VENDOR = {'3d-animated': 'microsoft-teams', '3d': 'microsoft-3D-fluent', '2d': 'microsoft'}


def norm(e):
    return e.replace('️', '').replace('︎', '')


def cp(e):
    return '-'.join(f'{ord(c):x}' for c in e)


def http(url, binary=True):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        data = r.read()
        return (data if binary else data.decode('utf-8', 'replace')), r.geturl()


_ms = {}
def ms_index(repo):
    """{emoji: {'folder': ..., 'files': [...]}} from a sparse, blob-less clone (metadata.json only, ~2 s)."""
    if repo in _ms:
        return _ms[repo]
    d = CACHE / 'repos' / repo
    if REFRESH and d.exists():
        shutil.rmtree(d)
    if not d.exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', '-q', '--depth', '1', '--filter=blob:none', '--sparse',
                        f'https://github.com/microsoft/{repo}', str(d)], check=True)
        subprocess.run(['git', '-C', str(d), 'sparse-checkout', 'set', '--no-cone', '/assets/*/metadata.json'], check=True)
    files = subprocess.run(['git', '-C', str(d), 'ls-tree', '-r', '--name-only', 'HEAD', 'assets/'],
                           check=True, capture_output=True, text=True).stdout.splitlines()
    by_folder = {}
    for f in files:
        by_folder.setdefault(f.split('/')[1], []).append(f)
    idx = {}
    for folder, fl in by_folder.items():
        meta = d / 'assets' / folder / 'metadata.json'
        if meta.exists():
            g = json.loads(meta.read_text(encoding='utf-8')).get('glyph', '')
            idx[norm(g)] = {'folder': folder, 'files': fl}
    _ms[repo] = idx
    return idx


def ms_file(e, repo, sub, ext):
    """Path of the default-skin-tone file in a style sub-folder (3D / Color / animated), or None."""
    hit = ms_index(repo).get(norm(e))
    if not hit:
        return None, None
    for f in hit['files']:
        parts = f.split('/')
        if f.endswith(ext) and parts[-2] == sub and (len(parts) == 4 or parts[2] == 'Default'):
            return f, hit['folder']
    return None, None


def ms_download(repo, path):
    base = f'https://raw.githubusercontent.com/microsoft/{repo}/main/'
    data, _ = http(base + urllib.parse.quote(path))
    if data.startswith(b'version https://git-lfs'):           # big files live in Git LFS
        data, _ = http(f'https://media.githubusercontent.com/media/microsoft/{repo}/main/' + urllib.parse.quote(path))
    return data


_ep = {}
def emojipedia(e):
    """Newest Emojipedia image per Microsoft vendor: {'microsoft-teams': url, ...}."""
    if e in _ep:
        return _ep[e]
    try:
        page, final = http('https://emojipedia.org/' + urllib.parse.quote(e), binary=False)
    except Exception as x:
        warn(f'Emojipedia lookup failed for {e} ({x}); falling back to other sources.')
        _ep[e] = {}; return {}
    slug = final.rstrip('/').rsplit('/', 1)[-1]
    best = {}
    for vendor, ver, name in re.findall(r'source/(microsoft(?:-teams|-3D-fluent)?)/(\d+)/([\w.-]+\.png)', page):
        score = (name.startswith(slug + '_'), int(ver))           # prefer this page's emoji, then newest
        if vendor not in best or score > best[vendor][0]:
            best[vendor] = (score, f'https://em-content.zobj.net/source/{vendor}/{ver}/{name}')
    _ep[e] = {v: u for v, (s, u) in best.items() if s[0]}
    return _ep[e]


def image_info(data):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    return im.size[0], getattr(im, 'n_frames', 1)


def candidate(e, style, source):
    if source == 'microsoft':
        if style == '3d-animated':
            path, folder = ms_file(e, MS_REPOS['animated'], 'animated', '.png')
            if path:
                return {'kind': 'ms-anim', 'repo': MS_REPOS['animated'], 'path': path, 'name': slugify(folder)}
        if style == '3d':
            path, folder = ms_file(e, MS_REPOS['static'], '3D', '.png')
            if path:
                return {'kind': 'ms-3d', 'repo': MS_REPOS['static'], 'path': path, 'name': slugify(folder)}
        if style == '2d':
            path, folder = ms_file(e, MS_REPOS['static'], 'Color', '.svg')
            if path:
                return {'kind': 'ms-svg', 'repo': MS_REPOS['static'], 'path': path, 'name': slugify(folder)}
        return None
    url = emojipedia(e).get(EP_VENDOR[style])
    if not url:
        return None
    try:
        px, frames = image_info(http(url)[0])
    except Exception as x:
        warn(f'could not load {url} ({x})'); return None
    if style == '3d-animated' and frames < 2:
        return None                                    # a still Teams design is not an animation
    return {'kind': 'link', 'url': url, 'px': px}


def slugify(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')


def resolve(e, styles):
    for style in styles:
        if style == 'system':
            break
        for source in SOURCES.get(style, []):
            c = candidate(e, style, source)
            if c:
                return {'style': style, 'source': source, **c}
    return {'style': 'system', 'source': 'system font', 'kind': 'text'}


def resolve_all(rows):
    """Look up each emoji once; results are kept in src/emoji-lock.json until the precedence changes."""
    settings = {'emoji_sources': SOURCES}
    old = {} if REFRESH or not LOCK.exists() else json.loads(LOCK.read_text(encoding='utf-8'))
    if old.pop('_settings', None) != settings:
        old = {}                                       # source precedence changed: look everything up again
    lock = {}
    for r in rows:
        if not r['emoji'] or (r['emoji'] + '|' + ' '.join(r['styles'])) in lock:
            continue
        k = r['emoji'] + '|' + ' '.join(r['styles'])
        lock[k] = old.get(k) or resolve(r['emoji'], r['styles'])
        if k not in old:
            print(f'  {r["emoji"]}  -> {lock[k]["style"]} from {lock[k]["source"]}', flush=True)
    LOCK.write_text(json.dumps({'_settings': settings, **dict(sorted(lock.items()))}, ensure_ascii=False, indent=1) + '\n',
                    encoding='utf-8')
    return lock


# ── re-hosted images ─────────────────────────────────────────────────────────
def files_for(res):
    if res['kind'] == 'ms-anim':
        return [f'emoji/{res["name"]}@{s:g}x.avif' for s in SCALES]
    if res['kind'] == 'ms-3d':
        return [f'emoji/{res["name"]}-3d@{s:g}x.avif' for s in SCALES]
    if res['kind'] == 'ms-svg':
        return [f'emoji/{res["name"]}-2d.svg']
    return []


def up_to_date(res):
    from PIL import Image
    if FORCE:
        return False
    for f, s in zip(files_for(res), SCALES):
        try:
            im = Image.open(ROOT / f)
            if im.size != (round(PX * s),) * 2 or (res['kind'] == 'ms-anim') != (getattr(im, 'n_frames', 1) > 1):
                return False
        except OSError:
            return False
    return all((ROOT / f).exists() for f in files_for(res))


def source_file(res):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / re.sub(r'[^\w.-]', '_', res['repo'] + '__' + res['path'])
    if FORCE or not f.exists():
        print('  download', res['path'], flush=True)
        f.write_bytes(ms_download(res['repo'], res['path']))
    return f


def encode(res):
    """Lanczos-resize every frame to each screen scale; save as AVIF (4:4:4, full colour)."""
    from PIL import Image, ImageSequence
    src = Image.open(source_file(res))
    frames = [(f.convert('RGBA').copy(), int(round(f.info.get('duration', 42)))) for f in ImageSequence.Iterator(src)]
    if res['kind'] == 'ms-3d':
        frames = frames[:1]
    for f, s in zip(files_for(res), SCALES):
        px = round(PX * s)
        imgs = [fr.resize((px, px), Image.LANCZOS) for fr, _ in frames]
        out = ROOT / f; tmp = out.with_suffix('.tmp')
        kw = dict(save_all=True, append_images=imgs[1:], duration=[d for _, d in frames], loop=0) if len(imgs) > 1 else {}
        imgs[0].save(tmp, 'AVIF', quality=QUALITY, speed=4, subsampling='4:4:4', **kw)
        os.replace(tmp, out)
    return f'  {res["name"]} ({res["kind"]}): ' + ' / '.join(f'{(ROOT / f).stat().st_size // 1024} KB' for f in files_for(res))


def build_images(lock):
    from PIL import features
    EMOJI_DIR.mkdir(exist_ok=True)
    todo = []
    for res in {json.dumps(v, sort_keys=True): v for v in lock.values()}.values():
        if res['kind'] == 'ms-svg':
            out = ROOT / files_for(res)[0]
            if FORCE or not out.exists():
                out.write_bytes(source_file(res).read_bytes())
        elif res['kind'] in ('ms-anim', 'ms-3d') and not up_to_date(res):
            todo.append(res)
    if todo:
        if not features.check('avif'):
            sys.exit('Pillow was built without AVIF support: pip install -U "pillow>=12"')
        for res in todo:
            source_file(res)                       # download first (sequential), then encode in parallel
        with ProcessPoolExecutor() as pool:
            for line in pool.map(encode, todo):
                print(line, flush=True)
    keep = {ROOT / f for res in lock.values() for f in files_for(res)}
    for f in EMOJI_DIR.glob('*.*'):
        if f.suffix in ('.avif', '.webp', '.svg', '.tmp') and f not in keep:
            f.unlink()
    mb = sum(f.stat().st_size for f in keep if f.exists()) / 1e6
    print(f'emoji/ {mb:.1f} MB')
    if mb > JSDELIVR_LIMIT_MB - 8:
        warn(f'emoji/ is {mb:.0f} MB; jsDelivr serves repos up to {JSDELIVR_LIMIT_MB} MB. '
             'Lower emoji_quality or drop a scale in src/config.json.')


def image_css(res):
    if res['kind'] in ('ms-anim', 'ms-3d'):
        return 'image-set(' + ','.join(f'url({f}) {s:g}x' for f, s in zip(files_for(res), SCALES)) + ')'
    if res['kind'] == 'ms-svg':
        return f'image-set(url({files_for(res)[0]}) {32 / PX:.4g}x)'      # Microsoft's SVGs are 32x32
    return f'image-set(url({res["url"]}) {res["px"] / PX:.4g}x)'


def img_src(res):
    if res['kind'] in ('ms-anim', 'ms-3d', 'ms-svg'):
        return files_for(res)[0]
    return res['url']


# ── probe font: hour / minute / weekday text -> exact box sizes ─────────────
def probe_font_b64():
    """At 20px: each hour, minute and weekday code adds exactly 1px (50 font units)."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
    from fontTools.misc.timeTools import timestampFromString
    S = 50
    w = {'M': 1, 'T': 2, 'h': 2, 'W': 3, 'F': 5, 'S': 6, 't': 1}   # Mon1 Tue2 Wed3 Thu4 Fri5 Sun6 Sat7
    order = ['.notdef', 'z'] + [f'd{k}' for k in range(1, 10)] + [f'L{c}' for c in w]
    cmap = {ord('0'): 'z', **{ord(str(k)): f'd{k}' for k in range(1, 10)}, **{ord(c): f'L{c}' for c in w}}
    for c in 'ondayuesri':
        cmap[ord(c)] = 'z'
    adv = {'.notdef': 0, 'z': 0, **{f'd{k}': k * S for k in range(1, 10)}, **{f'L{c}': v * S for c, v in w.items()}}
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
    # Two-digit numbers: the tens digit counts 10x ("47" = 4*50 + 1800 + 7*50 = 47*50 units).
    addOpenTypeFeaturesFromString(fb.font, f"""languagesystem DFLT dflt; languagesystem latn dflt; @D={D};
        feature kern {{ pos d1 @D 450; pos d2 @D 900; pos d3 @D 1350; pos d4 @D 1800; pos d5 @D 2250; }} kern;""")
    fb.font['head'].created = fb.font['head'].modified = timestampFromString('Thu Jan  1 00:00:00 2026')
    fb.font.recalcTimestamp = False                   # identical output every build
    fb.font.flavor = 'woff2'; b = io.BytesIO(); fb.font.save(b)
    return base64.b64encode(b.getvalue()).decode()


# ── CSS ──────────────────────────────────────────────────────────────────────
def q_hours(a, b):
    c = []
    if a > 0: c.append(f'(width>{U * a - U / 2:g}px)')
    if b < 24: c.append(f'(width<{U * b - U / 2:g}px)')
    return ' and '.join(c) or '(width>=0px)'


def q_day(d):
    c = DAYCODE[DAYS[d]]
    return f'({U * c - U / 2:g}px<width<{U * c + U / 2:g}px)'


def text_css(t):
    parts, out = t.split('{name}'), []
    for i, p in enumerate(parts):
        if p: out.append(json.dumps(p, ensure_ascii=False))
        if i < len(parts) - 1: out.append('var(--name)')
    return ' '.join(out)


def greeting_css(k, lock):
    text, emoji, styles = k
    if not emoji:
        return text_css(text)
    res = lock[emoji + '|' + ' '.join(styles)]
    if res['kind'] == 'text':
        return text_css(f'{text} {emoji}')
    return f'{text_css(text + " ")} {image_css(res)}'


def build_css(sched, lock):
    keys = list(dict.fromkeys(k for slots in sched.values() for k in slots))
    gid = {k: f'g{i}' for i, k in enumerate(keys)}
    S = lambda pairs: ';'.join(f'--{i}:var(--{gid[k]})' for i, k in pairs)

    # Base = the most common slot list per hour; days that differ only add the slots that change.
    rules, base = [], {}
    for h in range(24):
        lists = [tuple(sched[d, h]) for d in range(7)]
        base[h] = max(lists, key=lists.count)
    h = 0
    while h < 24:
        e = h
        while e + 1 < 24 and base[e + 1] == base[h]: e += 1
        rules.append(f'@container {q_hours(h, e + 1)}{{{S(enumerate(base[h]))}}}')
        h = e + 1
    for d in range(7):
        diffs = [tuple((i, k) for i, k in enumerate(sched[d, h]) if k != base[h][i]) for h in range(24)]
        h = 0
        while h < 24:
            e = h
            while e + 1 < 24 and diffs[e + 1] == diffs[h]: e += 1
            if diffs[h]:
                rules.append(f'@container d {q_day(d)}{{@container {q_hours(h, e + 1)}{{{S(diffs[h])}}}}}')
            h = e + 1
    for i in range(1, SLOTS):
        rules.append(f'@container (height>{U * i - U / 2:g}px){{content:var(--{i})}}')

    lines = [
        '/* Bonjourr greeting engine. Generated by src/build.py from greetings.csv. Do not edit by hand. */',
        f'@font-face{{font-family:P;src:url(data:font/woff2;base64,{probe_font_b64()})}}',
        f':root{{--name:{json.dumps(CFG["default_name"], ensure_ascii=False)}}}',
        '',
        '/* Active only when the probe clock exists and nothing would make it unreliable;',
        '   otherwise Bonjourr\'s own greeting stays. */',
        '[lang^=en] body:has([data-index="1"]):not(:has(#main.hidden,#greetings.he_hidden,#time.hidden,#time.is-analog,'
        '#time-container.he_hidden,[data-ampm],.auto.clock-date,.cn.clock-date)){--X:visible;--Y:hidden;--P:static}',
        '#greetings{visibility:var(--Y,visible);anchor-name:--g}  /* keeps its space; we draw on top of it */',
        '#time{position:var(--P,relative)}',
        '.clock-region{display:none}',
        '',
        '/* Probe = Bonjourr\'s 2nd world clock: hour -> width, minute -> height, weekday -> width (1px each). */',
        '[data-index="1"]{position:absolute;position-anchor:--g;position-visibility:always;top:anchor(bottom);'
        'left:anchor(center);display:grid!important;visibility:hidden;',
        '  >:not(.digital,.clock-date),.clock-date>:nth-child(n+2),.digital>:not([class$=h],[class$=m]),.digital-pm{display:none!important}',
        '  .digital,.digital-ampm{font:inherit}',
        '  .digital,.clock-date,.digital>*{grid-area:1/1;margin:0;line-height:0}',
        f'  .digital-hh,.digital-mm{{font:{20 * U}px/0 P;font-kerning:normal;text-rendering:optimizeLegibility;letter-spacing:0}}',
        f'  .clock-date{{font:{20 * U}px/0 P!important;letter-spacing:0!important}}',
        '  .digital{display:grid;place-content:start;container:d/inline-size}',
        '  .digital-mm{writing-mode:sideways-lr}',
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
    for k in keys:
        lines.append(f'  --{gid[k]}:{greeting_css(k, lock)};')
    lines += ['}', '', f'/* {SLOTS} slots per weekday and hour, picked by the minute the tab was opened */',
              f'[data-index] .digital-am:after{{@container d (width<{U * 7.5:g}px){{',
              '  display:block;content:var(--0);']   # the ';' matters: without it the next nested rule is swallowed
    lines += ['  ' + r for r in rules]
    lines.append('}}')
    return '\n'.join(lines) + '\n'


# ── PREVIEW.md ───────────────────────────────────────────────────────────────
def fmt_days(ds):
    ds = sorted(ds)
    if ds == list(range(7)): return 'Every day'
    if ds == list(range(5)): return 'Mon–Fri'
    if ds == [5, 6]: return 'Sat–Sun'
    out, i = [], 0
    while i < len(ds):
        j = i
        while j + 1 < len(ds) and ds[j + 1] == ds[j] + 1: j += 1
        out.append(DAYS[ds[i]] + ('–' + DAYS[ds[j]] if j > i else ''))
        i = j + 1
    return ', '.join(out)


def build_preview(rows, sched, lock):
    name = CFG['default_name']
    def img(r):
        if not r['emoji']:
            return ''
        res = lock[r['emoji'] + '|' + ' '.join(r['styles'])]
        if res['kind'] == 'text':
            return r['emoji']
        return f'<img src="{img_src(res)}" width="{PX}" height="{PX}" alt="{r["emoji"]}">'
    out = ['# Greeting preview', '',
           '_Generated by `src/build.py` from `greetings.csv`. Do not edit by hand._', '',
           '## Greetings', '', '| | Greeting | Emoji style · source |', '|---|---|---|']
    seen = set()
    for r in rows:
        if key(r) in seen: continue
        seen.add(key(r))
        res = lock.get(r['emoji'] + '|' + ' '.join(r['styles'])) if r['emoji'] else None
        out.append(f'| {img(r)} | {r["text"].replace("{name}", name)} | '
                   + (f'{res["style"]} · {res["source"]}' if res else '—') + ' |')
    out += ['', '## Chances', '', 'Share of new tabs that get each greeting, by weekday and hour.', '']
    blocks = {}
    for d in range(7):
        h = 0
        while h < 24:
            e = h
            while e + 1 < 24 and sched[d, e + 1] == sched[d, h]: e += 1
            blocks.setdefault((h, e + 1, tuple(sched[d, h])), set()).add(d)
            h = e + 1
    for (a, b, slots), ds in sorted(blocks.items(), key=lambda x: (x[0][0], min(x[1]))):
        counts = {}
        for k in slots: counts[k] = counts.get(k, 0) + 1
        parts = ', '.join(f'{k[0].replace("{name}", name)} {c * 100 / SLOTS:.0f}%'
                          for k, c in sorted(counts.items(), key=lambda x: -x[1]))
        out.append(f'- **{fmt_days(ds)} {a:02}–{b:02}**: {parts}')
    (ROOT / 'PREVIEW.md').write_text('\n'.join(out) + '\n', encoding='utf-8')


def export_schedule(sched):
    """Machine-readable schedule for tests: {"Mon-13": [text, emoji, ...60 slots]}."""
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / 'schedule.json').write_text(json.dumps(
        {f'{DAYS[d]}-{h}': [[k[0], k[1], ' '.join(k[2])] for k in slots] for (d, h), slots in sched.items()},
        ensure_ascii=False), encoding='utf-8')


def check_config():
    bad = [s for s in STYLES if s not in ALL_STYLES]
    bad += [f'emoji_sources.{st}' for st in SOURCES if st not in ALL_STYLES[:3]]
    bad += [f'source "{s}"' for v in SOURCES.values() for s in v if s not in ALL_SOURCES]
    if bad:
        sys.exit(f'src/config.json: unknown {", ".join(bad)}. Styles: {", ".join(ALL_STYLES)}; sources: {", ".join(ALL_SOURCES)}')


if __name__ == '__main__':
    check_config()
    rows = load_table()
    sched = build_schedule(rows)
    lock = resolve_all(rows)
    build_images(lock)
    css = build_css(sched, lock)
    (ROOT / 'greetings.css').write_text(css, encoding='utf-8')
    build_preview(rows, sched, lock)
    export_schedule(sched)
    print(f'greetings.css {len(css)} chars from {len(rows)} rows; PREVIEW.md written'
          + (f'; {len(WARNINGS)} warning(s)' if WARNINGS else ''))
