import os
import re
import json
import secrets
from functools import wraps
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, render_template_string, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow any external website (e.g., GitHub Pages) to call this API

KEYS_FILE = "api_keys.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, application/xml;q=0.9, */*;q=0.8"
}


def load_valid_keys():
    keys = set()
    env_keys = os.environ.get("API_KEYS", "")
    for k in env_keys.split(","):
        if k.strip():
            keys.add(k.strip())

    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    keys.update(data)
        except Exception:
            pass
    return keys


def save_new_key(new_key):
    keys = load_valid_keys()
    keys.add(new_key)
    try:
        with open(KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(keys)), f, indent=2)
    except Exception:
        pass


if not load_valid_keys():
    save_new_key("ck_live_demo_2026_nexus")


def require_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Allow requests coming directly from your own hosted web UI
        referer = request.headers.get("Referer", "")
        host = request.host_url
        if referer and host and referer.startswith(host):
            return fn(*args, **kwargs)

        provided_key = (
            request.headers.get("X-API-Key")
            or request.args.get("api_key")
            or ""
        ).strip()

        if not provided_key or provided_key not in load_valid_keys():
            return jsonify({
                "error": "Unauthorized. Missing or invalid API key.",
                "hint": "Pass your key in the 'X-API-Key' header or '?api_key=...' query param. Generate one at /keys"
            }), 401

        return fn(*args, **kwargs)
    return wrapper


# 1. Built-in Cricket Hub Web UI
@app.route("/")
def index():
    return render_template("index.html")


# 2. Developer Portal UI to Generate API Keys for Other Websites
@app.route("/keys")
def developer_portal():
    base_url = request.host_url.rstrip("/")
    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Cricket API — Developer Key Portal</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #0b1120; color: #f1f5f9; padding: 32px 16px; max-width: 740px; margin: auto; }
    .card { background: #1e293b; border: 1px solid #334155; border-radius: 14px; padding: 24px; margin-bottom: 20px; }
    h1 { color: #38bdf8; margin-top: 0; }
    button { background: #2563eb; color: #fff; border: none; padding: 11px 18px; border-radius: 10px; font-weight: 600; cursor: pointer; font-size: 0.95rem; }
    button:hover { background: #1d4ed8; }
    .key-box { margin-top: 16px; padding: 14px; background: #0f172a; border: 1px solid #38bdf8; border-radius: 10px; font-family: monospace; font-size: 1rem; color: #4ade80; word-break: break-all; display: none; }
    pre { background: #0f172a; padding: 14px; border-radius: 10px; overflow-x: auto; font-size: 0.85rem; color: #e2e8f0; border: 1px solid #334155; }
    a { color: #38bdf8; }
  </style>
</head>
<body>
  <div class="card">
    <h1>🏏 Cricket API Key Generator</h1>
    <p>Generate an API key to fetch live cricket scores (runs, wickets, overs, runs needed), schedules, and player stats in any external website.</p>
    <button onclick="createKey()">+ Generate New API Key</button>
    <div id="keyOutput" class="key-box"></div>
  </div>

  <div class="card">
    <h3>How to Use in Another Website (JavaScript)</h3>
    <pre id="codeSample">const res = await fetch("{{ base_url }}/live", {
  headers: { "X-API-Key": "YOUR_GENERATED_KEY" }
});
const data = await res.json();
console.log(data);</pre>
    <p>Available Endpoints: <code>/live</code>, <code>/schedule</code>, <code>/players/&lt;name&gt;</code></p>
    <p><a href="/">← Back to Cricket Hub Web UI</a></p>
  </div>

  <script>
    async function createKey() {
      const res = await fetch("/generate-key", { method: "POST" });
      const data = await res.json();
      const box = document.getElementById("keyOutput");
      box.style.display = "block";
      box.textContent = "Your API Key: " + data.api_key;
      document.getElementById("codeSample").textContent =
`const res = await fetch("{{ base_url }}/live", {
  headers: { "X-API-Key": "${data.api_key}" }
});
const data = await res.json();
console.log(data);`;
    }
  </script>
</body>
</html>
    """, base_url=base_url)


@app.route("/generate-key", methods=["POST"])
def generate_key():
    new_key = "ck_live_" + secrets.token_hex(16)
    save_new_key(new_key)
    base_url = request.host_url.rstrip("/")
    return jsonify({
        "api_key": new_key,
        "endpoints": {
            "live": f"{base_url}/live",
            "schedule": f"{base_url}/schedule",
            "player": f"{base_url}/players/Virat Kohli"
        }
    })


# 3. Live Cricket Scores Endpoint (ESPNcricinfo Official RSS + Scoreboard API)
@app.route("/live", methods=["GET"])
@require_api_key
def get_live():
    matches = []
    seen_titles = set()

    # Source A: ESPNcricinfo Official Live Scores XML/RSS Feed (reliable, includes wickets & overs)
    try:
        rss_resp = requests.get("https://static.cricinfo.com/rss/livescores.xml", headers=HEADERS, timeout=10)
        if rss_resp.ok:
            soup = BeautifulSoup(rss_resp.text, "html.parser")
            for item in soup.find_all("item"):
                title_tag = item.find("title")
                desc_tag = item.find("description")
                link_tag = item.find("guid") or item.find("link")

                raw_title = title_tag.get_text(" ", strip=True) if title_tag else ""
                desc = desc_tag.get_text(" ", strip=True) if desc_tag else ""
                link = link_tag.get_text(" ", strip=True) if link_tag else ""

                if raw_title and raw_title not in seen_titles:
                    seen_titles.add(raw_title)
                    parts = [p.strip() for p in raw_title.split(" v ")]
                    team1 = parts[0] if len(parts) > 0 else raw_title
                    team2 = parts[1] if len(parts) > 1 else ""
                    matches.append({
                        "title": raw_title,
                        "match": raw_title,
                        "teams": [team1, team2] if team2 else [team1],
                        "score": raw_title,
                        "status": desc or "Live / Recent",
                        "series": "ESPNcricinfo Live",
                        "url": link,
                        "summary": raw_title
                    })
    except Exception:
        pass

    # Source B: ESPN Public Cricket Scoreboard JSON API (adds series name, venue, overs & detailed status)
    try:
        sb_resp = requests.get("https://site.api.espn.com/apis/site/v2/sports/cricket/scorepanel", headers=HEADERS, timeout=10)
        if sb_resp.ok:
            sb_data = sb_resp.json()
            for group in sb_data.get("scores", []):
                league_name = group.get("leagues", [{}])[0].get("name", "Cricket")
                for ev in group.get("events", []):
                    name = ev.get("name", "")
                    short_name = ev.get("shortName", name)
                    status_detail = ev.get("status", {}).get("type", {}).get("detail", "")
                    comp = (ev.get("competitions") or [{}])[0]
                    competitors = comp.get("competitors", [])

                    team_scores = []
                    team_names = []
                    for c in competitors:
                        t_name = c.get("team", {}).get("displayName", "")
                        t_score = c.get("score", "")
                        team_names.append(t_name)
                        team_scores.append(f"{t_name} {t_score}".strip())

                    score_line = " vs ".join(team_scores) if team_scores else name
                    if score_line and score_line not in seen_titles:
                        seen_titles.add(score_line)
                        matches.append({
                            "title": name or short_name,
                            "match": name or short_name,
                            "teams": team_names,
                            "score": score_line,
                            "status": status_detail or "Live",
                            "series": league_name,
                            "summary": f"{score_line} — {status_detail} ({league_name})"
                        })
    except Exception:
        pass

    return jsonify(matches[:25])


# 4. Upcoming Schedule Endpoint (ESPN Public Cricket Scoreboard Calendar)
@app.route("/schedule", methods=["GET"])
@require_api_key
def get_schedule():
    fixtures = []
    seen = set()

    try:
        sb_resp = requests.get("https://site.api.espn.com/apis/site/v2/sports/cricket/scorepanel", headers=HEADERS, timeout=10)
        if sb_resp.ok:
            sb_data = sb_resp.json()
            for group in sb_data.get("scores", []):
                league_name = group.get("leagues", [{}])[0].get("name", "International / Domestic")
                for ev in group.get("events", []):
                    state = ev.get("status", {}).get("type", {}).get("state", "")
                    name = ev.get("name", "")
                    date_str = ev.get("date", "")
                    comp = (ev.get("competitions") or [{}])[0]
                    venue = comp.get("venue", {}).get("fullName", "")
                    status_detail = ev.get("status", {}).get("type", {}).get("detail", date_str)

                    if name and name not in seen:
                        # Prioritize upcoming ("pre") or include active schedule
                        if state == "pre" or len(fixtures) < 15:
                            seen.add(name)
                            fixtures.append({
                                "match": name,
                                "title": name,
                                "series": league_name,
                                "date": status_detail or date_str,
                                "venue": venue or "TBA",
                                "summary": f"{name} ({league_name}) — {status_detail}"
                            })
    except Exception:
        pass

    return jsonify(fixtures[:25])


# 5. Player Search & Player Comparison Endpoint (Unblocked ESPN Athlete Search + Profile Stats)
@app.route("/players/<player_name>", methods=["GET"])
@require_api_key
def get_player(player_name):
    clean_query = player_name.strip()
    if not clean_query:
        return jsonify({"error": "Player name is required"}), 400

    # Step 1: Search ESPN Public Athlete Directory (never blocked on Render)
    try:
        search_url = f"https://site.web.api.espn.com/apis/common/v3/search?query={quote(clean_query)}&limit=5&type=player"
        s_resp = requests.get(search_url, headers=HEADERS, timeout=10)
        items = s_resp.json().get("items", []) if s_resp.ok else []

        cricket_player = None
        for item in items:
            if item.get("sport", "").lower() == "cricket":
                cricket_player = item
                break
        if not cricket_player and items:
            cricket_player = items[0]

        if not cricket_player:
            return jsonify({"error": f"Player not found: {clean_query}"}), 404

        athlete_id = cricket_player.get("id")
        full_name = cricket_player.get("displayName") or clean_query.title()
        team_name = cricket_player.get("team", {}).get("displayName", "International")

        # Step 2: Fetch detailed athlete bio & stats from ESPN Cricket Core API
        bio_url = f"https://site.web.api.espn.com/apis/common/v3/sports/cricket/athletes/{athlete_id}"
        b_resp = requests.get(bio_url, headers=HEADERS, timeout=10)
        athlete_data = b_resp.json().get("athlete", {}) if b_resp.ok else {}

        position = athlete_data.get("position", {}).get("displayName", "Cricketer")
        bat_style = athlete_data.get("bats", {}).get("description", "N/A") if isinstance(athlete_data.get("bats"), dict) else str(athlete_data.get("bats", "N/A"))
        bowl_style = athlete_data.get("bowls", {}).get("description", "N/A") if isinstance(athlete_data.get("bowls"), dict) else str(athlete_data.get("bowls", "N/A"))
        age = athlete_data.get("displayAge", "N/A")
        dob = athlete_data.get("displayDOB", "N/A")
        image_url = athlete_data.get("headshot", {}).get("href", "")

        # Fetch career statistics summary
        stats_url = f"https://site.web.api.espn.com/apis/common/v3/sports/cricket/athletes/{athlete_id}/stats"
        st_resp = requests.get(stats_url, headers=HEADERS, timeout=10)
        stats_json = st_resp.json() if st_resp.ok else {}

        formatted_stats = {}
        for cat in stats_json.get("categories", []):
            cat_name = cat.get("displayName") or cat.get("name", "Stats")
            labels = cat.get("labels", [])
            rows = {}
            for st in cat.get("statistics", []):
                fmt_name = st.get("displayName") or st.get("name", "Format")
                vals = st.get("stats", [])
                rows[fmt_name] = dict(zip(labels, vals)) if labels else vals
            if rows:
                formatted_stats[cat_name] = rows

        return jsonify({
            "name": full_name,
            "player": full_name,
            "team": team_name,
            "country": team_name,
            "role": position,
            "age": age,
            "dob": dob,
            "batting_style": bat_style,
            "bowling_style": bowl_style,
            "image": image_url,
            "stats": formatted_stats,
            "career_stats": formatted_stats
        })
    except Exception as e:
        return jsonify({"error": f"Failed to fetch player data: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
