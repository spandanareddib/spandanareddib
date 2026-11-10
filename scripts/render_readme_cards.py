#!/usr/bin/env python3
"""
Render the animated SVG cards used by the profile README.

  python scripts/render_readme_cards.py            # real data (needs GITHUB_TOKEN)
  python scripts/render_readme_cards.py --demo     # fake data, no network
  STATIC=1 python scripts/render_readme_cards.py   # no animation (final frame), for screenshots

Everything visual lives in cards/*.svg. Text content lives in data/profile.json.
"""
import argparse, base64, datetime as dt, io, json, math, os, random, sys, textwrap
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "scripts" / "fonts"
CARDS = ROOT / "cards"
DATA = ROOT / "data"
STATIC = os.environ.get("STATIC") == "1"

# ---------------------------------------------------------------- palette
INK = "#1A1626"
MUTED = "#6F6A7D"
PAPER = "#F3F1F7"
RULE = "#D9D5E3"
TEAL = "#0F7F86"
PINK = "#E8456B"
SUN = "#FFC83D"
LEVELS = ["#DDD9E7", "#A9DCDB", "#5CC1C0", "#1E9A9C", "#0A6469"]

FAMILIES = {  # css family -> (font file, font-style)
    "SRSerif": ("serif.woff", "normal"),
    "SRSerifI": ("serif-italic.woff", "italic"),
    "SRMono": ("mono.woff", "normal"),
    "SRSans": ("sans.woff", "normal"),
}
STACK = {
    "SRSerif": "'SRSerif','DM Serif Display',Georgia,serif",
    "SRSerifI": "'SRSerifI','DM Serif Display',Georgia,serif",
    "SRMono": "'SRMono','JetBrains Mono',ui-monospace,Menlo,monospace",
    "SRSans": "'SRSans','DM Sans',system-ui,Arial,sans-serif",
}


# ---------------------------------------------------------------- font embedding
def subset_font(path, chars):
    from fontTools import subset
    opts = subset.Options()
    opts.flavor = "woff"
    opts.layout_features = ["kern", "liga"]
    opts.notdef_outline = True
    font = subset.load_font(str(path), opts)
    s = subset.Subsetter(opts)
    s.populate(text="".join(sorted(set(chars)) or [" "]))
    s.subset(font)
    buf = io.BytesIO()
    subset.save_font(font, buf, opts)
    return base64.b64encode(buf.getvalue()).decode()


class Svg:
    """Tiny SVG builder that remembers which characters each font needs."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.body, self.css, self.defs = [], [], []
        self.chars = {k: set() for k in FAMILIES}

    def add(self, s):
        self.body.append(s)

    def text(self, s, x, y, fam, size, fill, anchor="start", cls="", extra=""):
        self.chars[fam].update(s)
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        c = f' class="{cls}"' if cls else ""
        self.add(
            f'<text x="{x}" y="{y}" font-family="{STACK[fam]}" font-size="{size}" '
            f'fill="{fill}"{a}{c} {extra}>{escape(s)}</text>'
        )

    def mixed(self, parts, x, y, size, extra=""):
        """parts = [(text, family, fill), ...] drawn as one line."""
        spans = []
        for txt, fam, fill in parts:
            self.chars[fam].update(txt)
            spans.append(f'<tspan font-family="{STACK[fam]}" fill="{fill}">{escape(txt)}</tspan>')
        self.add(f'<text xml:space="preserve" x="{x}" y="{y}" font-size="{size}" {extra}>{"".join(spans)}</text>')

    def render(self):
        faces = []
        for fam, used in self.chars.items():
            if not used:
                continue
            file, style = FAMILIES[fam]
            b64 = subset_font(FONTS / file, used)
            faces.append(
                f"@font-face{{font-family:'{fam}';font-style:{style};"
                f"src:url(data:font/woff;base64,{b64}) format('woff')}}"
            )
        css = "".join(faces) + "".join(self.css)
        if not STATIC:
            css += "@media (prefers-reduced-motion:reduce){*{animation:none!important}.frame{display:none}}"
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" role="img">'
            f"<style>{css}</style><defs>{''.join(self.defs)}</defs>{''.join(self.body)}</svg>"
        )


def card_bg(svg, fill=PAPER, rx=18):
    svg.add(f'<rect width="{svg.w}" height="{svg.h}" rx="{rx}" fill="{fill}"/>')


def anim(name, dur, delay, ease="cubic-bezier(.2,.8,.2,1)"):
    if STATIC:
        return ""
    return f"animation:{name} {dur}s {ease} {delay}s both;"


KEYFRAMES = (
    "@keyframes rise{from{opacity:0;transform:translateY(22px)}to{opacity:1;transform:none}}"
    "@keyframes fade{from{opacity:0}to{opacity:1}}"
    "@keyframes pop{from{opacity:0;transform:scale(.2)}to{opacity:1;transform:none}}"
    "@keyframes grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}"
    "@keyframes swing{0%{opacity:0;transform:translateY(40px) rotate(-4deg)}"
    "70%{opacity:1;transform:translateY(-4px) rotate(1deg)}100%{opacity:1;transform:none}}"
    "@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}"
    "@keyframes nudge{0%,100%{transform:translateX(0)}50%{transform:translateX(4px)}}"
)


# ---------------------------------------------------------------- data
GQL = """
query($login:String!,$from:DateTime!,$to:DateTime!){
  user(login:$login){
    contributionsCollection(from:$from,to:$to){
      contributionCalendar{totalContributions weeks{contributionDays{date contributionCount}}}
    }
    repositories(first:30,privacy:PUBLIC,ownerAffiliations:OWNER,isFork:false,
                 orderBy:{field:PUSHED_AT,direction:DESC}){
      nodes{name description stargazerCount primaryLanguage{name color}}
    }
  }
}"""


def gh_graphql(login, token):
    now = dt.datetime.now(dt.timezone.utc)
    body = json.dumps({"query": GQL, "variables": {
        "login": login,
        "from": (now - dt.timedelta(days=364)).strftime("%Y-%m-%dT00:00:00Z"),
        "to": now.strftime("%Y-%m-%dT%H:%M:%SZ")}}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", body, {
        "Authorization": f"bearer {token}", "Content-Type": "application/json",
        "User-Agent": "readme-cards"})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.load(r)
    if "errors" in out:
        raise RuntimeError(out["errors"])
    u = out["data"]["user"]
    cal = u["contributionsCollection"]["contributionCalendar"]
    days = [{"date": d["date"], "count": d["contributionCount"]}
            for w in cal["weeks"] for d in w["contributionDays"]]
    repos = [{"name": n["name"], "description": n["description"] or "",
              "stars": n["stargazerCount"],
              "language": (n["primaryLanguage"] or {}).get("name", ""),
              "color": (n["primaryLanguage"] or {}).get("color") or MUTED}
             for n in u["repositories"]["nodes"]]
    return {"total": cal["totalContributions"], "days": days}, repos


def demo_data():
    rnd = random.Random(7)
    today = dt.date.today()
    start = today - dt.timedelta(days=364)
    days = []
    for i in range(365):
        d = start + dt.timedelta(days=i)
        busy = 1.6 if 120 < i < 200 or i > 300 else 0.8
        c = 0 if rnd.random() < 0.28 else int(rnd.random() ** 2 * 9 * busy)
        days.append({"date": d.isoformat(), "count": c})
    return {"total": sum(d["count"] for d in days), "days": days}, [
        {"name": "your-repo-one", "description": "Pinned repos are picked automatically from your latest public work.",
         "stars": 4, "language": "Python", "color": "#3572A5"},
        {"name": "your-repo-two", "description": "Edit featured_repos in data/profile.json to choose your own.",
         "stars": 2, "language": "TypeScript", "color": "#3178c6"},
        {"name": "your-repo-three", "description": "Language colour and star count come from the GitHub API.",
         "stars": 0, "language": "Jupyter Notebook", "color": "#DA5B0B"}]


def stats(cal):
    days = cal["days"]
    counts = [d["count"] for d in days]
    dates = [dt.date.fromisoformat(d["date"]) for d in days]
    today = dt.date.today()
    # current streak (today may still be empty)
    idx = len(days) - 1
    while idx >= 0 and dates[idx] > today:
        idx -= 1
    if idx >= 0 and counts[idx] == 0:
        idx -= 1
    cur = 0
    while idx >= 0 and counts[idx] > 0:
        cur += 1
        idx -= 1
    longest = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)
    months = {}
    for d, c in zip(dates, counts):
        months[(d.year, d.month)] = months.get((d.year, d.month), 0) + c
    keys = sorted(months)[-12:]
    return {
        "total": cal["total"], "current": cur, "longest": longest,
        "active": sum(1 for c in counts if c > 0), "span": len(days),
        "busiest": max(counts) if counts else 0,
        "months": [(dt.date(y, m, 1).strftime("%b"), months[(y, m)]) for y, m in keys],
    }


# ---------------------------------------------------------------- cards
def hero(p):
    s = Svg(800, 332)
    s.css.append(KEYFRAMES)
    card_bg(s)
    s.add(f'<rect x="40" y="40" width="8" height="8" rx="2" fill="{TEAL}" style="{anim("pulse", 2.4, 1.2, "ease-in-out")}animation-iteration-count:infinite;"/>')
    s.text(p["eyebrow"], 58, 48, "SRMono", 11, MUTED, extra=f'style="{anim("fade", .6, .1)}"')
    first, last = p["name"].split(" ", 1) if " " in p["name"] else (p["name"], "")
    s.text(first, 40, 132, "SRSerif", 80, INK, extra=f'style="{anim("rise", .9, .15)}"')
    s.defs.append(
        f'<linearGradient id="shine" gradientUnits="userSpaceOnUse" x1="40" y1="0" x2="330" y2="0">'
        f'<stop offset="0" stop-color="{INK}"/><stop offset=".42" stop-color="{INK}"/>'
        f'<stop offset=".5" stop-color="{TEAL}"/><stop offset=".58" stop-color="{INK}"/>'
        f'<stop offset="1" stop-color="{INK}"/>'
        + ("" if STATIC else
           '<animateTransform attributeName="gradientTransform" type="translate" '
           'values="-300 0;380 0;380 0" keyTimes="0;.35;1" dur="7s" begin="1.8s" repeatCount="indefinite"/>')
        + "</linearGradient>")
    s.text(last, 40, 206, "SRSerifI", 80, "url(#shine)" if not STATIC else INK,
           extra=f'style="{anim("rise", .9, .35)}"')
    for i, line in enumerate(textwrap.wrap(p["tagline"], 42)[:3]):
        s.text(line, 42, 242 + i * 21, "SRSans", 15, INK, extra=f'style="{anim("fade", .8, .9 + i * .12)}"')
    s.text(p["hero_link"], 42, 312, "SRMono", 11, MUTED, extra=f'style="{anim("fade", .8, 1.3)}"')
    # ascii portrait, printed row by row; font size is fitted to a 290 x 280 box
    rows = (DATA / "portrait.txt").read_text().splitlines()
    ncol = max(len(r) for r in rows)
    fs = min(290 / (ncol * 0.6), 280 / (len(rows) * 1.0))
    lh = fs * 1.0
    x0, y0 = 760 - ncol * fs * 0.6, 34 + (280 - len(rows) * lh) / 2 + lh
    for i, row in enumerate(rows):
        s.chars["SRMono"].update(row)
        s.add(
            f'<text xml:space="preserve" x="{x0:.1f}" y="{y0 + i * lh:.1f}" font-family="{STACK["SRMono"]}" '
            f'font-size="{fs:.2f}" fill="{INK}" fill-opacity=".8" style="{anim("fade", .3, 0.5 + i * .02, "linear")}">{escape(row)}</text>')
    return s.render()


def heatmap(cal):
    s = Svg(800, 226)
    s.css.append(KEYFRAMES)
    card_bg(s)
    s.mixed([("Every day, in ", "SRSerif", INK), ("teal", "SRSerifI", TEAL)], 40, 56, 28)
    s.text("refreshed daily", 760, 50, "SRMono", 10, MUTED, "end")
    days = cal["days"]
    nz = sorted(d["count"] for d in days if d["count"] > 0)
    q = [nz[int(len(nz) * f)] for f in (.25, .5, .75)] if nz else [1, 2, 3]

    def level(c):
        if c == 0: return 0
        return 1 + sum(c > t for t in q)

    first = dt.date.fromisoformat(days[0]["date"])
    lead = (first.weekday() + 1) % 7  # Sunday-first grid, like GitHub
    cell, gap, x0, y0 = 10, 3.2, 40, 80
    seen_month = None
    for i, d in enumerate(days):
        date = dt.date.fromisoformat(d["date"])
        col, row = divmod(i + lead, 7)
        x, y = x0 + col * (cell + gap), y0 + row * (cell + gap)
        delay = 0.9 + col * 0.016
        st = f"transform-box:fill-box;transform-origin:center;{anim('pop', .35, delay)}"
        s.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell}" height="{cell}" rx="2.4" fill="{LEVELS[level(d["count"])]}" style="{st}"/>')
        if date.day <= 7 and row == 0 and seen_month != date.month and col < 51:
            seen_month = date.month
            s.text(date.strftime("%b"), x, 190, "SRMono", 9, MUTED)
    lx = 760 - (5 * 13 + 52)
    s.text("less", lx, 207, "SRMono", 9, MUTED, "end")
    for i, c in enumerate(LEVELS):
        s.add(f'<rect x="{lx + 8 + i * 13}" y="198" width="10" height="10" rx="2.4" fill="{c}"/>')
    s.text("more", lx + 8 + 5 * 13 + 4, 207, "SRMono", 9, MUTED)
    return s.render()


def activity(cal):
    st = stats(cal)
    s = Svg(800, 304)
    s.css.append(KEYFRAMES)
    card_bg(s)
    s.text("the last 12 months on github", 40, 46, "SRMono", 10.5, MUTED)
    total = f"{st['total']:,}"
    s.mixed([(total + " ", "SRSerif", INK), ("contributions", "SRSerifI", INK)], 40, 106, 54,
            extra=f'style="{anim("rise", .8, 1.6)}"')
    months = st["months"]
    mx = max(c for _, c in months) or 1
    base, maxh, bw, step, bx = 262, 118, 31, 43.5, 40
    for i, (name, c) in enumerate(months):
        h = max(4, c / mx * maxh)
        partial = i == len(months) - 1
        color = TEAL if c == mx else ("#C9C5D4" if partial else INK)
        d = 2.1 + i * .06
        s.add(f'<rect x="{bx + i * step:.1f}" y="{base - h:.1f}" width="{bw}" height="{h:.1f}" rx="2" fill="{color}" '
              f'style="transform-box:fill-box;transform-origin:bottom;{anim("grow", .7, d)}"/>')
        s.text(name, bx + i * step + bw / 2, 281, "SRMono", 9.5, MUTED, "middle")
        if c == mx:
            s.text(f"{c:,}", bx + i * step + bw / 2, base - h - 7, "SRMono", 10, TEAL, "middle",
                   extra=f'style="{anim("fade", .5, d + .6)}"')
    rx = 624
    items = [(f"{st['current']} days", f"current streak, longest {st['longest']}"),
             (f"{st['active']} / {st['span']}", "days with a contribution"),
             (f"{st['busiest']}", "on the busiest day")]
    for i, (big, cap) in enumerate(items):
        y = 120 + i * 70
        if i:
            s.add(f'<line x1="{rx}" y1="{y - 42}" x2="760" y2="{y - 42}" stroke="{RULE}"/>')
        s.text(big, rx, y, "SRSerifI", 34, INK, extra=f'style="{anim("rise", .7, 2.3 + i * .15)}"')
        s.text(cap, rx, y + 20, "SRSans", 12, MUTED, extra=f'style="{anim("fade", .7, 2.5 + i * .15)}"')
    return s.render()


def tile(t, color, ink, delay):
    s = Svg(262, 196)
    s.css.append(KEYFRAMES)
    s.css.append(".arr{animation:nudge 2.4s ease-in-out 4s infinite}" if not STATIC else "")
    s.add(f'<g style="transform-box:fill-box;transform-origin:50% 100%;{anim("swing", 1.1, delay)}">')
    s.add(f'<rect width="262" height="196" rx="18" fill="{color}"/>')
    s.text(t["label"], 22, 34, "SRMono", 10.5, ink)
    s.text("→", 240, 35, "SRSans", 14, ink, "end", cls="arr")
    big = t["big"]
    digits = ""
    for ch in big:
        if ch.isdigit(): digits += ch
        else: break
    rest = big[len(digits):]
    if digits and not STATIC:
        n, frames = int(digits), 12
        t0 = delay + 0.5
        s.chars["SRSerifI"].update(rest + "0123456789")
        for i in range(frames):
            v = round(n * i / frames)
            s.add(
                f'<text class="frame" x="22" y="102" font-family="{STACK["SRSerifI"]}" font-size="38" fill="{ink}" '
                f'visibility="hidden">{v}{escape(rest)}<set attributeName="visibility" to="visible" '
                f'begin="{t0 + i * .06:.2f}s" dur=".06s"/></text>')
        s.text(big, 22, 102, "SRSerifI", 38, ink, extra=f'style="animation:fade .01s linear {t0 + frames * .06:.2f}s both"')
    else:
        s.text(big, 22, 102, "SRSerifI", 38, ink)
    for i, line in enumerate(textwrap.wrap(t["text"], 31)[:4]):
        s.text(line, 22, 138 + i * 18, "SRSans", 13, ink)
    s.add("</g>")
    return s.render()


def title(p, color):
    s = Svg(800, 64)
    s.mixed([(p["repos_title"][0] + " ", "SRSerif", color), (p["repos_title"][1], "SRSerifI", color)], 8, 46, 34)
    return s.render()


def repo_card(r, delay):
    s = Svg(262, 156)
    s.css.append(KEYFRAMES)
    s.add(f'<g style="{anim("rise", .8, delay)}">')
    s.add(f'<rect width="262" height="156" rx="18" fill="{PAPER}"/>')
    s.add(f'<circle cx="28" cy="34" r="5" fill="{r["color"]}"/>')
    s.text(r["name"], 42, 40, "SRSerif", 21, INK)
    for i, line in enumerate(textwrap.wrap(r["description"] or "No description yet.", 33)[:3]):
        s.text(line, 24, 70 + i * 18, "SRSans", 12.5, MUTED)
    foot = (r["language"] + "  ·  " if r["language"] else "") + f"★ {r['stars']}"
    s.text(foot, 24, 138, "SRMono", 10.5, MUTED)
    s.add("</g>")
    return s.render()


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()
    p = json.loads((DATA / "profile.json").read_text())
    login = os.environ.get("USERNAME_GH") or p["github_username"]
    token = os.environ.get("GITHUB_TOKEN")
    cache = DATA / "contributions.json"
    repos = []
    if args.demo:
        cal, repos = demo_data()
    else:
        try:
            if not token:
                raise RuntimeError("GITHUB_TOKEN not set")
            cal, repos = gh_graphql(login, token)
            cache.write_text(json.dumps(cal))
        except Exception as e:  # fall back to the last good snapshot
            print("fetch failed:", e, file=sys.stderr)
            if not cache.exists():
                sys.exit("no cached data/contributions.json; run with --demo or set GITHUB_TOKEN")
            cal = json.loads(cache.read_text())
    wanted = p.get("featured_repos") or []
    pool = [r for r in repos if r["name"].lower() != login.lower()]
    picks = [r for n in wanted for r in pool if r["name"] == n] if wanted else pool
    picks = (picks + [{"name": "coming soon", "description": "Add a public repo and it shows up here.",
                       "stars": 0, "language": "", "color": MUTED}] * 3)[:3]

    CARDS.mkdir(exist_ok=True)
    out = {"hero": hero(p), "heatmap": heatmap(cal), "activity": activity(cal),
           "title-building-light": title(p, INK), "title-building-dark": title(p, "#F3F1F7")}
    palette = [(TEAL, "#FFFFFF"), (PINK, "#FFFFFF"), (SUN, INK)]
    for i, (t, (c, ink)) in enumerate(zip(p["tiles"], palette)):
        out[f"tile-{i + 1}"] = tile(t, c, ink, 0.3 + i * .18)
    for i, r in enumerate(picks):
        out[f"repo-{i + 1}"] = repo_card(r, 0.3 + i * .15)
    for name, svg in out.items():
        (CARDS / f"{name}.svg").write_text(svg, encoding="utf-8")
        print(f"cards/{name}.svg  {len(svg) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
