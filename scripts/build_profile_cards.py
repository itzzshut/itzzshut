#!/usr/bin/env python3
"""
Build the "Rose Noir" profile cards from live GitHub data:

    card-hero.svg           handle, name, tagline, stack pills
    card-scan.svg           ./profile-scan terminal: ASCII avatar + system info
    card-projects.svg       featured repos with main-language donuts
    card-languages.svg      repository-weighted language bars
    card-contributions.svg  contribution grid eaten by a cute snake + streak stats
    card-summary.svg        all-time totals + monthly contributions chart
    card-stack.svg          tech stack chips with brand icons

Data comes from the public GitHub REST API (GITHUB_TOKEN is used when set)
and the public contributions calendar. Needs Pillow for the avatar / ASCII art.
Run daily by .github/workflows/profile-cards.yml, which publishes the output
directory to the "cards" branch.

    python scripts/build_profile_cards.py [output_dir]
"""
import base64
import datetime
import io
import json
import os
import re
import sys
import urllib.request
from xml.sax.saxutils import escape

from PIL import Image, ImageFilter, ImageOps

USER = os.environ.get("GH_PROFILE_USER", "itzzshut")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT = sys.argv[1] if len(sys.argv) > 1 else "dist"
# head-and-shoulders photo with the background cut out (alpha); falls back to the GitHub avatar
PORTRAIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "portrait.png")

NAME = "Mariam Malik"
TAGLINE = "Software Engineer · B.E. CSE, Jadavpur University · Full-stack apps"
PILLS = ["React", "Next.js", "Node.js", "Hono", "PostgreSQL"]
SCAN_ROWS = [  # live values are filled in below
    ("Subject", NAME),
    ("Handle", f"@{USER}"),
    ("Role", "Full-Stack Engineer"),
    ("Education", "B.E. CSE · Jadavpur '26"),
    ("Status", "Building · Shipping"),
]
STACK = [  # category, [(label, simple-icons slug or None for a monogram)]
    ("Languages", [("JavaScript", "javascript"), ("C++", "cplusplus"), ("Java", "openjdk"),
                   ("HTML", "html5"), ("CSS", "css3"), ("SQL", None)]),
    ("Frontend", [("React", "react"), ("Next.js", "nextdotjs"), ("Tailwind CSS", "tailwindcss"),
                  ("ShadCN UI", "shadcnui"), ("TanStack", "reactquery"), ("React Flow", None), ("Zustand", None)]),
    ("Backend", [("Node.js", "nodedotjs"), ("Express", "express"), ("Bun", "bun"), ("Hono", "hono"),
                 ("oRPC", None), ("Inngest", None), ("JWT", "jsonwebtokens")]),
    ("Data", [("PostgreSQL", "postgresql"), ("MongoDB", "mongodb"), ("Redis", "redis"),
              ("Prisma", "prisma"), ("Drizzle ORM", "drizzle")]),
    ("Tools", [("Git", "git"), ("GitHub", "github"), ("Vercel", "vercel"), ("Postman", "postman"),
               ("Clerk", "clerk"), ("Stripe", "stripe"), ("Cloudinary", "cloudinary"),
               ("Gemini", "googlegemini"), ("Slack API", "slack")]),
]
ICONS = "https://cdn.jsdelivr.net/npm/simple-icons@13.21.0/icons"
FEATURED = [  # repo, display title, description
    ("sensai", "AI Career Coach",
     "Gemini-powered career coach: resumes, cover letters and mock interviews."),
    ("spark-kafka-cassandra-pipeline", "Spark Streaming Pipeline",
     "API → Kafka → Spark Structured Streaming → Cassandra, scheduled by Airflow."),
    ("Vehiql", "Vehiql",
     "AI car marketplace with Gemini image search and test-drive booking."),
    ("real-time-financial-analysis-trading-system", "Real-Time Trading",
     "Kafka microservices computing EMA / RSI and streaming live trade signals."),
]

# ---- palette "Rose Noir": deep wine cards lit by pink and peach glows -------
BG1, BG2 = "#1C0A13", "#38142A"                                    # card base
PAPER, CREAM, SAND, LINE = "#2A1120", "#32162A", "#4C2338", "#6E2F4C"  # panels, bars, tracks, borders
BLUSH, PINK, ROSE, DEEP, WINE = "#E07A93", "#F2A7B8", "#F48FAB", "#F9C3D1", "#FFE3EA"
COCOA, MUTED, CARAMEL, MAUVE = "#F6E7E1", "#C49DA4", "#EDB98F", "#CFA0C8"  # COCOA = body text
HEAT = ["#341827", "#6A2645", "#A8456A", "#E07A93", "#FFC2D1"]
LANG_COLORS = [ROSE, CARAMEL, MAUVE, "#FFC2D1", "#E0707F", "#C9A88F", "#F7D6DF", "#B98AA0"]

SERIF = "Georgia,'Times New Roman',serif"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Consolas,'Liberation Mono',Menlo,monospace"
W = 860


# ---- data -------------------------------------------------------------------
def get(url, raw=False):
    headers = {"User-Agent": "profile-cards/1.0"}
    if TOKEN and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {TOKEN}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        body = r.read()
    return body if raw else json.loads(body)


def fetch_contributions(query=""):
    html = get(f"https://github.com/users/{USER}/contributions{query}", raw=True).decode("utf-8")
    tips = dict(re.findall(r'<tool-tip[^>]*\bfor="([^"]+)"[^>]*>([^<]*)</tool-tip>', html))
    days = []
    for tag in re.findall(r"<td[^>]*ContributionCalendar-day[^>]*>", html):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', tag))
        if not attrs.get("data-date"):
            continue
        m = re.match(r"(\d[\d,]*)", tips.get(attrs.get("id", ""), "").strip())
        days.append({
            "date": attrs["data-date"],
            "count": int(m.group(1).replace(",", "")) if m else 0,
            "level": int(attrs.get("data-level") or 0),
        })
    if not days:
        sys.exit("no contribution cells found -- GitHub markup may have changed")
    return sorted(days, key=lambda d: d["date"])


def streaks(days):
    longest = run = 0
    for d in days:
        run = run + 1 if d["count"] else 0
        longest = max(longest, run)
    i = len(days) - 1
    if days[i]["count"] == 0:
        i -= 1  # today isn't over yet
    current = 0
    while i >= 0 and days[i]["count"]:
        current, i = current + 1, i - 1
    return current, longest


def ago(iso):
    days = (datetime.datetime.now(datetime.timezone.utc)
            - datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))).days
    if days < 1:
        return "updated today"
    if days < 30:
        return f"updated {days}d ago"
    if days < 365:
        return f"updated {days // 30}mo ago"
    return f"updated {days // 365}y ago"


def collect():
    user = get(f"https://api.github.com/users/{USER}")
    repos = [r for r in get(f"https://api.github.com/users/{USER}/repos?per_page=100&type=owner")
             if not r["fork"] and r["name"].lower() != USER.lower()]
    weights, repo_langs = {}, {}
    for r in repos:
        langs = get(r["languages_url"])
        repo_langs[r["name"]] = langs
        total = sum(langs.values())
        for lang, n in langs.items():  # every repo counts equally
            weights[lang] = weights.get(lang, 0) + n / total
    wsum = sum(weights.values()) or 1
    languages = sorted(((k, 100 * v / wsum) for k, v in weights.items()), key=lambda x: -x[1])

    days = fetch_contributions()
    current, longest = streaks(days)
    joined = datetime.date.fromisoformat(user["created_at"][:10])
    all_days = {}
    for year in range(joined.year, datetime.date.today().year + 1):
        for d in fetch_contributions(f"?from={year}-01-01&to={year}-12-31"):
            all_days[d["date"]] = d["count"]
    monthly = {}
    for d in days:
        monthly[d["date"][:7]] = monthly.get(d["date"][:7], 0) + d["count"]
    best = max(days, key=lambda d: d["count"])
    avatar = get(f"{user['avatar_url']}&s=240" if "?" in user["avatar_url"]
                 else f"{user['avatar_url']}?s=240", raw=True)
    by_name = {r["name"]: r for r in repos}
    featured = []
    for name, title, desc in FEATURED:
        r, langs = by_name.get(name), repo_langs.get(name, {})
        if not r:
            continue
        main = max(langs, key=langs.get) if langs else "—"
        share = 100 * langs[main] / sum(langs.values()) if langs else 0
        featured.append({"name": name, "title": title, "desc": desc, "lang": main,
                         "share": share, "stars": r["stargazers_count"], "updated": ago(r["pushed_at"])})
    return {
        "repos": user["public_repos"], "followers": user["followers"],
        "stars": sum(r["stargazers_count"] for r in repos),
        "languages": languages, "featured": featured, "avatar": avatar, "days": days,
        "total": sum(d["count"] for d in days), "active": sum(1 for d in days if d["count"]),
        "current": current, "longest": longest, "best": best,
        "all_time": sum(all_days.values()), "joined": joined, "location": user.get("location") or "",
        "monthly": sorted(monthly.items()),
    }


# ---- shared drawing ---------------------------------------------------------
def lang_color(data, lang):
    names = [n for n, _ in data["languages"]]
    return LANG_COLORS[names.index(lang) % len(LANG_COLORS)] if lang in names else MUTED


def frame(h, body, extra_defs="", extra_css=""):
    """Wine card with drifting, pulsing glows, a sheen sweep, rounded border and a corner tag."""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" font-family="{SANS}">
<defs>
  <linearGradient id="paper" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="{BG1}"/><stop offset="55%" stop-color="{BG2}"/><stop offset="100%" stop-color="{BG1}"/></linearGradient>
  <linearGradient id="sheen" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="#FFFFFF" stop-opacity="0"/><stop offset="50%" stop-color="#FFE3EA" stop-opacity=".09"/><stop offset="100%" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient>
  <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="48"/></filter>
  <clipPath id="card"><rect x="1" y="1" width="{W - 2}" height="{h - 2}" rx="22"/></clipPath>
  {extra_defs}
</defs>
<style>
  .fade {{ opacity:0; animation:fade .8s ease-out forwards; }}
  @keyframes fade {{ from {{ opacity:0; transform:translateY(6px); }} to {{ opacity:1; transform:none; }} }}
  @keyframes blink {{ 50% {{ opacity:0; }} }}
  .blink {{ animation:blink 1.1s steps(1) infinite; }}
  {extra_css}
  @media (prefers-reduced-motion: reduce) {{ * {{ animation:none !important; opacity:1 !important; transform:none !important; }} }}
</style>
<g clip-path="url(#card)">
  <rect width="{W}" height="{h}" fill="url(#paper)"/>
  <g filter="url(#glow)">
    <circle cx="90" cy="30" r="95" fill="{BLUSH}" opacity=".55">
      <animate attributeName="cx" values="90;190;90" dur="14s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values=".55;.2;.55" dur="7s" repeatCount="indefinite"/></circle>
    <circle cx="{W - 110}" cy="{h - 20}" r="105" fill="#C2557A" opacity=".6">
      <animate attributeName="cy" values="{h - 20};{h - 100};{h - 20}" dur="12s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values=".3;.65;.3" dur="9s" repeatCount="indefinite"/></circle>
    <circle cx="{W // 2}" cy="{h + 30}" r="95" fill="{CARAMEL}" opacity=".35">
      <animate attributeName="cx" values="{W // 2};{W // 2 - 120};{W // 2}" dur="16s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values=".35;.12;.35" dur="8s" repeatCount="indefinite"/></circle>
    <circle cx="{W - 60}" cy="20" r="60" fill="{MAUVE}" opacity=".25">
      <animate attributeName="opacity" values=".1;.35;.1" dur="10s" repeatCount="indefinite"/></circle>
  </g>
  <rect x="-300" y="0" width="240" height="{h}" fill="url(#sheen)" transform="skewX(-18)">
    <animate attributeName="x" values="-300;{W + 300};{W + 300}" keyTimes="0;.4;1" dur="8s" repeatCount="indefinite"/>
  </rect>
  {body}
</g>
<rect x="1" y="1" width="{W - 2}" height="{h - 2}" rx="22" fill="none" stroke="{LINE}" stroke-width="1.5"/>
<text x="{W - 22}" y="{h - 12}" text-anchor="end" font-size="10" fill="{MUTED}" opacity=".8">{USER} · github</text>
</svg>'''


def heading(x, y, title, sub):
    return (f'<text class="fade" x="{x}" y="{y}" font-family="{SERIF}" font-size="30" font-weight="700" '
            f'font-style="italic" fill="{DEEP}">{escape(title)}</text>'
            f'<text class="fade" style="animation-delay:.2s" x="{x}" y="{y + 26}" font-size="13.5" '
            f'font-weight="600" fill="{COCOA}">{escape(sub)}</text>')


def wrap(text, width):
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line]


# ---- cards ------------------------------------------------------------------
def hero(data):
    h = 210
    widths = [int(len(p) * 7.6 + 30) for p in PILLS]
    x, pills = (W - sum(widths) - 10 * (len(PILLS) - 1)) / 2, []
    for i, (p, w) in enumerate(zip(PILLS, widths)):
        pills.append(
            f'<g class="fade" style="animation-delay:{.9 + i * .12:.2f}s">'
            f'<rect x="{x:.1f}" y="146" width="{w}" height="30" rx="15" fill="{PAPER}" stroke="{PINK}" stroke-width="1.5"/>'
            f'<text x="{x + w / 2:.1f}" y="166" text-anchor="middle" font-size="13" font-weight="700" fill="{DEEP}">{escape(p)}</text></g>')
        x += w + 10
    sparkles = "".join(
        f'<text x="{sx}" y="{sy}" font-size="{fs}" fill="{fill}">✦<animate attributeName="opacity" values="{v}" dur="{d}s" repeatCount="indefinite"/></text>'
        for sx, sy, fs, fill, v, d in [
            (70, 66, 14, ROSE, "1;.2;1", 2.6), (48, 92, 9, ROSE, ".2;1;.2", 3.1), (92, 104, 10, CARAMEL, "1;.3;1", 3.7),
            (W - 84, 58, 14, ROSE, ".3;1;.3", 2.9), (W - 60, 84, 9, ROSE, "1;.2;1", 3.3), (W - 104, 96, 10, CARAMEL, ".2;1;.2", 3.9)])
    body = f'''
  <path d="M 60 22 C 260 2, 600 44, 800 14" fill="none" stroke="{PINK}" stroke-width="1.2" opacity=".7"/>
  {sparkles}
  <text class="fade" x="{W / 2}" y="52" text-anchor="middle" font-family="{MONO}" font-size="14" font-weight="700" fill="{ROSE}" letter-spacing="1">@{USER}</text>
  <text class="fade" style="animation-delay:.25s" x="{W / 2}" y="104" text-anchor="middle" font-family="{SERIF}" font-size="50" font-weight="700" font-style="italic" fill="url(#name)">{NAME}</text>
  <text class="fade" style="animation-delay:.5s" x="{W / 2}" y="132" text-anchor="middle" font-size="15.5" font-weight="500" fill="{COCOA}">{escape(TAGLINE)}</text>
  {"".join(pills)}'''
    name_grad = f'''<linearGradient id="name" x1="{W / 2 - 200}" y1="0" x2="{W / 2 + 200}" y2="0" gradientUnits="userSpaceOnUse">
    <stop offset="0%" stop-color="{DEEP}"><animate attributeName="stop-color" values="{DEEP};{ROSE};{CARAMEL};{DEEP}" dur="9s" repeatCount="indefinite"/></stop>
    <stop offset="100%" stop-color="{ROSE}"><animate attributeName="stop-color" values="{ROSE};{CARAMEL};{WINE};{ROSE}" dur="9s" repeatCount="indefinite"/></stop>
  </linearGradient>'''
    return frame(h, body, extra_defs=name_grad)


def ascii_art(data, cols=74, line_h=7.6, font=7.0):
    """Portrait as rows of (char, tone) cells: brighter pixels get denser, lighter-pink characters."""
    if os.path.exists(PORTRAIT):
        img = Image.open(PORTRAIT).convert("RGBA")
    else:
        img = Image.open(io.BytesIO(data["avatar"])).convert("RGBA")
    alpha = img.getchannel("A")
    gray = ImageOps.autocontrast(img.convert("L"), cutoff=1)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=12, percent=320, threshold=0))  # keep eyes, brows, hair strands
    gray = ImageOps.equalize(gray, mask=alpha.point(lambda v: 255 if v > 128 else 0))
    gray = gray.point(lambda v: int(255 * (v / 255) ** 1.25))  # keep the face from flattening into solid '@'
    rows = round(cols * img.height / img.width * (font * .6) / line_h)
    g = gray.resize((cols, rows), Image.LANCZOS)
    m = alpha.resize((cols, rows), Image.LANCZOS)
    ramp = " .,:;-=+*#%@"
    lines = []
    for r in range(rows):
        cells = []
        for c in range(cols):
            if m.getpixel((c, r)) < 110:
                cells.append((" ", 0))
                continue
            v = g.getpixel((c, r)) / 255
            cells.append((ramp[max(1, min(len(ramp) - 1, int(v * len(ramp))))], min(4, int(v * 5))))
        lines.append(cells)
    return lines


def scan(data):
    h = 470
    top_langs = ""
    for n, _ in data["languages"][:4]:  # as many as fit the value column
        if len(f"{top_langs}, {n}") > 27:
            break
        top_langs = f"{top_langs}, {n}" if top_langs else n
    rows = SCAN_ROWS + [
        ("Languages", top_langs),
        ("Repositories", f"{data['repos']}"),
        ("Contributions", f"{data['total']:,} (last year)"),
        ("Stars", f"{data['stars']}"),
        ("Followers", f"{data['followers']}"),
        ("Active days", f"{data['active']}"),
        ("Contact", f"github.com/{USER}"),
    ]
    art = ascii_art(data)
    tones = ["#6E2F4C", "#A8456A", ROSE, "#F7B6C6", WINE]
    art_w, line_h = 311, 7.6
    art_lines = []
    for i, cells in enumerate(art):
        runs, prev = [], None  # merge neighbouring characters of the same tone into one tspan
        for ch, tone in cells:
            if runs and tone == prev:
                runs[-1][1] += ch
            else:
                runs.append([tone, ch])
            prev = tone
        tspans = "".join(f'<tspan fill="{tones[t]}">{escape(txt)}</tspan>' for t, txt in runs)
        art_lines.append(f'<text x="{222 - art_w / 2}" y="{100 + i * line_h:.1f}" textLength="{art_w}" '
                         f'lengthAdjust="spacing" xml:space="preserve">{tspans}</text>')
    info = []
    for i, (k, v) in enumerate(rows):
        y = 106 + i * 26.5
        d = f"{.4 + i * .12:.2f}"
        info.append(
            f'<g class="fade" style="animation-delay:{d}s">'
            f'<text x="454" y="{y}" font-weight="700" fill="{DEEP}">{escape(k)}</text>'
            f'<text x="560" y="{y}" fill="{LINE}" letter-spacing="1">··········</text>'
            f'<text x="652" y="{y}" fill="{COCOA}">{escape(v[:27])}</text></g>')
    body = f'''
  <rect x="0" y="0" width="{W}" height="40" fill="{CREAM}"/>
  <line x1="0" y1="40" x2="{W}" y2="40" stroke="{LINE}"/>
  <circle cx="24" cy="20" r="6" fill="#F28B9B"/><circle cx="44" cy="20" r="6" fill="#F2C38B"/><circle cx="64" cy="20" r="6" fill="#B9D3A8"/>
  <text x="{W / 2}" y="24" text-anchor="middle" font-family="{MONO}" font-size="12" fill="{COCOA}">{USER}@github ~ $ ./profile-scan --live<tspan class="blink" fill="{ROSE}">▍</tspan></text>
  <circle cx="{W - 70}" cy="20" r="4" fill="{ROSE}"><animate attributeName="opacity" values="1;.25;1" dur="1.4s" repeatCount="indefinite"/></circle>
  <text x="{W - 60}" y="24" font-family="{MONO}" font-size="11" font-weight="700" fill="{ROSE}">LIVE</text>

  <rect x="20" y="58" width="404" height="386" rx="14" fill="{PAPER}" fill-opacity=".75" stroke="{LINE}"/>
  <rect x="436" y="58" width="404" height="386" rx="14" fill="{PAPER}" fill-opacity=".75" stroke="{LINE}"/>
  <text x="38" y="80" font-family="{MONO}" font-size="10" font-weight="700" fill="{ROSE}" letter-spacing="2">VISUAL.MAP</text>
  <text x="454" y="80" font-family="{MONO}" font-size="10" font-weight="700" fill="{ROSE}" letter-spacing="2">SYSTEM.INFO</text>
  <g font-family="{MONO}" font-size="7" font-weight="700">{"".join(art_lines)}</g>
  <g font-family="{MONO}" font-size="12">{"".join(info)}</g>
  <rect x="20" y="58" width="820" height="26" fill="url(#scanline)" opacity=".55">
    <animate attributeName="y" values="58;420;58" dur="7s" repeatCount="indefinite"/>
  </rect>'''
    scanline = f'''<linearGradient id="scanline" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="{PINK}" stop-opacity="0"/><stop offset="50%" stop-color="{PINK}" stop-opacity=".55"/><stop offset="100%" stop-color="{PINK}" stop-opacity="0"/>
  </linearGradient>'''
    return frame(h, body, extra_defs=scanline)


def projects(data):
    items = data["featured"]
    card_w, card_h, gap = 394, 178, 16
    n_rows = (len(items) + 1) // 2
    h = 96 + n_rows * (card_h + gap) + 20
    cards = []
    for i, p in enumerate(items):
        x = 28 + (i % 2) * (card_w + gap)
        y = 92 + (i // 2) * (card_h + gap)
        color = lang_color(data, p["lang"])
        r, cx, cy = 30, x + card_w - 62, y + 96
        circ = 2 * 3.14159 * r
        dash = circ * p["share"] / 100
        desc = "".join(f'<text x="{x + 18}" y="{y + 86 + j * 17}">{escape(l)}</text>'
                       for j, l in enumerate(wrap(p["desc"], 36)[:3]))
        pill_w = int(len(p["lang"]) * 6.6 + 22)
        cards.append(f'''
  <g class="fade" style="animation-delay:{.2 + i * .15:.2f}s">
    <rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="14" fill="{PAPER}" stroke="{LINE}"/>
    <path d="M {x} {y + 30} H {x + card_w}" stroke="{LINE}"/>
    <text x="{x + 16}" y="{y + 20}" font-family="{MONO}" font-size="11" fill="{MUTED}"><tspan fill="{ROSE}">●</tspan> {USER}/{escape(p["name"] if len(p["name"]) <= 34 else p["name"][:33] + "…")}</text>
    <circle cx="{x + card_w - 18}" cy="{y + 15}" r="4" fill="{PINK}"/>
    <text x="{x + 18}" y="{y + 58}" font-family="{MONO}" font-size="16.5" font-weight="700" fill="{DEEP}">{escape(p["title"])} <tspan class="blink" fill="{ROSE}">_</tspan></text>
    <g font-family="{MONO}" font-size="11.5" fill="{COCOA}">{desc}</g>
    <rect x="{x + 18}" y="{y + card_h - 38}" width="{pill_w}" height="20" rx="10" fill="{CREAM}" stroke="{color}"/>
    <text x="{x + 18 + pill_w / 2}" y="{y + card_h - 24}" text-anchor="middle" font-family="{MONO}" font-size="10.5" font-weight="700" fill="{color}">{escape(p["lang"])}</text>
    <text x="{x + 30 + pill_w}" y="{y + card_h - 24}" font-family="{MONO}" font-size="10.5" fill="{MUTED}"><tspan fill="{CARAMEL}">★</tspan> {p["stars"]} · {p["updated"]}</text>
    <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{SAND}" stroke-width="9"/>
    <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="9" stroke-linecap="round"
      stroke-dasharray="{dash:.1f} {circ:.1f}" stroke-dashoffset="{dash:.1f}" transform="rotate(-90 {cx} {cy})">
      <animate attributeName="stroke-dashoffset" from="{dash:.1f}" to="0" dur="1.4s" begin="{.4 + i * .15:.2f}s" fill="freeze"/>
    </circle>
    <text x="{cx}" y="{cy + 4}" text-anchor="middle" font-family="{MONO}" font-size="12" font-weight="700" fill="{COCOA}">{p["share"]:.0f}%</text>
  </g>''')
    body = f'''
  <text x="28" y="48" font-family="{MONO}" font-size="14" font-weight="700" fill="{DEEP}" letter-spacing="3">PROJECTS.LIST</text>
  <text x="196" y="48" font-family="{MONO}" font-size="12" fill="{MUTED}">./projects.sh --featured</text>
  <text x="{W - 28}" y="48" text-anchor="end" font-family="{MONO}" font-size="12" fill="{ROSE}">{len(items)} projects</text>
  <line x1="28" y1="64" x2="{W - 28}" y2="64" stroke="{PINK}" stroke-width="1.2"/>
  {"".join(cards)}'''
    return frame(h, body)


def languages(data):
    langs = data["languages"][:6]
    h = 120 + len(langs) * 36 + 20
    rows = []
    for i, (name, share) in enumerate(langs):
        y = 124 + i * 36
        color = lang_color(data, name)
        bar = 440 * share / max(s for _, s in langs)
        d = f"{.3 + i * .12:.2f}"
        rows.append(f'''
  <g class="fade" style="animation-delay:{d}s">
    <circle cx="52" cy="{y - 5}" r="6" fill="{color}"/>
    <text x="70" y="{y}" font-size="14.5" font-weight="700" fill="{COCOA}">{escape(name)}</text>
    <text x="318" y="{y}" text-anchor="end" font-size="14.5" font-weight="700" fill="{color}">{share:.0f}%</text>
    <rect x="356" y="{y - 11}" width="452" height="11" rx="5.5" fill="{SAND}" opacity=".7"/>
    <rect x="356" y="{y - 11}" width="{bar:.1f}" height="11" rx="5.5" fill="{color}">
      <animate attributeName="width" from="0" to="{bar:.1f}" dur="1.2s" begin="{d}s" fill="freeze"/>
    </rect>
  </g>''')
    body = f'''
  {heading(40, 58, "Language Stack", "Repository-weighted across public repos")}
  <text x="{W - 40}" y="54" text-anchor="end" font-family="{MONO}" font-size="13" font-weight="700" fill="{ROSE}">&gt; stack.scan <tspan class="blink">_</tspan></text>
  {"".join(rows)}'''
    return frame(h, body)


def contributions(data):
    days = data["days"]
    first = datetime.date.fromisoformat(days[0]["date"])
    week0 = first - datetime.timedelta(days=(first.weekday() + 1) % 7)
    cell, gap, left, top = 11, 3.2, 74, 124
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    def pos(d):
        off = (datetime.date.fromisoformat(d["date"]) - week0).days
        return off // 7, off % 7

    n_weeks = pos(days[-1])[0] + 1
    rects, labels, last_m = [], [], None
    for wk in range(n_weeks):
        d = week0 + datetime.timedelta(days=wk * 7 + 6)
        if d.month != last_m and wk < n_weeks - 2:
            last_m = d.month
            labels.append(f'<text x="{left + wk * (cell + gap)}" y="{top - 8}">{months[d.month - 1]}</text>')
    for name, r in [("Mon", 1), ("Wed", 3), ("Fri", 5)]:
        labels.append(f'<text x="40" y="{top + r * (cell + gap) + cell - 2}">{name}</text>')

    # A cute snake slithers week by week through the grid, eating each contribution as it passes;
    # the eaten squares grow back when the loop restarts.
    cells = {pos(d): d for d in days}
    order = []
    for wk in range(n_weeks):
        for row in (range(7) if wk % 2 == 0 else range(6, -1, -1)):
            if (wk, row) in cells:
                order.append((wk, row))
    center = lambda wk, row: (left + wk * (cell + gap) + cell / 2, top + row * (cell + gap) + cell / 2)
    pts = [center(*c) for c in order]
    path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    walk, begin = .9, 3.0                        # share of the loop spent moving; start after the pop-in
    dur = len(order) * .075 / walk
    step = dur * walk / (len(order) - 1)        # seconds per square
    index = {c: i for i, c in enumerate(order)}
    for d in days:
        wk, row = pos(d)
        lvl = max(0, min(4, d["level"]))
        delay = (wk + row * .5) / (n_weeks + 3) * 2.6
        eat = ""
        if lvl:
            t = max(.001, walk * index[(wk, row)] / (len(order) - 1))
            eat = (f'<animate attributeName="fill" values="{HEAT[lvl]};{HEAT[0]};{HEAT[lvl]}" keyTimes="0;{t:.4f};.985" '
                   f'calcMode="discrete" dur="{dur:.2f}s" begin="{begin}s" repeatCount="indefinite"/>')
        rects.append(
            f'<rect class="c" x="{left + wk * (cell + gap):.1f}" y="{top + row * (cell + gap):.1f}" width="{cell}" '
            f'height="{cell}" rx="2.6" fill="{HEAT[lvl]}" style="animation-delay:{delay:.2f}s">{eat}'
            f'<title>{d["count"]} contribution{"" if d["count"] == 1 else "s"} on {d["date"]}</title></rect>')
    legend = "".join(f'<rect x="{W - 150 + i * 15}" y="45" width="11" height="11" rx="2.6" fill="{c}"/>'
                     for i, c in enumerate(HEAT))
    grid_bottom = top + 7 * (cell + gap)
    best = data["best"]
    stats = [("Current streak", f"{data['current']} days"), ("Longest streak", f"{data['longest']} days"),
             ("Best day", f"{best['count']} on {datetime.date.fromisoformat(best['date']):%d %b}"),
             ("Active days", f"{data['active']}")]
    tiles = []
    tw = (W - 80 - 3 * 14) / 4
    for i, (k, v) in enumerate(stats):
        x = 40 + i * (tw + 14)
        tiles.append(
            f'<g class="fade" style="animation-delay:{2.6 + i * .15:.2f}s">'
            f'<rect x="{x:.1f}" y="{grid_bottom + 22}" width="{tw:.1f}" height="58" rx="12" fill="{PAPER}" stroke="{LINE}"/>'
            f'<text x="{x + tw / 2:.1f}" y="{grid_bottom + 47}" text-anchor="middle" font-family="{SERIF}" font-size="19" font-weight="700" fill="{DEEP}">{escape(v)}</text>'
            f'<text x="{x + tw / 2:.1f}" y="{grid_bottom + 67}" text-anchor="middle" font-size="11.5" font-weight="600" fill="{MUTED}">{k}</text></g>')
    h = grid_bottom + 22 + 58 + 34

    motion = (f'dur="{dur:.2f}s" repeatCount="indefinite" rotate="auto" keyPoints="0;1;1" keyTimes="0;{walk};1" '
              f'calcMode="linear"><mpath href="#snakepath"/></animateMotion>')
    segments = []
    for i, r in reversed(list(enumerate([7.2, 6.9, 6.6, 6.2, 5.8, 5.4, 5.0, 4.5, 4.0, 3.4]))):
        fill = PINK if i % 2 else ROSE
        lag = begin + (i + 1) * step * .62
        segments.append(f'<g opacity="0"><set attributeName="opacity" to="1" begin="{lag:.2f}s"/>'
                        f'<circle r="{r}" fill="{fill}" stroke="{BG1}" stroke-width=".9"/>'
                        f'<animateMotion begin="{lag:.2f}s" {motion}</g>')
    head = f'''<g opacity="0"><set attributeName="opacity" to="1" begin="{begin}s"/><g transform="scale(1.35)">
    <path d="M 7 0 l 4.5 0 l 2 -1.6 M 11.5 0 l 2 1.6" stroke="#FF5C7A" stroke-width="1.2" stroke-linecap="round" fill="none">
      <animate attributeName="opacity" values="1;1;0;0;1" keyTimes="0;.4;.45;.9;1" dur="1.2s" repeatCount="indefinite"/></path>
    <ellipse rx="8" ry="7" fill="{ROSE}" stroke="{BG1}" stroke-width=".8"/>
    <ellipse cx="-1" cy="-4.6" rx="1.9" ry="1.2" fill="#FF9FB5" opacity=".9"/><ellipse cx="-1" cy="4.6" rx="1.9" ry="1.2" fill="#FF9FB5" opacity=".9"/>
    <circle cx="2.8" cy="-2.8" r="2.4" fill="#FFFFFF"/><circle cx="2.8" cy="2.8" r="2.4" fill="#FFFFFF"/>
    <circle cx="3.6" cy="-2.6" r="1.25" fill="#2A1120"/><circle cx="3.6" cy="2.6" r="1.25" fill="#2A1120"/>
    <circle cx="4" cy="-3.1" r=".45" fill="#FFFFFF"/><circle cx="4" cy="2.1" r=".45" fill="#FFFFFF"/></g>
    <animateMotion begin="{begin}s" {motion}</g>'''
    snake = "".join(segments) + head
    body = f'''
  {heading(40, 58, "Contribution Activity", f"{data['total']:,} contributions in the last year")}
  <text x="{W - 186}" y="55" text-anchor="end" font-size="11.5" fill="{MUTED}">Less</text>{legend}<text x="{W - 72}" y="55" font-size="11.5" fill="{MUTED}">More</text>
  <g font-size="11" font-weight="600" fill="{MUTED}">{"".join(labels)}</g>
  {"".join(rects)}
  <path id="snakepath" d="{path}" fill="none"/>
  {snake}
  {"".join(tiles)}'''
    css = (".c { transform-box:fill-box; transform-origin:center; opacity:0; animation:pop .5s ease-out forwards; }"
           " @keyframes pop { from { opacity:0; transform:scale(.3); } to { opacity:1; transform:scale(1); } }")
    return frame(h, body, extra_css=css)


def summary(data):
    h = 260
    total = data["all_time"]
    total_txt = f"{total / 1000:.2f}".rstrip("0").rstrip(".") + "k" if total >= 1000 else str(total)
    years = (datetime.date.today() - data["joined"]).days // 365
    facts = [f"{total_txt} contributions on GitHub", f"{data['repos']} public repos",
             f"Joined GitHub {years} year{'' if years == 1 else 's'} ago"]
    if data["location"]:
        facts.append(data["location"])
    rows = "".join(
        f'<g class="fade" style="animation-delay:{.3 + i * .15:.2f}s"><text x="40" y="{112 + i * 34}" font-size="13" fill="{ROSE}">✦</text>'
        f'<text x="62" y="{112 + i * 34}" font-size="16" fill="{COCOA}">{escape(f)}</text></g>' for i, f in enumerate(facts))

    months = data["monthly"]
    x0, x1, y0, y1 = 430, 792, 70, 200
    top = max(20, -(-max(v for _, v in months) // 20) * 20)
    pts = [(x0 + i * (x1 - x0) / (len(months) - 1), y1 - v / top * (y1 - y0)) for i, (_, v) in enumerate(months)]
    path = f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"
    for i in range(len(pts) - 1):  # Catmull-Rom -> cubic Bezier, clamped to the baseline
        p0, p1, p2 = pts[max(i - 1, 0)], pts[i], pts[i + 1]
        p3 = pts[min(i + 2, len(pts) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, min(y1, p1[1] + (p2[1] - p0[1]) / 6))
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, min(y1, p2[1] - (p3[1] - p1[1]) / 6))
        path += f" C {c1[0]:.1f} {c1[1]:.1f}, {c2[0]:.1f} {c2[1]:.1f}, {p2[0]:.1f} {p2[1]:.1f}"
    step = max(20, top // 5 // 20 * 20)
    ticks = "".join(
        f'<line x1="{x1}" y1="{y1 - t / top * (y1 - y0):.1f}" x2="{x1 + 5}" y2="{y1 - t / top * (y1 - y0):.1f}" stroke="{MUTED}"/>'
        f'<text x="{x1 + 9}" y="{y1 - t / top * (y1 - y0) + 4:.1f}">{t}</text>'
        for t in range(0, top + 1, step))
    xlabels = "".join(
        f'<text x="{pts[i][0]:.1f}" y="{y1 + 20}" text-anchor="middle">{m[2:4]}/{m[5:7]}</text>'
        for i, (m, _) in enumerate(months) if i % 2 == 0)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{WINE}" stroke="{ROSE}" stroke-width="1.5"/>' for x, y in pts)
    body = f"""
  <text class="fade" x="40" y="62" font-family="{SERIF}" font-size="27" font-weight="700" font-style="italic" fill="{DEEP}">{USER} <tspan fill="{ROSE}" font-size="22">({NAME})</tspan></text>
  {rows}
  <text x="{x1}" y="52" text-anchor="end" font-size="12.5" fill="{MUTED}">contributions in the last year</text>
  <g clip-path="url(#reveal)">
    <path d="{path} L {x1} {y1} L {x0} {y1} Z" fill="url(#area)"/>
    <path d="{path}" fill="none" stroke="{PINK}" stroke-width="2.5" stroke-linecap="round"/>
    {dots}
  </g>
  <line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{MUTED}"/>
  <line x1="{x1}" y1="{y0 - 6}" x2="{x1}" y2="{y1}" stroke="{MUTED}"/>
  <g font-size="11" fill="{MUTED}">{ticks}{xlabels}</g>"""
    defs = f"""<linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="{ROSE}" stop-opacity=".75"/><stop offset="100%" stop-color="{ROSE}" stop-opacity=".05"/></linearGradient>
  <clipPath id="reveal"><rect x="{x0 - 6}" y="{y0 - 20}" width="0" height="{y1 - y0 + 30}"><animate attributeName="width" from="0" to="{x1 - x0 + 12}" dur="1.8s" begin=".3s" fill="freeze"/></rect></clipPath>"""
    return frame(h, body, extra_defs=defs)


def stack(data):
    colors = [ROSE, MAUVE, CARAMEL, "#FFC2D1", PINK]
    x_chips, x_max, chip_h, y = 196, W - 36, 30, 106
    blocks, n = [], 0
    for (category, items), color in zip(STACK, colors):
        top = y
        x = x_chips
        chips = []
        for label, slug in items:
            w = int(len(label) * 7.3 + 42)
            if x + w > x_max:
                x, y = x_chips, y + chip_h + 10
            if slug:
                svg = get(f"{ICONS}/{slug}.svg", raw=True).decode("utf-8")
                d = re.search(r'<path d="([^"]+)"', svg).group(1)
                icon = (f'<path transform="translate({x + 11} {y + 8}) scale(.583)" d="{d}" fill="{color}"/>')
            else:
                icon = (f'<circle cx="{x + 18}" cy="{y + 15}" r="7.5" fill="{color}"/>'
                        f'<text x="{x + 18}" y="{y + 18.5}" text-anchor="middle" font-size="9" font-weight="800" '
                        f'fill="{BG1}">{escape(label[0])}</text>')
            chips.append(
                f'<g class="fade" style="animation-delay:{.25 + n * .035:.2f}s">'
                f'<rect x="{x}" y="{y}" width="{w}" height="{chip_h}" rx="15" fill="{PAPER}" stroke="{color}" stroke-opacity=".55"/>'
                f'{icon}<text x="{x + 33}" y="{y + 20}" font-size="12.5" font-weight="600" fill="{COCOA}">{escape(label)}</text></g>')
            x += w + 8
            n += 1
        blocks.append(
            f'<circle cx="46" cy="{top + 15}" r="4" fill="{color}"/>'
            f'<text x="58" y="{top + 19.5}" font-family="{MONO}" font-size="11.5" font-weight="700" fill="{color}" '
            f'letter-spacing="2">{category.upper()}</text>{"".join(chips)}')
        y += chip_h + 14
        blocks.append(f'<line x1="40" y1="{y - 7}" x2="{W - 40}" y2="{y - 7}" stroke="{LINE}" stroke-dasharray="2 5"/>')
    blocks.pop()  # no divider after the last category
    h = y + 26
    body = f"""
  {heading(40, 58, "Tech Stack", "Languages, frameworks and tools I ship with")}
  <text x="{W - 40}" y="54" text-anchor="end" font-family="{MONO}" font-size="13" font-weight="700" fill="{ROSE}">&gt; stack --list <tspan class="blink">_</tspan></text>
  {"".join(blocks)}"""
    return frame(h, body)


if __name__ == "__main__":
    data = collect()
    os.makedirs(OUT, exist_ok=True)
    for name, render in [("hero", hero), ("scan", scan), ("projects", projects),
                         ("languages", languages), ("contributions", contributions), ("summary", summary), ("stack", stack)]:
        path = os.path.join(OUT, f"card-{name}.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(render(data))
        print(f"wrote {path} ({os.path.getsize(path) // 1024} KB)")
    print(f"{data['repos']} repos · {data['total']} contributions · "
          f"top languages {[n for n, _ in data['languages'][:4]]}")
