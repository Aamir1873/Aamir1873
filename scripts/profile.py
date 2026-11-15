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


# --------------------------------------------------------------------------- magnolia and flag (lo-fi dither)
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


def _tepal_outline(length=44, width=31, k=32):
    """Outline of one magnolia tepal pointing up (-y) from its base: narrow base, broad rounded tip."""
    left, right = [], []
    for i in range(k + 1):
        t = i / k
        half = width / 2 * (math.sin(math.pi * min(1, t * .95 + .05)) ** .6) * (.55 + .45 * t)
        left.append((-half, -t * length))
        right.append((half, -t * length))
    tip = [(width / 2 * .5 * math.cos(a) * .9, -length - 4 * math.sin(a)) for a in [math.pi * j / 8 for j in range(1, 8)]]
    return right + tip + left[::-1]


TEPAL = _tepal_outline()


def _tepal_tone(x, y):
    if not _inside_poly(TEPAL, x, y):
        return None
    if _near([TEPAL + TEPAL[:1]], x, y, 1.6):
        return 1                                           # solid rim
    t = min(1, -y / 44)
    return .82 * (1 - t) ** 1.1 + .07                      # deep blush at the base, paler toward the tips


def _bud_tone(x, y):
    if ((x / 7) ** 2 + ((y + 12) / 14) ** 2) > 1:
        return None
    return 1 if ((x / 7) ** 2 + ((y + 12) / 14) ** 2) > .62 else .5 - .3 * (-y / 26)


def _leaf_tone(x, y, length=40, width=20):
    if not 0 <= x <= length:
        return None
    half = width / 2 * math.sin(math.pi * x / length) ** .7
    if abs(y) > half:
        return None
    return 1 if abs(y) <= 1.2 or abs(y) >= half - 1.6 else .34 + .2 * (1 - x / length)


def _pistil_tone(x, y):
    if not (-20 <= y <= 0 and abs(x) <= 5 * (1 + y / 24)):
        return None
    return .9


def magnolia(u, bx, by, scale, cell=2.4, branch_from=(120, 96)):
    """One magnolia: a branch with two leaves and a side bud, and a bloom that opens slowly from a closed bud,
    then sways a little. (bx, by) is the base of the bloom; the branch runs down to the right from it."""
    paper = f'fill="{PAPER}"'
    ink = f'fill="{BLUE}"'
    ex, ey = branch_from
    branch = [[_bez((ex, ey), (ex * .66, ey * .9), (ex * .3, ey * .55), (0, 6), k / 40) for k in range(41)]]
    twig = [[_bez(branch[0][18], (branch[0][18][0] - 8, branch[0][18][1] - 14), (branch[0][18][0] - 10, branch[0][18][1] - 26),
                  (branch[0][18][0] - 14, branch[0][18][1] - 36), k / 20) for k in range(21)]]
    wood = _dots(lambda x, y: 1 if _near(branch, x, y, 3.2) else (1 if _near(twig, x, y, 2) else None),
                 -6, ex + 4, -6 - abs(twig[0][-1][1]), ey + 6, cell)
    leaf_px = _dots(_leaf_tone, 0, 42, -12, 12, cell)
    (l1x, l1y), (l2x, l2y) = branch[0][30], branch[0][12]
    leaves = (f'<g transform="translate({n(l1x)} {n(l1y)}) rotate(68)"><path d="{leaf_px}" {ink}/></g>'
              f'<g transform="translate({n(l2x)} {n(l2y)}) rotate(160)"><path d="{leaf_px}" {ink}/></g>')
    tx, ty = twig[0][-1]
    side_bud = f'<g transform="translate({n(tx)} {n(ty)}) rotate(-18) scale(.8)"><path d="{_dots(_bud_tone, -8, 8, -28, 2, cell)}" {ink}/></g>'

    tepal_px = _dots(_tepal_tone, -17, 17, -50, 2, cell)
    tepal_shape = "M" + "L".join(f"{n(x)} {n(y)}" for x, y in TEPAL) + "Z"

    def tepal(final, size, start, dur):
        closed = final * .1
        return (f'<g transform="rotate({n(closed)})"><animateTransform attributeName="transform" type="rotate" from="{n(closed)}" '
                f'to="{n(final)}" begin="{start}s" dur="{dur}s" fill="freeze" calcMode="spline" keyTimes="0;1" keySplines="{SLOW}"/>'
                f'<g transform="scale({size})"><path d="{tepal_shape}" {paper}/><path d="{tepal_px}" {ink}/></g></g>')

    back = "".join(tepal(a, .98, 1.2 + i * .25, 6.5) for i, a in enumerate((-24, 24, 0)))
    pistil = f'<path d="{_dots(_pistil_tone, -6, 6, -22, 1, cell)}" {ink}/>'
    front = "".join(tepal(a, .9, 1.0 + i * .2, 6.8) for i, a in enumerate((-44, 44, -14, 14)))
    calyx = f'<path d="{_dots(lambda x, y: 1 if (x / 7) ** 2 + ((y - 2) / 4) ** 2 <= 1 else None, -8, 8, -3, 7, cell)}" {ink}/>'
    sway = (f'<animateTransform attributeName="transform" type="rotate" values="0 0 0;1.6 0 0;-1.2 0 0;0 0 0" begin="8s" dur="10s" '
            f'repeatCount="indefinite" calcMode="spline" keyTimes="0;.4;.75;1" keySplines="{EASE};{EASE};{EASE}"/>')
    bloom = f'<g>{sway}{back}{pistil}{front}{calyx}</g>'
    return (f'<g transform="translate({bx} {by}) scale({scale})"><path d="{wood}" {ink}/>{leaves}{side_bud}{bloom}</g>')


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
    u, W, H = "hero", 880, 250
    x, y, w, h = 8, 6, 864, 236
    body = [card(x, y, w, h),
            magnolia(u, 744, 128, 1.15, branch_from=(112, 98)),
            qatar_flag(796, 20, 62),
            label(40, 56, ROLE),
            text(36, 132, NAME, 62, BLUE, family=SERIF, italic=True, ls=-1),
            text(40, 172, PITCH, 17),
            text(40, 208, NOW, 14, MUTED)]
    svg("hero", W, H, u, "".join(body), f"{NAME}, AI and software engineer in Doha, Qatar. {PITCH}")

    u, W, H = "hero-m", 440, 312
    x, y, w, h = 6, 6, 428, 300
    body = [card(x, y, w, h),
            magnolia(u, 360, 126, .68, cell=2.6, branch_from=(108, 100)),
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
