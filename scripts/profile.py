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


# --------------------------------------------------------------------------- butterfly (a lo-fi dithered monarch)
EASE = ".42 0 .58 1"

# Right-hand wings, body on x = 0. Outlines are a start point plus cubic segments.
FORE = ((3, -4), [((30, -40), (62, -64), (92, -66)), ((100, -66), (103, -58), (100, -50)),
                  ((94, -32), (88, -14), (80, 2)), ((60, 6), (30, 6), (4, 2))])
HIND = ((4, 4), [((30, 2), (62, 6), (78, 16)), ((90, 26), (86, 48), (72, 62)),
                 ((58, 76), (30, 76), (16, 62)), ((8, 50), (4, 30), (4, 8))])
FORE_VEINS = ["M6 -5C24 -18 40 -26 56 -31L51 -18C36 -14 20 -8 6 -1", "M8 -8C30 -30 52 -48 74 -60",
              "M56 -31C66 -40 76 -52 86 -64", "M56 -31C70 -40 84 -50 97 -60", "M56 -31C72 -36 88 -42 101 -48",
              "M54 -25C70 -28 84 -30 97 -34", "M51 -18C66 -18 80 -18 92 -20", "M44 -15C60 -12 74 -8 86 -6",
              "M32 -11C50 -6 66 -2 82 1", "M20 -6C36 -2 52 2 66 4"]
HIND_VEINS = ["M6 6C20 8 34 12 44 17C46 23 46 29 44 34C30 26 16 18 7 11", "M44 17C58 16 70 16 80 18",
              "M45 22C60 24 74 28 87 33", "M45 28C60 34 74 42 85 48", "M44 34C56 44 66 52 74 62",
              "M40 32C46 46 54 60 58 72", "M32 28C34 44 38 58 40 74", "M22 22C22 38 24 52 26 68", "M10 14C10 30 12 44 17 60"]
APEX = "M58 -70L106 -70L106 -34C94 -37 80 -44 64 -54Z"
APEX_SPOTS = [(84, -50, 2.8), (91, -45, 2.3), (77, -55, 2.2), (93, -53, 1.9), (70, -59, 1.6), (86, -40, 1.6)]


def _bez(p0, p1, p2, p3, t):
    mt = 1 - t
    return (mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0],
            mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1])


def _sample(shape, first=0, last=None, k=28):
    (x0, y0), segs = shape
    starts = [(x0, y0)] + [s[2] for s in segs[:-1]]
    pts = []
    for i in range(first, len(segs) if last is None else last):
        p1, p2, p3 = segs[i]
        pts += [_bez(starts[i], p1, p2, p3, j / k) for j in range(k + 1)]
    return pts


def _lines(d):
    """Polylines from an absolute M/L/C/Z path."""
    toks = re.findall(r"[MLCZ]|-?\d*\.?\d+", d)
    out, i, cur = [], 0, None
    while i < len(toks):
        t = toks[i]
        if t == "M":
            cur = (float(toks[i + 1]), float(toks[i + 2])); out.append([cur]); i += 3
        elif t == "L":
            cur = (float(toks[i + 1]), float(toks[i + 2])); out[-1].append(cur); i += 3
        elif t == "C":
            p1, p2, p3 = [(float(toks[i + j]), float(toks[i + j + 1])) for j in (1, 3, 5)]
            out[-1] += [_bez(cur, p1, p2, p3, s / 12) for s in range(1, 13)]
            cur = p3; i += 7
        else:
            out[-1].append(out[-1][0]); i += 1
    return out


def _inside(poly, x, y):
    hit, j = False, len(poly) - 1
    for i in range(len(poly)):
        (xi, yi), (xj, yj) = poly[i], poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


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


def _edge_spots(shape, spans, centre, rows=((3.6, 6.2), (7.2, 8.4))):
    """Points for the monarch's two rows of white spots, just inside a wing's outer edge."""
    (x0, y0), segs = shape
    starts = [(x0, y0)] + [s[2] for s in segs[:-1]]
    pts = []
    for i, (t0, t1) in spans:
        p0, (p1, p2, p3) = starts[i], segs[i]
        for k in range(161):
            t = t0 + (t1 - t0) * k / 160
            (px, py), (qx, qy) = _bez(p0, p1, p2, p3, t), _bez(p0, p1, p2, p3, min(1, t + .002))
            dx, dy = qx - px, qy - py
            ln = (dx * dx + dy * dy) ** .5 or 1
            nx, ny = -dy / ln, dx / ln
            if (centre[0] - px) * nx + (centre[1] - py) * ny < 0:
                nx, ny = -nx, -ny
            pts.append((px, py, nx, ny))
    out = []
    for r, (inset, gap) in enumerate(rows):
        run, last = (gap / 2 if r else 0), None
        for px, py, nx, ny in pts:
            if last:
                run += ((px - last[0]) ** 2 + (py - last[1]) ** 2) ** .5
            last = (px, py)
            if run >= gap:
                run = 0
                out.append((px + nx * inset, py + ny * inset, 2.2 if r == 0 else 1.9))
    return out


WING = {
    "fore": dict(poly=_sample(FORE), outer=[_sample(FORE, 0, 3)], inner=[_sample(FORE, 3, 4)],
                 veins=[ln for d in FORE_VEINS for ln in _lines(d)], apex=_lines(APEX)[0],
                 spots=_edge_spots(FORE, [(0, (.84, 1)), (1, (0, 1)), (2, (0, .94))], (56, -26)) + APEX_SPOTS),
    "hind": dict(poly=_sample(HIND), outer=[_sample(HIND, 1, 3)], inner=[_sample(HIND, 3, 4), _sample(HIND, 0, 1)],
                 veins=[ln for d in HIND_VEINS for ln in _lines(d)], apex=None,
                 spots=_edge_spots(HIND, [(0, (.62, 1)), (1, (0, 1)), (2, (0, .86))], (44, 36))),
}


def _wing_tone(x, y):
    """Ink density at a point of the right-hand wings: 1 = solid, 0 = paper, None = outside."""
    for key in ("fore", "hind"):                      # forewing sits on top
        w = WING[key]
        if not _inside(w["poly"], x, y):
            continue
        if any((x - sx) ** 2 + (y - sy) ** 2 <= (r + .3) ** 2 for sx, sy, r in w["spots"]):
            return 0
        if w["apex"] and _inside(w["apex"], x, y):
            return 1
        if _near(w["outer"], x, y, 9) or _near(w["inner"], x, y, 2.2) or _near(w["veins"], x, y, 1.6):
            return 1
        return .2 + .24 * max(0, 1 - (x * x + y * y) ** .5 / 105)    # lighter cells so veins and borders read; darker toward the body
    return None


BODY = [(0, 17, 3.8, 19), (0, -6, 5.6, 10.5), (0, -19.5, 5.2, 5.2)]
BODY_SPOTS = [(-2.2, -21), (2.2, -21), (-2.6, -10), (2.6, -10), (-2.8, -3), (2.8, -3)]
ANTENNAE = [[(1.5, -22), (8, -36), (17, -50)], [(-1.5, -22), (-8, -36), (-17, -50)]]


def _body_tone(x, y):
    if any((x - sx) ** 2 + (y - sy) ** 2 <= 1.6 ** 2 for sx, sy in BODY_SPOTS):
        return 0
    if any(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1 for cx, cy, rx, ry in BODY):
        return 1
    if _near(ANTENNAE, x, y, 1.7) or any((x - ex) ** 2 + (y + 50.6) ** 2 <= 3.2 ** 2 for ex in (17.6, -17.6)):
        return 1
    return None


def _dots(tone, xs, ys, cell, groups, seed):
    """Ordered (4x4 Bayer) dither of a tone field into square pixels, split into shimmer groups."""
    rnd = __import__("random").Random(seed)
    paths = [[] for _ in range(groups)]
    size = cell * .78
    for gy in ys:
        for gx in xs:
            t = tone(gx * cell + cell / 2, gy * cell + cell / 2)
            if t is None or t <= (B4[gy % 4][gx % 4] + .5) / 16:
                continue
            x, y = gx * cell + (cell - size) / 2, gy * cell + (cell - size) / 2
            paths[rnd.randrange(groups)].append(f"M{n(x)} {n(y)}h{n(size)}v{n(size)}h{n(-size)}z")
    return ["".join(p) for p in paths]


def smooth_loop(pts):
    """A closed Catmull-Rom curve through the waypoints, as cubic Bezier path data."""
    d, m = f"M{pts[0][0]} {pts[0][1]}", len(pts)
    for i in range(m):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % m], pts[(i + 2) % m]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f"C{n(c1[0])} {n(c1[1])} {n(c2[0])} {n(c2[1])} {p2[0]} {p2[1]}"
    return d


def butterfly(u, waypoints, scale, dur, box, cell=3):
    """A lo-fi dithered monarch: square ink pixels that shimmer and stray specks drifting off the wings.
    It beats three times and glides, and wanders the whole card facing where it flies, hovering now and then."""
    rows = range(int(-72 // cell) - 1, int(78 // cell) + 1)
    wing = _dots(_wing_tone, range(0, int(106 // cell) + 1), rows, cell, 3, 7)
    body = _dots(_body_tone, range(int(-20 // cell) - 1, int(20 // cell) + 1), range(int(-56 // cell) - 1, int(38 // cell) + 1), cell, 1, 3)
    shimmer = [("0 0;.5 -.4;-.3 .4;0 0", 7.0), ("0 0;-.4 .3;.4 -.4;0 0", 8.5), ("0 0;.3 .5;-.5 -.2;0 0", 10.0)]
    pixels = "".join(f'<path d="{d}" fill="{BLUE}"><animateTransform attributeName="transform" type="translate" '
                     f'values="{v}" dur="{t}s" repeatCount="indefinite" calcMode="spline" keyTimes="0;.33;.66;1" '
                     f'keySplines="{EASE};{EASE};{EASE}"/></path>'
                     for d, (v, t) in zip(wing, shimmer))
    defs = f'<g id="{u}-wing">{pixels}</g>'
    beats, times = "1 1;.24 1;1 1;.24 1;1 1;.82 1;1 1", "0;.1;.2;.3;.4;.7;1"
    flap = (f'<animateTransform attributeName="transform" type="scale" dur="6s" repeatCount="indefinite" values="{beats}" '
            f'keyTimes="{times}" calcMode="spline" keySplines="{";".join([EASE] * 6)}"/>')
    use = f'<use href="#{u}-wing" xlink:href="#{u}-wing"/>'
    wings = f'<g transform="scale(-1 1)"><g>{flap}{use}</g></g><g>{flap}{use}</g>'

    # stray specks peeling off the outer edges, like a loose swarm
    rnd = __import__("random").Random(11)
    edge = WING["fore"]["outer"][0] + WING["hind"]["outer"][0]
    specks = []
    for k in range(26):
        px, py = edge[rnd.randrange(len(edge))]
        side = -1 if k % 2 else 1
        dx, dy = px - 40, py - 4
        ln = (dx * dx + dy * dy) ** .5 or 1
        dist = rnd.uniform(10, 24)
        tx, ty = side * (dx / ln * dist + rnd.uniform(-5, 5)), dy / ln * dist + rnd.uniform(-5, 5)
        dur, s = rnd.uniform(4.5, 7.5), cell * .8
        specks.append(f'<rect x="{n(side * px - s / 2)}" y="{n(py - s / 2)}" width="{n(s)}" height="{n(s)}" fill="{BLUE}" opacity="0">'
                      f'<animate attributeName="opacity" values="0;.85;0" dur="{dur:.1f}s" begin="-{rnd.uniform(0, 4):.1f}s" repeatCount="indefinite"/>'
                      f'<animateTransform attributeName="transform" type="translate" values="0 0;{n(tx)} {n(ty)}" dur="{dur:.1f}s" '
                      f'begin="-{rnd.uniform(0, 4):.1f}s" repeatCount="indefinite"/></rect>')
    insect = f'<g transform="scale({scale})">{"".join(specks)}{wings}<path d="{body[0]}" fill="{BLUE}"/></g>'
    wobble = (f'<g>{insect}<animateTransform attributeName="transform" type="rotate" values="-5;4;-3;-5" dur="8s" '
              f'repeatCount="indefinite" calcMode="spline" keyTimes="0;.4;.75;1" keySplines="{EASE};{EASE};{EASE}"/></g>')
    bx, by, bw, bh = box
    clip = f'<clipPath id="{u}-fly"><rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="8"/></clipPath>'
    # keyPoints slow it to a hover twice per lap; rotate="auto" turns it along the path (its head points up, hence +90)
    motion = (f'<animateMotion path="{smooth_loop(waypoints)}" dur="{dur}s" repeatCount="indefinite" rotate="auto" '
              f'keyPoints="0;.34;.7;1" keyTimes="0;.33;.68;1" calcMode="spline" keySplines="{EASE};{EASE};{EASE}"/>')
    flight = f'<g clip-path="url(#{u}-fly)"><g>{motion}<g transform="rotate(90)">{wobble}</g></g></g>'
    return f'<defs>{defs}{clip}</defs>' + flight


# --------------------------------------------------------------------------- hero
def hero(s):
    u, W, H = "hero", 880, 250
    x, y, w, h = 8, 6, 864, 236
    body = [card(x, y, w, h),
            butterfly(u, [(760, 120), (650, 70), (440, 84), (230, 72), (118, 140), (290, 196), (540, 184), (790, 172)], .56, 96, (x, y, w, h)),
            label(40, 56, ROLE),
            text(36, 132, NAME, 62, BLUE, family=SERIF, italic=True, ls=-1),
            text(40, 172, PITCH, 17),
            text(40, 208, NOW, 14, MUTED)]
    svg("hero", W, H, u, "".join(body), f"{NAME}, AI and software engineer in Doha, Qatar. {PITCH}")

    u, W, H = "hero-m", 440, 312
    x, y, w, h = 6, 6, 428, 300
    body = [card(x, y, w, h),
            butterfly(u, [(354, 84), (240, 112), (110, 72), (76, 190), (240, 240), (392, 214)], .38, 72, (x, y, w, h), cell=5),
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
