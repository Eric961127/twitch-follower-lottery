import os
import secrets
import random
from urllib.parse import urlencode

import requests
from flask import Flask, redirect, request, session, render_template, jsonify, url_for
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)

# Secure cookies in production (Render uses HTTPS).
if os.getenv("RENDER"):
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_REDIRECT_URI = os.getenv("TWITCH_REDIRECT_URI", "http://localhost:5000/callback")
TWITCH_SCOPE = "moderator:read:followers"

# Simple in-memory follower cache keyed by a random browser-session ID.
# Good for a small free deployment; restarting the service clears the cache.
follower_cache = {}


def require_config():
    missing = []
    if not TWITCH_CLIENT_ID:
        missing.append("TWITCH_CLIENT_ID")
    if not TWITCH_CLIENT_SECRET:
        missing.append("TWITCH_CLIENT_SECRET")
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))


def twitch_headers():
    token = session.get("access_token")
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Client-Id": TWITCH_CLIENT_ID,
    }


def cache_key():
    if "cache_key" not in session:
        session["cache_key"] = secrets.token_urlsafe(24)
    return session["cache_key"]


@app.route("/")
def index():
    return render_template("index.html", user=session.get("user"))


@app.route("/login")
def login():
    require_config()
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state

    query = urlencode({
        "client_id": TWITCH_CLIENT_ID,
        "redirect_uri": TWITCH_REDIRECT_URI,
        "response_type": "code",
        "scope": TWITCH_SCOPE,
        "state": state,
        "force_verify": "true",
    })
    return redirect("https://id.twitch.tv/oauth2/authorize?" + query)


@app.route("/callback")
def callback():
    require_config()

    if request.args.get("error"):
        return f"Twitch 授權失敗：{request.args.get('error_description', request.args.get('error'))}", 400

    code = request.args.get("code")
    state = request.args.get("state")
    expected_state = session.pop("oauth_state", None)

    if not code:
        return "沒有收到 Twitch authorization code", 400
    if not state or not expected_state or not secrets.compare_digest(state, expected_state):
        return "OAuth state 驗證失敗，請重新登入。", 400

    token_response = requests.post(
        "https://id.twitch.tv/oauth2/token",
        data={
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": TWITCH_REDIRECT_URI,
        },
        timeout=20,
    )

    if token_response.status_code != 200:
        return "無法取得 Twitch Access Token：" + token_response.text, 400

    token_data = token_response.json()
    access_token = token_data["access_token"]

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": TWITCH_CLIENT_ID,
    }

    user_response = requests.get(
        "https://api.twitch.tv/helix/users",
        headers=headers,
        timeout=20,
    )
    if user_response.status_code != 200:
        return "無法取得 Twitch 使用者資料", 400

    users = user_response.json().get("data", [])
    if not users:
        return "找不到 Twitch 帳號資料", 400

    user = users[0]
    session["access_token"] = access_token
    session["refresh_token"] = token_data.get("refresh_token")
    session["user"] = {
        "id": user["id"],
        "login": user["login"],
        "display_name": user["display_name"],
        "profile_image_url": user["profile_image_url"],
    }

    follower_cache.pop(cache_key(), None)
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    key = session.get("cache_key")
    if key:
        follower_cache.pop(key, None)
    session.clear()
    return redirect(url_for("index"))


@app.route("/api/followers")
def followers():
    user = session.get("user")
    headers = twitch_headers()

    if not user or not headers:
        return jsonify(ok=False, error="尚未登入 Twitch"), 401

    followers_list = []
    cursor = None

    try:
        while True:
            params = {
                "broadcaster_id": user["id"],
                "moderator_id": user["id"],
                "first": 100,
            }
            if cursor:
                params["after"] = cursor

            response = requests.get(
                "https://api.twitch.tv/helix/channels/followers",
                headers=headers,
                params=params,
                timeout=20,
            )

            if response.status_code == 401:
                return jsonify(ok=False, error="Twitch 授權已失效，請登出後重新登入"), 401
            if response.status_code == 403:
                return jsonify(ok=False, error="Twitch 未授予讀取追蹤者的權限，請重新登入授權"), 403

            response.raise_for_status()
            data = response.json()

            followers_list.extend({
                "id": item["user_id"],
                "login": item["user_login"],
                "name": item["user_name"],
                "followed_at": item["followed_at"],
            } for item in data.get("data", []))

            cursor = data.get("pagination", {}).get("cursor")
            if not cursor:
                break

        follower_cache[cache_key()] = followers_list
        return jsonify(ok=True, count=len(followers_list), followers=followers_list)

    except requests.RequestException as exc:
        return jsonify(ok=False, error=f"Twitch API 連線失敗：{exc}"), 502


@app.route("/api/draw", methods=["POST"])
def draw():
    if not session.get("user"):
        return jsonify(ok=False, error="尚未登入 Twitch"), 401

    followers_list = follower_cache.get(cache_key(), [])
    if not followers_list:
        return jsonify(ok=False, error="請先更新追蹤者名單"), 400

    winner = random.SystemRandom().choice(followers_list)
    return jsonify(ok=True, winner=winner)


@app.route("/health")
def health():
    return jsonify(ok=True)


if __name__ == "__main__":
    require_config()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
