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

import concurrent.futures as cf
import datetime as dt
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

    def commits(full):
        status, headers, body = call(f"{API}/repos/{full}/commits?author={login}&per_page=1", token)
        if status != 200:
            return 0
        m = re.search(r'[?&]page=(\d+)>; rel="last"', headers.get("Link", ""))
        return int(m.group(1)) if m else len(json.loads(body or b"[]"))

    names = [r["full_name"] for r in repos if not r.get("fork")]
    with cf.ThreadPoolExecutor(8) as ex:
        counts = dict(zip(names, ex.map(commits, names)))

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
        "commits": sum(counts.values()), "repos_committed": sum(1 for v in counts.values() if v),
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


# --------------------------------------------------------------------------- flower (a lo-fi dithered plant that grows and blooms)
EASE = ".42 0 .58 1"
EASE_OUT = ".2 .7 .3 1"
B4_SEED = 7


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
    """Ordered (4x4 Bayer) dither of a tone field into square ink pixels, as one path."""
    out, size = [], cell * .8
    for gy in range(int(y0 // cell) - 1, int(y1 // cell) + 1):
        for gx in range(int(x0 // cell) - 1, int(x1 // cell) + 1):
            t = tone(gx * cell + cell / 2, gy * cell + cell / 2)
            if t is None or t <= (B4[gy % 4][gx % 4] + .5) / 16:
                continue
            x, y = gx * cell + (cell - size) / 2, gy * cell + (cell - size) / 2
            out.append(f"M{n(x)} {n(y)}h{n(size)}v{n(size)}h{n(-size)}z")
    return "".join(out)


STEM = ((0, 0), (-7, -52), (11, -100), (4, -150))      # base to flower head, local units (up is -y)
STEM_LINE = [[_bez(*STEM, k / 60) for k in range(61)]]
TOP = STEM[3]
LEAVES = [(.34, -152, 1.8), (.6, -28, 2.6)]              # (position along stem, angle, start time)


def _stem_tone(x, y):
    return 1 if _near(STEM_LINE, x, y, 2.6) else None


def _leaf_tone(x, y, length=46, width=17):
    """An almond leaf along +x from its base: dithered blade, solid midrib and rim."""
    if not 0 <= x <= length:
        return None
    half = width / 2 * math.sin(math.pi * x / length) ** .8
    if abs(y) > half:
        return None
    if abs(y) <= 1.3 or abs(y) >= half - 1.7:
        return 1
    return .38 + .24 * (1 - x / length)


def _petal_tone(x, y, inner=8, outer=42, width=14):
    """A petal pointing up (-y) from the flower centre: dithered, darker at the base, with a solid rim."""
    r = -y
    if not inner <= r <= outer:
        return None
    t = (r - inner) / (outer - inner)
    half = width / 2 * math.sin(math.pi * min(1, t * 1.08)) ** .55
    if abs(x) > half:
        return None
    if abs(x) >= half - 1.6 or t > .95:
        return 1
    return .34 + .3 * (1 - t)


def _disc_tone(x, y, r=12):
    d = (x * x + y * y) ** .5
    if d > r:
        return None
    seeds = [(3.4 * math.cos(a), 3.4 * math.sin(a)) for a in (0, 2.1, 4.2)] + [(0, 0)]
    if d < r - 2 and any((x - sx) ** 2 + (y - sy) ** 2 < 1.6 for sx, sy in seeds):
        return 0
    return 1


def _bud_tone(x, y):
    if ((x / 8) ** 2 + ((y + 11) / 13) ** 2) > 1:
        return None
    return 1 if ((x / 8) ** 2 + ((y + 11) / 13) ** 2) > .62 or abs(x) < 1.2 else .55


def _soil_tone(x, y):
    if ((x / 40) ** 2 + (y / 9) ** 2) > 1 or y < -9:
        return None
    return .5 + .3 * (y + 9) / 9


def _grow(begin, dur, frm="0 0", to="1 1", spline=EASE_OUT):
    return (f'<animateTransform attributeName="transform" type="scale" from="{frm}" to="{to}" begin="{begin}s" dur="{dur}s" '
            f'fill="freeze" calcMode="spline" keyTimes="0;1" keySplines="{spline}"/>')


def flower(u, bx, by, scale, cell=3):
    """A plant that grows from a sprout to a bloom once, then sways in place and gives off a little pollen."""
    stem_h = -TOP[1] + 2
    clip = (f'<clipPath id="{u}-stem"><rect x="-30" y="2" width="60" height="0">'
            f'<animate attributeName="y" from="2" to="{-stem_h}" begin=".5s" dur="3.6s" fill="freeze" calcMode="spline" keyTimes="0;1" keySplines="{EASE_OUT}"/>'
            f'<animate attributeName="height" from="0" to="{stem_h + 2}" begin=".5s" dur="3.6s" fill="freeze" calcMode="spline" keyTimes="0;1" keySplines="{EASE_OUT}"/>'
            f'</rect></clipPath>')
    ink = f'fill="{BLUE}"'
    soil = f'<path d="{_dots(_soil_tone, -42, 42, -10, 2, cell)}" {ink}/>'
    stem = f'<g clip-path="url(#{u}-stem)"><path d="{_dots(_stem_tone, -12, 16, -152, 2, cell)}" {ink}/></g>'
    leaf_px = _dots(_leaf_tone, 0, 48, -10, 10, cell)
    leaves = ""
    for pos, angle, start in LEAVES:
        ax, ay = _bez(*STEM, pos)
        leaves += (f'<g transform="translate({n(ax)} {n(ay)}) rotate({angle})"><g transform="scale(0)">{_grow(start, 1.6)}'
                   f'<path d="{leaf_px}" {ink}/></g></g>')
    bud = (f'<g transform="translate({TOP[0]} {TOP[1]})"><g transform="scale(0)">{_grow(3.7, 1.1)}'
           f'<g><animate attributeName="opacity" from="1" to="0" begin="5.3s" dur=".9s" fill="freeze"/>'
           f'<path d="{_dots(_bud_tone, -9, 9, -25, 2, cell)}" {ink}/></g></g></g>')
    petal_px = _dots(_petal_tone, -11, 11, -41, -6, cell)
    petals = ""
    for i in range(8):
        target, start = i * 45, 4.9 + (i % 4) * .08
        fold = (i * 45 + 180) % 360 - 180        # fold every petal back toward straight up
        petals += (f'<g transform="rotate({fold * .12:.1f})"><animateTransform attributeName="transform" type="rotate" '
                   f'from="{fold * .12:.1f}" to="{target}" begin="{start:.2f}s" dur="2.4s" fill="freeze" calcMode="spline" keyTimes="0;1" '
                   f'keySplines="{EASE_OUT}"/><g transform="scale(0)">{_grow(start, 2.2)}<path d="{petal_px}" {ink}/></g></g>')
    disc = f'<g transform="scale(0)">{_grow(5.4, 1.4)}<path d="{_dots(_disc_tone, -13, 13, -13, 13, cell)}" {ink}/></g>'
    head = f'<g transform="translate({TOP[0]} {TOP[1]})">{petals}{disc}</g>'

    rnd = __import__("random").Random(5)
    pollen = ""
    for k in range(7):
        sx, sy = TOP[0] + rnd.uniform(-10, 10), TOP[1] + rnd.uniform(-8, 4)
        dx, dy, d = rnd.uniform(-22, 22), rnd.uniform(-46, -26), rnd.uniform(5, 8.5)
        begin = 8 + rnd.uniform(0, 6)
        s = cell * .8
        pollen += (f'<rect x="{n(sx)}" y="{n(sy)}" width="{n(s)}" height="{n(s)}" {ink} opacity="0">'
                   f'<animate attributeName="opacity" values="0;.8;0" dur="{d:.1f}s" begin="{begin:.1f}s" repeatCount="indefinite"/>'
                   f'<animateTransform attributeName="transform" type="translate" values="0 0;{n(dx)} {n(dy)}" dur="{d:.1f}s" '
                   f'begin="{begin:.1f}s" repeatCount="indefinite"/></rect>')
    sway = (f'<animateTransform attributeName="transform" type="rotate" values="0 0 0;1.8 0 0;-1.4 0 0;0 0 0" begin="7.5s" dur="11s" '
            f'repeatCount="indefinite" calcMode="spline" keyTimes="0;.35;.7;1" keySplines="{EASE};{EASE};{EASE}"/>')
    plant = f'<g>{sway}{stem}{leaves}{bud}{head}{pollen}</g>'
    return f'<defs>{clip}</defs><g transform="translate({bx} {by}) scale({scale})">{plant}{soil}</g>'


# --------------------------------------------------------------------------- hero
def hero(s):
    u, W, H = "hero", 880, 250
    x, y, w, h = 8, 6, 864, 236
    body = [card(x, y, w, h),
            flower(u, 770, 238, 1, cell=3),
            label(40, 56, ROLE),
            text(36, 132, NAME, 62, BLUE, family=SERIF, italic=True, ls=-1),
            text(40, 172, PITCH, 17),
            text(40, 208, NOW, 14, MUTED)]
    svg("hero", W, H, u, "".join(body), f"{NAME}, AI and software engineer in Doha, Qatar. {PITCH}")

    u, W, H = "hero-m", 440, 312
    x, y, w, h = 6, 6, 428, 300
    body = [card(x, y, w, h),
            flower(u, 394, 302, .62, cell=4),
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
            (fmt(s["commits"]), "commits", f"across {s['repos_committed']} repositories"),
            (str(s["owned"]), "repositories", f"{s['public']} public, the rest private")]


def stats_alt(s):
    return (f"On GitHub: {fmt(s['all_time'])} contributions since {date(s['joined'], '%B %Y')}, {fmt(s['last_year'])} in the last "
            f"12 months, {fmt(s['commits'])} commits across {s['repos_committed']} repositories, {s['owned']} repositories of my own.")


def stats(s):
    stamp = f"UPDATED DAILY  ·  {date(s['updated']).upper()}"
    u, W, H = "stats", 880, 176
    x, y, w, h = 8, 6, 864, 164
    body = [card(x, y, w, h), label(32, 40, "ON GITHUB  ·  PRIVATE WORK INCLUDED"), label(848, 40, stamp, 10.5, "end", MUTED)]
    for i, (big, l1, l2) in enumerate(stats_items(s)):
        cx = 32 + i * 206
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


def arrow_badge(cx, cy, r, delay):
    """A solid blue disc with a paper arrow that nudges up and to the right every few seconds."""
    nudge = (f'<animateTransform attributeName="transform" type="translate" values="0 0;0 0;2 -2;0 0" keyTimes="0;.7;.85;1" '
             f'dur="4s" begin="{delay}s" repeatCount="indefinite" calcMode="spline" keySplines="{EASE};{EASE};{EASE}"/>')
    a = r * .36
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{BLUE}"/>'
            f'<g>{nudge}<path d="M{n(cx - a)} {n(cy + a)}L{n(cx + a)} {n(cy - a)}M{n(cx - a * .4)} {n(cy - a)}H{n(cx + a)}V{n(cy + a * .4)}" '
            f'fill="none" stroke="{PAPER}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></g>')


def links():
    for i, (key, lab, value, note, _) in enumerate(LINKS):
        u = f"link-{key}"
        x, y, w, h = 8, 4, 864, 60
        body = [card(x, y, w, h), tint(u, "p50", x + 22, y + 21, 18, 18, 3),
                label(x + 54, y + 36, lab, 11),
                text(x + 170, y + 38, value, 23, BLUE, family=SERIF, italic=True)]
        ny = y + (27 if len(note) == 2 else 36)
        body += [text(x + w - 64, ny + j * 18, line, 13.5, MUTED, anchor="end") for j, line in enumerate(note)]
        body.append(arrow_badge(x + w - 32, y + h / 2, 14, i * .6))
        svg(u, 880, 68, u, "".join(body), f"{lab.title()}: {value}")

        u = f"link-{key}-m"
        x, y, w, h = 6, 3, 428, 66
        body = [card(x, y, w, h), label(x + 20, y + 26, lab, 10.5),
                text(x + 19, y + 52, value, 19 if len(value) < 22 else 16.5, BLUE, family=SERIF, italic=True),
                arrow_badge(x + w - 30, y + h / 2, 13, i * .6)]
        svg(f"link-{key}-mobile", 440, 72, u, "".join(body), f"{lab.title()}: {value}")


# --------------------------------------------------------------------------- README
def picture(name, alt, version, href=None):
    tag = (f'<picture><source media="(max-width: 700px)" srcset="profile/{name}-mobile.svg?v={version}">'
           f'<img src="profile/{name}.svg?v={version}" width="100%" alt="{html.escape(alt)}"></picture>')
    return f'<a href="{href}">{tag}</a>' if href else tag


def readme(s):
    v = s["updated"].replace("-", "")
    lines = [
        "<!-- The images in profile/ and this file are regenerated daily by .github/workflows/update-profile.yml. -->",
        "",
        picture("hero", f"{NAME}, AI and software engineer in Doha, Qatar. {PITCH}", v, SITE),
        "",
        picture("stats", stats_alt(s), v),
        "",
        picture("calendar", f"{fmt(s['last_year'])} contributions in the last 12 months", v),
        "",
        "<p>" + "<br>".join(picture(f"link-{key}", f"{lab.title()}: {value}", v, href) for key, lab, value, _, href in LINKS) + "</p>",
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
    print(f"Rendered profile: {fmt(s['last_year'])} contributions in the last year, {fmt(s['commits'])} commits.")


if __name__ == "__main__":
    main()
