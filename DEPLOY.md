# Deploying MediScript on Render (free tier)

MediScript runs on Render's **free** web-service tier with no database to set up.

## 1. Get an OCR.space key (free)
Sign up at https://ocr.space/ocrapi and copy your API key. This is the only
secret you must provide.

## 2. Push to GitHub
```bash
git init && git add . && git commit -m "MediScript"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```
(Or run `scripts/setup_github.sh` / `.ps1`.)

## 3. Deploy on Render
1. Go to https://dashboard.render.com → **New +** → **Blueprint**.
2. Select your repo. Render reads `render.yaml` and configures everything.
3. When asked, set **OCRSPACE_KEYS** to your key (comma-separate several keys to
   rotate through their quotas). `SECRET_KEY` is generated for you.
4. Click **Apply**. First build takes a few minutes.

Your app will be live at `https://<name>.onrender.com`.

## What you get for free
- Full app: prescription reading, search, savings finder, analytics, news.
- SQLite storage — **no database to create**.

## Free-tier caveats (and fixes)
- **Cold starts:** free services sleep after ~15 min idle; the next request
  wakes it and also loads the medicine dataset, so the *first* hit can take
  10–30 s. Subsequent requests are fast.
- **Ephemeral data:** the free disk resets on sleep/redeploy, so registered
  users/inventory don't persist. For a portfolio demo that's usually fine. To
  persist data, add a database:
  1. Render → **New +** → **Postgres** (has a free trial tier).
  2. Copy its **Internal Connection String**.
  3. On the web service → **Environment** → add `DATABASE_URL` = that string.
  4. Redeploy. The app auto-creates its tables; for schema changes over time you
     can run `alembic upgrade head` (migrations are included).

## Enabling the optional medical NER model
Not needed for free tier (adds ~0.5–1 GB RAM). See the README section
"Optional: enable a real medical NER model".

## Running locally
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
echo "OCRSPACE_KEYS=your_key_here" > .env
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000
