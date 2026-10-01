# Morning Check

A private dashboard for your training and recovery, rebuilt from your Garmin
data every morning and published on GitHub Pages. It has five parts:

| | What it does |
|---|---|
| **Morning readiness swapper** | Reads training readiness, overnight HRV against your baseline band, sleep and resting HR. On a red day it moves today's hard session in Google Calendar to the next good day and puts a light session in its place. |
| **Tournament auto-report** | Groups games by place and date (Viareggio → Burla) and reports per-game load, average and peak HR, how intensity faded across the days, total load, and how many days your HRV took to come back. A season table ranks what each event cost you. |
| **Progressive overload builder** | Reads your Google Keep note **gym logs**, applies double progression to every lift, and uploads the next session to Garmin as a strength workout with the weight and reps for each set, so the watch tells you what to hit. It also writes the lifts you actually did into the matching Garmin activity's description. |
| **Recovery correlations** | Plots HRV and sleep against alcohol, late training, travel, tournament days and big training days, then measures each one's effect on your next-morning numbers with a confidence range. |
| **Injury early-warning** | Scans for the patterns that come before strains: a load spike (acute:chronic ratio), no rest days, back-to-back hard days, monotony, and HRV stuck under baseline. Add your glute strain date and it shows what the week before it looked like and warns when today matches. |

Until you add your secrets the site shows **demo data** with a banner, so you
can see how it works first.

## How it works

```
GitHub Actions (hourly 06:20–12:20, plus afternoon and evening)
  ├─ Garmin Connect   activities, HRV, sleep, readiness, resting HR, lifestyle log
  ├─ Google Keep      "gym logs" and "recovery tags" notes
  ├─ Google Calendar  this week's sessions
  ├─ analyse          fitapp/*.py
  ├─ act              move the hard session · upload workouts · write activity notes
  └─ publish          encrypted data.enc.json → GitHub Pages → your phone
```

This repository is **public**, so nothing personal is ever committed. The data
file is encrypted with AES-256-GCM using a passphrase only you know. Your
browser decrypts it, and you type the passphrase once per device. The state
cache between runs is encrypted the same way. Action logs only show counts and
error types, never your numbers.

## Setup (about 20 minutes, once)

### 1. Turn on GitHub Pages
Repository **Settings → Pages → Build and deployment → Source: GitHub Actions**.
Your dashboard will be at `https://<your-username>.github.io/fitnessApp/`.

### 2. Choose a passphrase
**Settings → Secrets and variables → Actions → New repository secret**
- `DASHBOARD_PASSPHRASE`: a long passphrase (four or five random words). It
  is the only thing protecting your health data on a public URL.

### 3. Garmin
On your own computer (Garmin may ask for an MFA code, which a robot can't answer):

```bash
pip install garminconnect==0.3.2
python scripts/garmin_login.py
```

Save the printed line as the secret `GARMIN_TOKENS`. Each run refreshes the
tokens and keeps them in the encrypted cache. If they ever expire, run the
script again. You can also add `GARMIN_EMAIL` and `GARMIN_PASSWORD` as a
fallback, but Garmin sometimes blocks password logins from cloud servers.

### 4. Google Calendar (for the readiness swapper)
1. In [Google Cloud Console](https://console.cloud.google.com/) create a project, enable the **Google Calendar API**, then
   **IAM & Admin → Service accounts → Create**. Open it, **Keys → Add key → JSON**.
2. In Google Calendar → your calendar's **Settings and sharing → Share with specific people**, add the
   service account's e-mail (`…@….iam.gserviceaccount.com`) with **Make changes to events**.
3. Secrets: `GOOGLE_SERVICE_ACCOUNT_JSON` = the whole JSON key file, `GOOGLE_CALENDAR_ID` = your Gmail address
   (or the calendar ID shown under *Integrate calendar*).

Sessions count as **hard** when their title contains words like *intervals, tempo, threshold, track, hills,
heavy, gym, lower, squat*, and as **protected** (never moved) for *tournament, game, tryouts, Burla, EBUCC,
hat, race*. Edit both lists, and the light replacements, in `config.yml`. Set `readiness.mode: suggest` if
you'd rather see the swap on the dashboard than have it applied.

Moved sessions keep their time and get a note in the description. The app only moves sessions that haven't
started yet. It acts once per morning, and if the new day turns out red too, the session moves again.

### 5. Google Keep (gym log and recovery tags)
Keep has no official API for personal accounts, so this uses
[gkeepapi](https://github.com/kiwiz/gkeepapi). Follow the steps at the top of
`scripts/keep_token.py`, then save the secrets `GOOGLE_EMAIL` and
`GOOGLE_KEEP_MASTER_TOKEN`. The master token is powerful, so keep it only in
GitHub secrets.

### 6. Make it yours
Edit `config.yml`:
- `timezone`, and `athlete.home` if auto-detection picks the wrong place.
- `injury.history`: add your glute strain, e.g. `- {date: 2026-07-14, label: "Glute strain"}`.
- `tournaments.manual`: upcoming events (Team Denmark tryouts is already in; add Pesca Disco Hat and EBUCC
  dates). The swapper never moves a hard session onto these days or the day before.
- `tournaments.names_by_location`: `Viareggio: Burla` is already there.
- `overload.rules`: rep ranges and weight jumps per lift.

### 7. First run
**Actions → Refresh dashboard → Run workflow**, with *dry run* ticked the first
time so nothing changes in Garmin or your calendar. The first real run
backfills 45 days of daily metrics, and later runs fill in the rest of the
180-day history.

## Writing the gym log

One note titled **gym logs** (any note whose title contains that works, so
"Gym logs 2025" counts too). Start each session with a date. A name after the
date is the session's name, and the builder keeps separate targets for each
recurring session.

```
Mon 29/09 – Lower A
Squat 3x5 100kg
RDL (6-10) 3x8 70          ← "(6-10)" sets that lift's rep range
Hip thrust 100x8x3
Bulgarian split squat 3x10 @ 16

1 Oct
Upper A
Bench 80: 8,8,7
Pull-ups bw 10,9,8
DB row 24x12, 24x12, 24x10
```

Weight before or after the sets, `kg`/`lbs`, `3 sets of 5 at 100kg`, and a
name on its own line followed by one set per line all work. Timed holds (`3x60s`) are skipped. Lines the
parser can't read are listed on the Strength tab.

**Recovery tags** (optional): a second note titled **recovery tags** with lines
like `27/09 alcohol` or `28/09 travel, late dinner`. If you log alcohol in
Garmin Connect's lifestyle logging, it's picked up automatically. Late training,
travel and tournament days are detected from your activities.

## Run it locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
python -m fitapp --demo && python -m http.server -d site 8000      # demo at http://localhost:8000
# real data, no writes, readable JSON for debugging (never commit it):
DASHBOARD_PASSPHRASE=… GARMIN_TOKENS=… python -m fitapp --dry-run --plain /tmp/data.plain.json
```

## Good to know

- Garmin Connect and Google Keep are reached through unofficial libraries. If Garmin or Google change
  something, a run may fail until the library is updated. The dashboard keeps showing the last good data
  and marks it **Stale**.
- GitHub pauses scheduled workflows in public repositories after 60 days without any commits. If the
  dashboard stops updating, open **Actions → Refresh dashboard → Enable workflow**.
- The readiness call needs last night's data, so it happens on the first run after your watch syncs. To
  force a refresh, run the workflow from the Actions tab (the GitHub mobile app can do this too).
- Garmin's exercise library has its own names. Common lifts are mapped. Others upload with the name in the
  step note; map them under `overload.garmin_exercise_overrides`.
