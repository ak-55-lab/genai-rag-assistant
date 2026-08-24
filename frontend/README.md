# GenAI — chat front-end for the RAG agent

A password-gated chat window that proxies to an n8n RAG Chat Agent webhook.
Holds no OpenAI key and does no scoring itself — it logs someone in and
forwards their messages to n8n, which does retrieval, reranking, and
generation.

- Login: enter your name (used only to personalize the greeting) plus a
  shared password
- Chat: ChatGPT-style UI — centered input to start, moves to a bottom bar
  once a conversation is going, with a left sidebar listing chats for the
  current browser session (in-memory only, resets on reload). Each chat
  gets its own session ID, so separate chats have independent memory in
  n8n (5-turn window buffer).
- Branding: inline SVG robot logo — no external image/CDN dependencies.

## Configuration

Copy `.env.example` to `.env` and set:

- `APP_PASSWORD` — the shared password for the login page
- `N8N_CHAT_WEBHOOK_URL` — your n8n Chat Trigger webhook's public URL
- `FLASK_SECRET_KEY` — optional, auto-generated if unset

Neither of the first two ship with a working default in this repo —
you need your own n8n instance with the workflow in `../n8n/workflow.json`
imported and published.

## Run locally

```bash
cp .env.example .env
# edit .env
docker compose up --build
```

Open `http://localhost:8081`.

## Deploy

Any platform that runs a Dockerfile works (Railway, Fly.io, Render, etc.).
The Dockerfile binds to `$PORT` if set, falling back to 8080. Set the same
three environment variables in your platform's dashboard.

## Security notes

- The login "name" field is not a credential — it's freeform text used
  only to personalize the welcome message.
- Sessions are Flask's signed cookies — no database. Sidebar chat history
  is in-memory in the browser tab and is lost on reload; n8n's own
  conversation memory (5-turn window) is also in-memory and doesn't
  survive an n8n restart.
- There's no rate limiting on `/api/chat`. Fine for a small, trusted
  audience; add per-session throttling before wider distribution.
