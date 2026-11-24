#!/usr/bin/env python3
"""GitHub profile README for Aamir1873: fetches live stats and renders the profile images.

Runs daily in GitHub Actions (.github/workflows/update-profile.yml), and locally:

    GH_TOKEN=$(gh auth token) python3 scripts/profile.py    # fetch and render
    python3 scripts/profile.py --cached                     # re-render from the last fetch

Only totals leave this script. No repository names go into the images, the README or the logs:
the token can see private repositories, and Actions logs on a public repository are public.
Standard library only, so the workflow needs no installs.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import math
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "profile"
CACHE = ROOT / "data" / "profile-stats.json"

# --------------------------------------------------------------------------- copy that rarely changes
NAME = "Aamir Abdul Kader"
ROLE = "AI & SOFTWARE ENGINEER  ·  DOHA, QATAR"
PITCH = "I build products end to end: architecture, cloud, AI and product."
NOW = "Now: AI Engineer at BOLD Architecture & Contracting"
SITE = "https://aamir.qzz.io"
LINKEDIN = "https://www.linkedin.com/in/aamir-abdul-kader/"
EMAIL = "aamir.abdulkader6@gmail.com"

# --------------------------------------------------------------------------- look
PAPER, EDGE, EMPTY = "#f5f0e6", "#e2dbcd", "#e7e0d2"
BLUE, TEXT, MUTED = "#2f56d6", "#283057", "#5b6078"
SERIF = "Iowan Old Style, Palatino Linotype, Palatino, Book Antiqua, Georgia, serif"
SANS = "Avenir Next, Avenir, Segoe UI, Helvetica Neue, Arial, sans-serif"

# =========================================================================== fetch
API = "https://api.github.com"


def call(url, token, payload=None):
    req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload else None, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "profile-stats"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, b""


def graphql(token, query, **variables):
    status, _, body = call(f"{API}/graphql", token, {"query": query, "variables": variables})
    data = json.loads(body or b"{}")
    if status != 200 or "errors" in data:
        sys.exit(f"GitHub GraphQL request failed (HTTP {status})")
    return data["data"]["viewer"]


def fetch(token):
    viewer = graphql(token, "query{viewer{login createdAt}}")
    login = viewer["login"]
    created = dt.datetime.fromisoformat(viewer["createdAt"].replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)

    # all-time contributions, one year at a time (the API caps each window at a year)
    window = "query($from:DateTime!,$to:DateTime!){viewer{contributionsCollection(from:$from,to:$to){contributionCalendar{totalContributions}}}}"
    all_time, start = 0, created
    while start < now:
        end = min(start + dt.timedelta(days=365) - dt.timedelta(seconds=1), now)
        cal = graphql(token, window, **{"from": start.isoformat(), "to": end.isoformat()})
        all_time += cal["contributionsCollection"]["contributionCalendar"]["totalContributions"]
        start = end + dt.timedelta(seconds=1)

    year = graphql(token, "query{viewer{contributionsCollection{contributionCalendar{totalContributions "
                          "weeks{contributionDays{date contributionCount contributionLevel}}}}}}")
    calendar = year["contributionsCollection"]["contributionCalendar"]

    repos, page = [], 1
    while True:
        status, _, body = call(f"{API}/user/repos?affiliation=owner,collaborator,organization_member&per_page=100&page={page}", token)
        batch = json.loads(body or b"[]") if status == 200 else []
        repos += batch
        if len(batch) < 100:
            break
        page += 1

    days = [d for w in calendar["weeks"] for d in w["contributionDays"]]
    streak = best = 0
    for d in days:
        streak = streak + 1 if d["contributionCount"] else 0
        best = max(best, streak)
    top = max(days, key=lambda d: d["contributionCount"])
    owned = [r for r in repos if r["owner"]["login"] == login]
    return {
        "updated": now.date().isoformat(), "joined": created.date().isoformat(),
        "all_time": all_time, "last_year": calendar["totalContributions"],
        "weeks": [[[d["date"], d["contributionCount"], d["contributionLevel"]] for d in w["contributionDays"]] for w in calendar["weeks"]],
        "active_days": sum(1 for d in days if d["contributionCount"]), "longest_streak": best,
        "best_day": [top["contributionCount"], top["date"]],
        "owned": len(owned), "public": sum(1 for r in owned if not r["private"]),
        "stars": sum(r["stargazers_count"] for r in owned if not r["private"]),
    }


# =========================================================================== draw
def n(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def esc(s):
    return html.escape(s, quote=False)


def text(x, y, s, size, fill=TEXT, *, family=SANS, weight=400, ls=0, anchor="start", italic=False):
    it = ' font-style="italic"' if italic else ""
    return (f'<text x="{n(x)}" y="{n(y)}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'letter-spacing="{ls}" fill="{fill}" text-anchor="{anchor}"{it}>{esc(s)}</text>')


def label(x, y, s, size=11.5, anchor="start", fill=BLUE):
    return text(x, y, s, size, fill, weight=700, ls=2.2, anchor=anchor)


B4 = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def patterns(u, cell=2):
    """Ordered-dither tints of the one blue ink (plain <pattern>s, so every browser draws them the same)."""
    out = []
    for name, k in (("12", 2), ("25", 4), ("50", 8), ("75", 12)):
        dots = "".join(f'<rect x="{x * cell}" y="{y * cell}" width="{cell}" height="{cell}"/>'
                       for y in range(4) for x in range(4) if B4[y][x] < k)
        out.append(f'<pattern id="{u}-p{name}" width="{4 * cell}" height="{4 * cell}" patternUnits="userSpaceOnUse">'
                   f'<g fill="{BLUE}">{dots}</g></pattern>')
    out.append(f'<pattern id="{u}-hz" width="6" height="6" patternUnits="userSpaceOnUse"><rect width="6" height="2" fill="{BLUE}"/></pattern>')
    out.append(f'<pattern id="{u}-dg" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
               f'<rect width="2" height="6" fill="{BLUE}"/></pattern>')
    return "".join(out)


def tint(u, kind, x, y, w, h, rx=0):
    """A shape in one of the blue tints: solid, a dither density, stripes, or an outline."""
    r = f'x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="{rx}"'
    if kind == "solid":
        return f'<rect {r} fill="{BLUE}"/>'
    if kind == "outline":
        return f'<rect x="{n(x + .75)}" y="{n(y + .75)}" width="{n(w - 1.5)}" height="{n(h - 1.5)}" rx="{rx}" fill="{EMPTY}" stroke="{BLUE}" stroke-width="1.5"/>'
    return f'<rect {r} fill="{EMPTY}"/><rect {r} fill="url(#{u}-{kind})"/>'


def card(x, y, w, h):
    return f'<rect x="{x + .5}" y="{y + .5}" width="{w - 1}" height="{h - 1}" rx="8" fill="{PAPER}" stroke="{EDGE}"/>'


def svg(name, w, h, u, body, alt):
    doc = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
           f'aria-label="{html.escape(alt)}"><title>{esc(alt)}</title><defs>{patterns(u)}</defs>{body}</svg>')
    (OUT / f"{name}.svg").write_text(doc)


def fmt(v):
    return f"{v:,}"


def date(iso, form="%-d %b %Y"):
    return dt.date.fromisoformat(iso).strftime(form)


# --------------------------------------------------------------------------- magnolia tree and flag (lo-fi dither)
EASE = ".42 0 .58 1"
SLOW = ".3 .1 .3 1"
QATAR_MAROON = "#8a1538"


def _bez(p0, p1, p2, p3, t):
    mt = 1 - t
    return (mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0],
            mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1])


def _near(lines, x, y, r):
    r2 = r * r
    for line in lines:
        for (ax, ay), (bx, by) in zip(line, line[1:]):
            dx, dy = bx - ax, by - ay
            ll = dx * dx + dy * dy
            t = 0 if not ll else max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / ll))
            px, py = ax + t * dx - x, ay + t * dy - y
            if px * px + py * py <= r2:
                return True
    return False


def _dots(tone, x0, x1, y0, y1, cell):
    """Ordered (4x4 Bayer) dither of a tone field into square ink pixels, as path data."""
    out, size = [], cell * .82
    for gy in range(int(math.floor(y0 / cell)) - 1, int(y1 // cell) + 1):
        for gx in range(int(math.floor(x0 / cell)) - 1, int(x1 // cell) + 1):
            t = tone(gx * cell + cell / 2, gy * cell + cell / 2)
            if t is None or t <= (B4[gy % 4][gx % 4] + .5) / 16:
                continue
            x, y = gx * cell + (cell - size) / 2, gy * cell + (cell - size) / 2
            out.append(f"M{n(x)} {n(y)}h{n(size)}v{n(size)}h{n(-size)}z")
    return "".join(out)


def _inside_poly(poly, x, y):
    hit, j = False, len(poly) - 1
    for i in range(len(poly)):
        (xi, yi), (xj, yj) = poly[i], poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


MAGNOLIA_PINK = "#b23a83"


def _cup_tepal(length=18, width=10.5, k=24):
    """A tulip-magnolia tepal pointing up (-y) from the base of the cup."""
    left, right = [], []
    for i in range(k + 1):
        t = i / k
        half = width / 2 * math.sin(math.pi * min(1, .06 + .94 * t)) ** .5 * (.5 + .5 * t)
        left.append((-half, -t * length))
        right.append((half, -t * length))
    return right + left[::-1]


CUP = _cup_tepal()


def _cup_tone(x, y):
    if not _inside_poly(CUP, x, y):
        return None
    if _near([CUP + CUP[:1]], x, y, 1.1):
        return 1
    t = min(1, -y / 18)
    return .9 * (1 - t) ** .9 + .1          # deep pink-purple at the base, pale toward the tip


def _tree(seed=21, depth=5):
    """Branch segments (start, end, width) and branch tips for a small multi-stemmed magnolia: it splits low
    into two stems and spreads into a rounded crown, like a saucer magnolia."""
    rnd = __import__("random").Random(seed)
    segs, tips = [], []

    def grow(x, y, ang, length, width, d):
        bend = rnd.uniform(-.12, .12)
        mx, my = x + length * .5 * math.cos(ang), y + length * .5 * math.sin(ang)
        ang2 = ang + bend
        x1, y1 = mx + length * .5 * math.cos(ang2), my + length * .5 * math.sin(ang2)
        segs.extend([((x, y), (mx, my), width), ((mx, my), (x1, y1), width * .9)])
        tips.append((x1, y1, ang2, d))
        if d == 0:
            return
        count = 2 if d > 3 else rnd.choice((2, 3, 3))
        for k in range(count):
            a = ang2 + (k - (count - 1) / 2) * rnd.uniform(.36, .58) + rnd.uniform(-.08, .08)
            a = max(-math.pi + .72, min(-.72, a))             # keep branches reaching up and out, never down
            grow(x1, y1, a, length * rnd.uniform(.74, .84), width * .68, d - 1)

    segs.append(((0, 4), (0, -10), 8))                         # a short trunk before it splits
    for stem in (-math.pi / 2 - .3, -math.pi / 2 + .26):
        grow(0, -10, stem, 29, 6.4, depth)
    return segs, tips


def _wood_tone(segs):
    def tone(x, y):
        for (ax, ay), (bx, by), w in segs:
            dx, dy = bx - ax, by - ay
            ll = dx * dx + dy * dy
            t = 0 if not ll else max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / ll))
            px, py = ax + t * dx - x, ay + t * dy - y
            if px * px + py * py <= (w / 2) ** 2:
                return 1
        return None
    return tone


def magnolia_tree(u, bx, by, scale, cell=2, seed=21, petals=6, blooms_max=40, spacing=11.5):
    """A small saucer-magnolia tree: dark dithered trunk and branches, tulip-shaped pink blooms that open from
    their own buds in a slow wave across the crown, and a few petals drifting to the ground."""
    segs, tips = _tree(seed)
    xs = [p[0] for s in segs for p in s[:2]]
    ys = [p[1] for s in segs for p in s[:2]]
    wood = _dots(_wood_tone(segs), min(xs) - 6, max(xs) + 6, min(ys) - 6, 4, cell)
    ground = _dots(lambda x, y: (.28 + .3 * (y + 6) / 6) if (x / 46) ** 2 + (y / 6) ** 2 <= 1 and y >= -6 else None,
                   -48, 48, -7, 2, cell)
    px = _dots(_cup_tone, -7, 7, -20, 1, cell * .5)
    cup = "M" + "L".join(f"{n(x)} {n(y)}" for x, y in CUP) + "Z"
    pale = _dots(lambda x, y: (lambda t: None if t is None else (1 if t == 1 else t * .55))(_cup_tone(x, y)), -7, 7, -20, 1, cell * .5)
    defs = (f'<path id="{u}-cup" d="{cup}" fill="{PAPER}"/>'
            f'<path id="{u}-cuppx" d="{px}" fill="{MAGNOLIA_PINK}"/>'
            f'<path id="{u}-cuppale" d="{pale}" fill="{MAGNOLIA_PINK}"/>')
    use = f'<use href="#{u}-cup" xlink:href="#{u}-cup"/><use href="#{u}-cuppx" xlink:href="#{u}-cuppx"/>'
    use_pale = f'<use href="#{u}-cup" xlink:href="#{u}-cup"/><use href="#{u}-cuppale" xlink:href="#{u}-cuppale"/>'

    rnd = __import__("random").Random(seed + 1)
    candidates = [i for i, t in enumerate(tips) if t[3] <= 2 and t[1] < -42]
    rnd.shuffle(candidates)
    keep = []
    for i in sorted(candidates, key=lambda i: tips[i][3]):                  # outer tips first, then inner forks
        if all((tips[i][0] - tips[j][0]) ** 2 + (tips[i][1] - tips[j][1]) ** 2 >= spacing ** 2 for j in keep):
            keep.append(i)
        if len(keep) >= blooms_max:
            break
    order = sorted(keep, key=lambda i: (tips[i][1], tips[i][0]))              # open from the top of the crown down
    blooms = []
    for rank, i in enumerate(order):
        x, y, ang, _ = tips[i]
        tilt = math.degrees(ang + math.pi / 2) * .5 + rnd.uniform(-8, 8)
        size = rnd.uniform(.7, .88)
        opens = .6 + rank * (4.4 / max(1, len(order) - 1)) + rnd.uniform(-.25, .25)
        tepals, art = "", (use_pale if rnd.random() < .35 else use)
        openness = rnd.choice((1, 1, 1, .8, .62))                               # some stay half-open
        for a, layer in ((-17, 0), (17, 0), (-36, 1), (36, 1), (0, 1)):
            closed, final = a * .12, a * openness
            tepals += (f'<g transform="rotate({n(closed)})"><animateTransform attributeName="transform" type="rotate" '
                       f'from="{n(closed)}" to="{n(final)}" begin="{opens:.2f}s" dur="2.6s" fill="freeze" calcMode="spline" '
                       f'keyTimes="0;1" keySplines="{SLOW}"/>{art}</g>')
        swell = (f'<animateTransform attributeName="transform" type="scale" from=".62" to="1" begin="{max(0, opens - 1.4):.2f}s" '
                 f'dur="1.8s" fill="freeze" calcMode="spline" keyTimes="0;1" keySplines="{SLOW}"/>')
        blooms.append(f'<g transform="translate({n(x)} {n(y)}) rotate({n(tilt)}) scale({n(size)})">'
                      f'<g transform="scale(.62)">{swell}{tepals}</g></g>')

    falling = ""
    for k in range(petals):
        x, y, _, _ = tips[rnd.choice(keep)]
        drift, d = rnd.uniform(-26, 26), rnd.uniform(8, 12)
        begin = 7 + rnd.uniform(0, 9)
        falling += (f'<g opacity="0"><animate attributeName="opacity" values="0;.9;.9;0" keyTimes="0;.1;.8;1" dur="{d:.1f}s" '
                    f'begin="{begin:.1f}s" repeatCount="indefinite"/>'
                    f'<animateTransform attributeName="transform" type="translate" values="{n(x)} {n(y)};{n(x + drift)} -4" '
                    f'dur="{d:.1f}s" begin="{begin:.1f}s" repeatCount="indefinite"/>'
                    f'<g transform="rotate({rnd.randint(40, 140)}) scale(.38)">{use}</g></g>')
    sway = (f'<animateTransform attributeName="transform" type="rotate" values="0 0 0;.8 0 0;-.6 0 0;0 0 0" begin="7s" dur="12s" '
            f'repeatCount="indefinite" calcMode="spline" keyTimes="0;.4;.75;1" keySplines="{EASE};{EASE};{EASE}"/>')
    return (f'<defs>{defs}</defs><g transform="translate({bx} {by}) scale({scale})">'
            f'<path d="{ground}" fill="{BLUE}" opacity=".55"/>'
            f'<g>{sway}<path d="{wood}" fill="{TEXT}"/>{"".join(blooms)}</g>{falling}</g>')


def qatar_flag(x, y, w, cell=1.2):
    """Qatar's flag as a small dithered image: maroon dither, and a white band whose edge has exactly nine points.

    The serrated edge is drawn as an exact shape so all nine points stay sharp at this size; only the maroon
    area is dithered. Proportions follow the flag's 11:28 ratio.
    """
    h = w * 11 / 28
    base, tip = w * .25, w * .36                 # where the white band ends and how far its points reach
    pid = f"qa{int(x)}{int(y)}"
    dots = "".join(f'<rect x="{n(i * cell)}" y="{n(j * cell)}" width="{n(cell * .9)}" height="{n(cell * .9)}"/>'
                   for j in range(4) for i in range(4) if B4[j][i] < 13)
    pattern = (f'<pattern id="{pid}" width="{n(4 * cell)}" height="{n(4 * cell)}" patternUnits="userSpaceOnUse">'
               f'<g fill="{QATAR_MAROON}">{dots}</g></pattern>')
    edge = []
    for i in range(9):
        edge += [(base, h * i / 9), (tip, h * (i + .5) / 9)]
    edge.append((base, h))
    maroon = [(base, 0), (w, 0), (w, h)] + edge[::-1]
    d = "M" + "L".join(f"{n(x + px)} {n(y + py)}" for px, py in maroon) + "Z"
    return (f'<defs>{pattern}</defs><rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" fill="#ffffff"/>'
            f'<path d="{d}" fill="url(#{pid})"/>'
            f'<rect x="{n(x + .5)}" y="{n(y + .5)}" width="{n(w - 1)}" height="{n(h - 1)}" fill="none" stroke="{QATAR_MAROON}" stroke-width="1"/>')


# --------------------------------------------------------------------------- hero
def hero(s):
    u, W, H = "hero", 880, 300
    x, y, w, h = 8, 6, 864, 286
    body = [card(x, y, w, h),
            magnolia_tree(u, 762, 290, 1.7, cell=1.05, seed=17),
            qatar_flag(796, 20, 62),
            label(40, 82, ROLE),
            text(36, 158, NAME, 62, BLUE, family=SERIF, italic=True, ls=-1),
            text(40, 198, PITCH, 17),
            text(40, 234, NOW, 14, MUTED)]
    svg("hero", W, H, u, "".join(body), f"{NAME}, AI and software engineer in Doha, Qatar. {PITCH}")

    u, W, H = "hero-m", 440, 432
    x, y, w, h = 6, 6, 428, 420
    body = [card(x, y, w, h),
            magnolia_tree(u, 318, 424, .9, cell=1.3, seed=17, blooms_max=30),
            qatar_flag(372, 18, 46, cell=1),
            label(24, 44, "AI & SOFTWARE ENGINEER", 11), label(24, 63, "DOHA, QATAR", 11),
            text(21, 146, "Aamir", 52, BLUE, family=SERIF, italic=True, ls=-1),
            text(21, 198, "Abdul Kader", 52, BLUE, family=SERIF, italic=True, ls=-1),
            text(24, 236, "I build products end to end:", 16),
            text(24, 258, "architecture, cloud, AI and product.", 16),
            text(24, 288, NOW, 13, MUTED)]
    svg("hero-mobile", W, H, u, "".join(body), f"{NAME}, AI and software engineer in Doha, Qatar. {PITCH}")


# --------------------------------------------------------------------------- numbers
def stats_items(s):
    return [(fmt(s["all_time"]), "contributions", f"since {date(s['joined'], '%b %Y')}"),
            (fmt(s["last_year"]), "contributions", "in the last 12 months"),
            (str(s["owned"]), "repositories", f"{s['public']} public, the rest private")]


def stats_alt(s):
    return (f"On GitHub: {fmt(s['all_time'])} contributions since {date(s['joined'], '%B %Y')}, {fmt(s['last_year'])} in the last "
            f"12 months, {s['owned']} repositories of my own, {s['public']} of them public.")


def stats(s):
    stamp = f"UPDATED DAILY  ·  {date(s['updated']).upper()}"
    u, W, H = "stats", 880, 176
    x, y, w, h = 8, 6, 864, 164
    body = [card(x, y, w, h), label(32, 40, "ON GITHUB  ·  PRIVATE WORK INCLUDED"), label(848, 40, stamp, 10.5, "end", MUTED)]
    for i, (big, l1, l2) in enumerate(stats_items(s)):
        cx = 32 + i * 276
        if i:
            body.append(f'<rect x="{cx - 20}" y="62" width="1" height="90" fill="{EDGE}"/>')
        body += [text(cx - 2, 104, big, 46, BLUE, family=SERIF, italic=True, ls=-1),
                 text(cx, 130, l1, 14.5, TEXT, weight=600), text(cx, 149, l2, 14, MUTED)]
    svg("stats", W, H, u, "".join(body), stats_alt(s))

    u, W, H = "stats-m", 440, 296
    x, y, w, h = 6, 6, 428, 284
    body = [card(x, y, w, h), label(24, 40, "ON GITHUB"), label(416, 40, date(s["updated"]).upper(), 10.5, "end", MUTED)]
    for i, (big, l1, l2) in enumerate(stats_items(s)):
        cx, cy = 24 + (i % 2) * 204, 104 + (i // 2) * 116
        body += [text(cx - 2, cy, big, 42, BLUE, family=SERIF, italic=True, ls=-1),
                 text(cx, cy + 26, l1, 14.5, TEXT, weight=600), text(cx, cy + 45, l2, 13.5, MUTED)]
    body.append(f'<rect x="24" y="164" width="392" height="1" fill="{EDGE}"/>')
    svg("stats-mobile", W, H, u, "".join(body), stats_alt(s))


# --------------------------------------------------------------------------- calendar
LEVEL = {"NONE": "empty", "FIRST_QUARTILE": "p25", "SECOND_QUARTILE": "p50", "THIRD_QUARTILE": "p75", "FOURTH_QUARTILE": "solid"}


def cell(u, kind, x, y, size):
    if kind == "empty":
        return f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="2" fill="{EMPTY}"/>'
    return tint(u, kind, x, y, size, size, 2)


def calendar_grid(u, weeks, gx, gy, size, gap, months=True):
    out, seen = [], None
    for wi, week in enumerate(weeks):
        for iso, _, level in week:
            d = dt.date.fromisoformat(iso)
            cx, cy = gx + wi * (size + gap), gy + d.isoweekday() % 7 * (size + gap)
            out.append(cell(u, LEVEL[level], cx, cy, size))
            if months and d.isoweekday() % 7 == 0 and d.day <= 7 and d.month != seen:
                seen = d.month
                out.append(text(cx, gy - 9, d.strftime("%b"), 11, MUTED))
    return out


def legend(u, x, y, size, gap):
    out = [text(x - 8, y + size - 1, "Less", 11, MUTED, anchor="end")]
    for i, kind in enumerate(("empty", "p25", "p50", "p75", "solid")):
        out.append(cell(u, kind, x + i * (size + gap), y, size))
    out.append(text(x + 5 * (size + gap) + 4, y + size - 1, "More", 11, MUTED))
    return out


def calendar(s):
    count, day = s["best_day"]
    side = [(str(s["active_days"]), "active days"), (f"{s['longest_streak']} days", "longest streak"),
            (str(count), f"best day, {date(day, '%-d %b')}")]
    alt = (f"{fmt(s['last_year'])} contributions in the last 12 months: {s['active_days']} active days, "
           f"longest streak {s['longest_streak']} days.")

    u, W, H = "cal", 880, 270
    x, y, w, h = 8, 6, 864, 258
    body = [card(x, y, w, h), label(32, 40, "CONTRIBUTIONS  ·  LAST 12 MONTHS"),
            text(30, 88, fmt(s["last_year"]), 44, BLUE, family=SERIF, italic=True, ls=-1),
            text(34 + len(fmt(s["last_year"])) * 22 + 12, 86, "contributions in the last year", 14.5, TEXT)]
    for i, (big, small) in enumerate(side):
        sx = 848 - (2 - i) * 132
        body += [text(sx, 72, big, 21, BLUE, family=SERIF, italic=True, anchor="end"),
                 text(sx, 91, small, 12.5, MUTED, anchor="end")]
    body += calendar_grid(u, s["weeks"], 70, 132, 11, 3)
    body += [text(60, 132 + 1 * 14 + 9.5, "Mon", 10.5, MUTED, anchor="end"),
             text(60, 132 + 3 * 14 + 9.5, "Wed", 10.5, MUTED, anchor="end"),
             text(60, 132 + 5 * 14 + 9.5, "Fri", 10.5, MUTED, anchor="end")]
    body += legend(u, 848 - 5 * 14 - 30, 240, 11, 3)
    svg("calendar", W, H, u, "".join(body), alt)

    u, W, H = "cal-m", 440, 316
    x, y, w, h = 6, 6, 428, 304
    body = [card(x, y, w, h), label(24, 40, "CONTRIBUTIONS"),
            text(22, 86, fmt(s["last_year"]), 40, BLUE, family=SERIF, italic=True, ls=-1),
            text(24, 108, "in the last 12 months  ·  last 26 weeks shown", 13.5, MUTED)]
    body += calendar_grid(u, s["weeks"][-26:], 26, 140, 12, 3)
    for i, (big, small) in enumerate(side):
        sx = 24 + i * 136
        body += [text(sx, 274, big, 19, BLUE, family=SERIF, italic=True), text(sx, 292, small, 12, MUTED)]
    svg("calendar-mobile", W, H, u, "".join(body), alt)


# --------------------------------------------------------------------------- links
LINKS = [
    ("site", "WEBSITE", "aamir.qzz.io", ["Most of my work is in private repos,", "so projects and case studies live here."], SITE),
    ("linkedin", "LINKEDIN", "Aamir Abdul Kader", ["Experience and work history"], LINKEDIN),
    ("email", "EMAIL", EMAIL, ["Replies within 24 hours"], f"mailto:{EMAIL}"),
]


def links():
    for key, lab, value, note, _ in LINKS:
        u = f"link-{key}"
        x, y, w, h = 8, 4, 864, 60
        body = [card(x, y, w, h), tint(u, "p50", x + 22, y + 21, 18, 18, 3),
                label(x + 54, y + 36, lab, 11),
                text(x + 170, y + 38, value, 23, BLUE, family=SERIF, italic=True)]
        ny = y + (27 if len(note) == 2 else 36)
        body += [text(x + w - 24, ny + j * 18, line, 13.5, MUTED, anchor="end") for j, line in enumerate(note)]
        svg(u, 880, 68, u, "".join(body), f"{lab.title()}: {value}")

        u = f"link-{key}-m"
        x, y, w, h = 6, 3, 428, 66
        body = [card(x, y, w, h), label(x + 20, y + 26, lab, 10.5),
                text(x + 19, y + 52, value, 19 if len(value) < 22 else 16.5, BLUE, family=SERIF, italic=True)]
        svg(f"link-{key}-mobile", 440, 72, u, "".join(body), f"{lab.title()}: {value}")


# --------------------------------------------------------------------------- README
def version(name):
    """A short fingerprint of an image's content, so a changed image gets a new URL and skips stale caches."""
    return hashlib.sha1((OUT / f"{name}.svg").read_bytes()).hexdigest()[:10]


def picture(name, alt, href=None):
    tag = (f'<picture><source media="(max-width: 700px)" srcset="profile/{name}-mobile.svg?v={version(name + "-mobile")}">'
           f'<img src="profile/{name}.svg?v={version(name)}" width="100%" alt="{html.escape(alt)}"></picture>')
    return f'<a href="{href}">{tag}</a>' if href else tag


def readme(s):
    lines = [
        "<!-- The images in profile/ and this file are regenerated daily by .github/workflows/update-profile.yml. -->",
        "",
        picture("hero", f"{NAME}, AI and software engineer in Doha, Qatar. {PITCH}", SITE),
        "",
        picture("stats", stats_alt(s)),
        "",
        picture("calendar", f"{fmt(s['last_year'])} contributions in the last 12 months"),
        "",
        "<p>" + "<br>".join(picture(f"link-{key}", f"{lab.title()}: {value}", href) for key, lab, value, _, href in LINKS) + "</p>",
        "",
    ]
    (ROOT / "README.md").write_text("\n".join(lines))


def main():
    if "--cached" in sys.argv:
        s = json.loads(CACHE.read_text())
    else:
        token = os.environ.get("GH_TOKEN")
        if not token:
            if os.environ.get("CI"):
                # no PROFILE_STATS_TOKEN secret yet: keep the committed images and skip without failing the run
                print("::warning::PROFILE_STATS_TOKEN is not set, so the profile stats were not refreshed.")
                return
            sys.exit("Set GH_TOKEN to a token that can read your repositories, e.g. GH_TOKEN=$(gh auth token).")
        s = fetch(token)
        if not os.environ.get("CI"):
            CACHE.parent.mkdir(exist_ok=True)
            CACHE.write_text(json.dumps(s))
    OUT.mkdir(exist_ok=True)
    hero(s), stats(s), calendar(s), links(), readme(s)
    print(f"Rendered profile: {fmt(s['last_year'])} contributions in the last year, {s['owned']} repositories.")


if __name__ == "__main__":
    main()
