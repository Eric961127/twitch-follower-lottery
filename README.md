# Twitch Follower Lottery

免費的 Twitch 追蹤者抽獎網站。

## Local setup

1. Copy `.env.example` to `.env`.
2. Fill in your Twitch Client ID and Client Secret.
3. In Twitch Developer Console, add `http://localhost:5000/callback` as an OAuth Redirect URL.
4. Install and run:

```bash
py -m pip install -r requirements.txt
py app.py
```

Open `http://localhost:5000`.

## Render deployment

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`

Set these environment variables in Render:
- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`
- `TWITCH_REDIRECT_URI` = `https://YOUR-SERVICE.onrender.com/callback`
- `FLASK_SECRET_KEY`

Then add that exact HTTPS callback URL to the Twitch Developer Console.

**Never commit `.env` or your Twitch Client Secret.**
