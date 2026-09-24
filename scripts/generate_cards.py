#!/usr/bin/env python3
"""Generate the profile README cards (header, stats, languages, streak) as SVGs.

Reads data from the GitHub GraphQL API using GITHUB_TOKEN, so the README no
longer depends on third-party card services. Standard library only.

Usage:
  GITHUB_TOKEN=... python3 scripts/generate_cards.py <login> <out_dir>
  python3 scripts/generate_cards.py <login> <out_dir> --data sample.json
"""

import datetime as dt
import json
import os
import sys
import urllib.request
from html import escape

API = "https://api.github.com/graphql"

THEMES = {
    "light": {
        "bg": "#ffffff", "title": "#2f81f7", "text": "#1f2328",
        "muted": "#656d76", "icon": "#2f81f7", "ring": "#fb8c00",
        "track": "#eaeef2",
    },
    "dark": {
        "bg": "#0d1117", "title": "#58a6ff", "text": "#e6edf3",
        "muted": "#8b949e", "icon": "#58a6ff", "ring": "#ffa657",
        "track": "#21262d",
    },
}

FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Sans-Serif"
HIDDEN_LANGS = {"html", "javascript", "css", "freemarker", "plpgsql", "plsql"}

PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    login
    createdAt
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes {
        name
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

CALENDAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def graphql(token, query, variables):
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}",
                 "User-Agent": "profile-cards"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]["user"]


def fetch(login, token):
    """Return {profile, days: [(date, count)], commits_this_year}."""
    profile = graphql(token, PROFILE_QUERY, {"login": login})
    now = dt.datetime.now(dt.timezone.utc)
    start_year = int(profile["createdAt"][:4])
    days = {}
    commits_this_year = 0
    for year in range(start_year, now.year + 1):
        frm = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc)
        to = min(dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc), now)
        data = graphql(token, CALENDAR_QUERY, {
            "login": login, "from": frm.isoformat(), "to": to.isoformat()})
        coll = data["contributionsCollection"]
        if year == now.year:
            commits_this_year = (coll["totalCommitContributions"]
                                 + coll["restrictedContributionsCount"])
        for week in coll["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days[day["date"]] = day["contributionCount"]
    return {
        "profile": profile,
        "days": sorted(days.items()),
        "commits_this_year": commits_this_year,
        "today": now.date().isoformat(),
    }


# ---------------------------------------------------------------- computations

def streaks(days, today):
    """Return (total, current, longest) from sorted (date, count) pairs."""
    total = sum(c for _, c in days)
    longest = run = 0
    for _, count in days:
        run = run + 1 if count else 0
        longest = max(longest, run)
    # The current streak survives a zero-contribution today.
    current = 0
    for date, count in reversed(days):
        if date > today:
            continue
        if count:
            current += 1
        elif date != today:
            break
    return total, current, longest


def languages(repos, login, limit=8):
    sizes, colors = {}, {}
    for repo in repos:
        if repo.get("name", "").lower() == login.lower():
            continue  # Skip this profile repo's own tooling.
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name.lower() in HIDDEN_LANGS:
                continue
            sizes[name] = sizes.get(name, 0) + edge["size"]
            colors[name] = edge["node"]["color"] or "#8b949e"
    total = sum(sizes.values())
    top = sorted(sizes.items(), key=lambda kv: -kv[1])[:limit]
    return [(n, colors[n], s / total * 100) for n, s in top] if total else []


def human(n):
    for div, suffix in ((1_000_000, "m"), (1_000, "k")):
        if n >= div:
            return f"{n / div:.1f}".rstrip("0").rstrip(".") + suffix
    return str(n)


# ---------------------------------------------------------------- rendering

def svg(width, height, t, body, title):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
<title>{escape(title)}</title>
<style>
  text {{ font-family: {FONT}; }}
  .title {{ font-size: 18px; font-weight: 600; fill: {t['title']}; }}
  .label {{ font-size: 14px; fill: {t['text']}; }}
  .value {{ font-size: 14px; font-weight: 700; fill: {t['text']}; }}
  .muted {{ font-size: 12px; fill: {t['muted']}; }}
  .fade {{ opacity: 0; animation: fadein .6s ease-out forwards; }}
  @keyframes fadein {{ to {{ opacity: 1; }} }}
</style>
<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="6" fill="{t['bg']}"/>
{body}
</svg>
"""


# 16x16 Octicons paths.
ICONS = {
    "star": "M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z",
    "commit": "M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5Zm-1.43-.75a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0Z",
    "pr": "M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354ZM3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z",
    "issue": "M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Z",
    "people": "M2 5.5a3.5 3.5 0 1 1 5.898 2.549 5.508 5.508 0 0 1 3.034 4.084.75.75 0 1 1-1.482.235 4 4 0 0 0-7.9 0 .75.75 0 0 1-1.482-.236A5.507 5.507 0 0 1 3.102 8.05 3.493 3.493 0 0 1 2 5.5ZM11 4a3.001 3.001 0 0 1 2.22 5.018 5.01 5.01 0 0 1 2.56 3.012.749.749 0 0 1-.885.954.752.752 0 0 1-.549-.514 3.507 3.507 0 0 0-2.522-2.372.75.75 0 0 1-.574-.73v-.352a.75.75 0 0 1 .416-.672A1.5 1.5 0 0 0 11 5.5.75.75 0 0 1 11 4Zm-5.5-.5a2 2 0 1 0-.001 3.999A2 2 0 0 0 5.5 3.5Z",
}


def stats_card(data, t):
    p = data["profile"]
    stars = sum(r["stargazerCount"] for r in p["repositories"]["nodes"])
    year = data["today"][:4]
    rows = [
        ("commit", f"Commits ({year})", data["commits_this_year"]),
        ("pr", "Pull requests", p["pullRequests"]["totalCount"]),
        ("issue", "Issues", p["issues"]["totalCount"]),
        ("star", "Stars earned", stars),
        ("people", "Followers", p["followers"]["totalCount"]),
    ]
    body = [f'<text x="25" y="35" class="title">{escape(p["login"])}\'s GitHub Stats</text>']
    for i, (icon, label, value) in enumerate(rows):
        y = 70 + i * 25
        body.append(
            f'<g class="fade" style="animation-delay:{150 + i * 120}ms" transform="translate(25,{y})">'
            f'<path transform="translate(0,-12)" fill="{t["icon"]}" d="{ICONS[icon]}"/>'
            f'<text x="25" y="0" class="label">{label}:</text>'
            f'<text x="220" y="0" class="value">{human(value)}</text></g>')
    return svg(340, 195, t, "\n".join(body), "GitHub stats")


def langs_card(data, t):
    langs = languages(data["profile"]["repositories"]["nodes"], data["profile"]["login"])
    width = 340
    body = [f'<text x="25" y="35" class="title">Most Used Languages</text>']
    if not langs:
        body.append('<text x="25" y="100" class="muted">No public code yet — stay tuned.</text>')
        return svg(width, 195, t, "\n".join(body), "Top languages")
    bar_w, x = width - 50, 25.0
    body.append(f'<mask id="bar"><rect x="25" y="55" width="{bar_w}" height="8" rx="4" fill="#fff"/></mask>')
    body.append(f'<g mask="url(#bar)"><rect x="25" y="55" width="{bar_w}" height="8" fill="{t["track"]}"/>')
    for _, color, pct in langs:
        w = bar_w * pct / 100
        body.append(f'<rect x="{x:.2f}" y="55" width="{w:.2f}" height="8" fill="{color}"/>')
        x += w
    body.append("</g>")
    for i, (name, color, pct) in enumerate(langs):
        col, row = i % 2, i // 2
        cx, cy = 25 + col * 150, 90 + row * 25
        body.append(
            f'<g class="fade" style="animation-delay:{150 + i * 80}ms">'
            f'<circle cx="{cx + 5}" cy="{cy - 4}" r="5" fill="{color}"/>'
            f'<text x="{cx + 16}" y="{cy}" class="label" style="font-size:12px">{escape(name)} '
            f'<tspan class="muted">{pct:.1f}%</tspan></text></g>')
    return svg(width, 195, t, "\n".join(body), "Top languages")


def streak_card(data, t):
    total, current, longest = streaks(data["days"], data["today"])
    since = data["days"][0][0] if data["days"] else data["today"]
    cols = [
        (human(total), "Total Contributions", f"Since {since}"),
        (str(current), "Current Streak", "days in a row"),
        (str(longest), "Longest Streak", "days"),
    ]
    body = []
    for i, (value, label, sub) in enumerate(cols):
        cx = 115 + i * 225
        delay = f"animation-delay:{150 + i * 150}ms;"
        body.append(
            f'<text class="fade" x="{cx}" y="82" text-anchor="middle" '
            f'style="{delay}font-size:28px;font-weight:700;fill:{t["text"]}">{value}</text>')
        if i == 1:
            body.append(
                f'<circle cx="{cx}" cy="72" r="40" fill="none" stroke="{t["ring"]}" stroke-width="5"/>'
                f'<text class="fade" x="{cx}" y="140" text-anchor="middle" '
                f'style="{delay}font-size:14px;font-weight:700;fill:{t["ring"]}">{label}</text>')
        else:
            body.append(f'<text class="fade label" x="{cx}" y="140" text-anchor="middle" style="{delay}">{label}</text>')
        body.append(f'<text class="fade muted" x="{cx}" y="165" text-anchor="middle" style="{delay}">{sub}</text>')
    for x in (227, 452):
        body.append(f'<line x1="{x}" y1="30" x2="{x}" y2="165" stroke="{t["track"]}" stroke-width="1"/>')
    return svg(680, 195, t, "\n".join(body), "Contribution streak")


def header_card(t, lines=("Hi there 👋", "Wishing you a joyful life",
                         "and lots of flow when you code.")):
    n, per = len(lines), 3.0
    body = []
    for i, line in enumerate(lines):
        # Each line fades in, holds, then fades out; lines take turns.
        start, end = i / n * 100, (i + 1) / n * 100
        body.append(f"""<style>
  @keyframes l{i} {{
    0%, {start:.2f}% {{ opacity: 0; transform: translateY(8px); }}
    {start + 4:.2f}%, {end - 4:.2f}% {{ opacity: 1; transform: translateY(0); }}
    {end:.2f}%, 100% {{ opacity: 0; transform: translateY(-8px); }}
  }}
  .l{i} {{ opacity: 0; animation: l{i} {n * per}s ease-in-out infinite; }}
</style>
<text class="l{i}" x="300" y="44" text-anchor="middle" style="font-family:'Fira Code',Consolas,monospace;font-size:24px;font-weight:500;fill:{t['title']}">{escape(line)}</text>""")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="70" viewBox="0 0 600 70" role="img" aria-label="{escape(' '.join(lines))}">
<title>{escape(' '.join(lines))}</title>
{''.join(body)}
</svg>
"""


def main():
    login, out = sys.argv[1], sys.argv[2]
    if "--data" in sys.argv:
        with open(sys.argv[sys.argv.index("--data") + 1]) as f:
            data = json.load(f)
    else:
        token = os.environ.get("STATS_TOKEN") or os.environ["GITHUB_TOKEN"]
        data = fetch(login, token)
    os.makedirs(out, exist_ok=True)
    for name, t in THEMES.items():
        suffix = "" if name == "light" else "-dark"
        for card, render in (("header", lambda t: header_card(t)),
                             ("stats", lambda t: stats_card(data, t)),
                             ("langs", lambda t: langs_card(data, t)),
                             ("streak", lambda t: streak_card(data, t))):
            with open(os.path.join(out, f"{card}{suffix}.svg"), "w") as f:
                f.write(render(t))
    print(f"Wrote cards to {out}")


if __name__ == "__main__":
    main()
