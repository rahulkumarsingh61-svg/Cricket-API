import os
import re
import json
import secrets
from functools import wraps
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, render_template_string, request
from flask_cors import CORS
from googlesearch import search

app = Flask(__name__)
CORS(app)  # Allow any external website (e.g., GitHub Pages) to call this API

KEYS_FILE = "api_keys.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
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


# 3. Live Cricket Scores Endpoint (Includes Runs, Wickets, Overs & Status)
@app.route("/live", methods=["GET"])
@require_api_key
def get_live():
    try:
        url = "https://www.cricbuzz.com/cricket-match/live-scores"
        resp = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(resp.text, "lxml")

        matches = []
        match_blocks = soup.find_all("div", class_=re.compile(r"cb-mtch-lst|cb-schdl"))
        for block in match_blocks:
            title_el = block.find(["h3", "a"], class_=re.compile(r"cb-lv-scr-mtch-hdr|text-hvr-underline"))
            score_el = block.find("div", class_=re.compile(r"cb-scr-wll-chvrn|cb-lv-scrs-col"))
            status_el = block.find("div", class_=re.compile(r"cb-text-live|cb-text-complete|cb-text-preview"))

            title = title_el.get_text(" ", strip=True) if title_el else ""
            score_text = score_el.get_text(" | ", strip=True) if score_el else ""
            status_text = status_el.get_text(" ", strip=True) if status_el else ""

            if title or score_text:
                matches.append({
                    "match": title,
                    "score": score_text,
                    "status": status_text,
                    "summary": " - ".join(p for p in [title, score_text, status_text] if p)
                })

        return jsonify(matches)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# 4. Upcoming Schedule Endpoint
@app.route("/schedule", methods=["GET"])
@require_api_key
def get_schedule():
    try:
        url = "https://www.cricbuzz.com/cricket-schedule/upcoming-series/international"
        resp = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(resp.text, "lxml")

        fixtures = []
        rows = soup.find_all("div", class_=re.compile(r"cb-ovr-flo|cb-col-100"))
        seen = set()
        for row in rows:
            link = row.find("a", href=re.compile(r"/live-cricket-scores/|/cricket-series/"))
            if not link:
                continue
            text = row.get_text(" ", strip=True)
            if text and 10 < len(text) < 220 and text not in seen:
                seen.add(text)
                fixtures.append(text)
            if len(fixtures) >= 25:
                break

        return jsonify(fixtures)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# 5. Player Profile & Career Stats Endpoint
@app.route("/players/<player_name>", methods=["GET"])
@require_api_key
def get_player(player_name):
    query = f"{player_name} cricbuzz profile"
    profile_link = None
    try:
        results = search(query, num_results=5)
        for link in results:
            if "cricbuzz.com/profiles/" in link:
                profile_link = link
                break
        if not profile_link:
            return jsonify({"error": f"No Cricbuzz profile found for {player_name}"}), 404
    except Exception as e:
        return jsonify({"error": f"Search failed: {str(e)}"}), 500

    try:
        resp = requests.get(profile_link, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(resp.text, "lxml")

        name_el = soup.find("h1")
        name = name_el.get_text(strip=True) if name_el else player_name

        tables = soup.find_all("table")
        stats_tables = []
        for tbl in tables[:2]:
            headers = [th.get_text(strip=True) for th in tbl.find_all("th")]
            rows_data = []
            for tr in tbl.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if cells:
                    rows_data.append(dict(zip(headers, cells)) if headers else cells)
            if rows_data:
                stats_tables.append(rows_data)

        return jsonify({
            "player": name,
            "profile_url": profile_link,
            "career_stats": stats_tables
        })
    except Exception as e:
        return jsonify({"error": f"Failed to parse player stats: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
