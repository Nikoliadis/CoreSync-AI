# Device validation — the workout journey

The one thing automated tests cannot cover. Everything below is verified at the unit
level and against the real backend; none of it has been tapped on hardware.

Takes about 15 minutes. You need a phone and the **Expo Go** app from the App Store or
Play Store.

---

## Setup

The phone and this machine must be on the same Wi-Fi.

```bash
# 1. Infrastructure
docker compose up -d postgres redis

# 2. API — bound to 0.0.0.0, not localhost, or the phone cannot reach it
cd backend
.venv/Scripts/python.exe -m uvicorn coresync.presentation.main:app --host 0.0.0.0 --port 8000

# 3. Find this machine's LAN address
ipconfig        # look for IPv4 under your Wi-Fi adapter, e.g. 192.168.1.42
```

Put that address in `mobile/.env.local`:

```
EXPO_PUBLIC_API_URL=http://192.168.1.42:8000
```

> `localhost` will not work. On the phone, localhost is the phone.

```bash
cd mobile
npx expo start
```

Scan the QR code with Expo Go (Android) or the Camera app (iOS).

---

## The journey

Tick each. Note anything that surprises you, however small.

### Account

- [ ] App opens to the welcome screen
- [ ] **Register** — account is created
- [ ] Verification screen appears with your email in it
- [ ] Verify the account: the token is printed in the API console, or run
      `docker exec coresync-postgres-1 psql -U coresync -d coresync -c "UPDATE users SET email_verified_at = now(), status='active' WHERE email='<yours>'"`
- [ ] **Log in** — lands on Home
- [ ] Home shows your name and zeroed totals

### Starting a workout

- [ ] Tap the centre **+** tab
- [ ] Tap **Start workout**
- [ ] Active workout screen opens, named "Workout", 0 sets

### Exercise picker

- [ ] Tap **Add exercise**
- [ ] The list loads
- [ ] Type `bench` — results narrow as you type, no lag between keystrokes
- [ ] Tap a muscle-group chip — results filter
- [ ] Tap the same chip again — filter clears
- [ ] Scroll to the bottom — more results load
- [ ] Tap an exercise — returns to the workout with it added, under its real name

### Logging

- [ ] Tap **+ Sets** — a row appears
- [ ] Type a weight and reps
- [ ] Tap the tick — row highlights, phone vibrates, rest timer starts
- [ ] Header shows 1 set and the volume
- [ ] Tap **+ Sets** again — weight and reps are prefilled from the last set
- [ ] Complete a second set
- [ ] Tap **+30s** on the rest timer — countdown extends
- [ ] Tap **Done** on the timer — it disappears
- [ ] Long-press a tick — the set is deleted, remaining sets renumber

### Offline — the part that matters

- [ ] **Turn on airplane mode**
- [ ] Add another set and complete it — no error, no spinner, no delay
- [ ] Open the exercise picker — the offline banner appears and cached exercises are listed
- [ ] Pick one and add it
- [ ] Log a set against it

### Interruption

- [ ] **Force-quit the app** — swipe it away, do not just background it
- [ ] Reopen it
- [ ] Navigate to the active workout
- [ ] **Every set is still there**, exactly as left
- [ ] The exercise added while offline is still there

### Previous performance and records

These need a *second* workout to mean anything: the PREV column reads from completed
sessions only, so on a first-ever session it is correctly empty.

- [ ] Finish the workout above, then start a new one and add the same exercise
- [ ] The **PREV** column shows what you lifted last time, per set number
- [ ] It reads `80 × 8`, not the values you are currently typing
- [ ] Tap **+ Sets** on a fresh exercise — weight and reps prefill from last session
- [ ] Log a set clearly heavier than last time — a **trophy** appears on that row
- [ ] Log a lighter set afterwards — the trophy stays on the best set, and appears once
- [ ] Log a set clearly lighter than your best — no trophy
- [ ] In airplane mode the PREV column is empty and nothing errors or spins

### Reordering and removing

- [ ] Add a second exercise
- [ ] Tap the **down arrow** on the first — the two swap
- [ ] The up arrow on the top exercise and the down arrow on the bottom are greyed out
- [ ] Tap the **bin** on an exercise with no completed sets — it goes, no dialog
- [ ] Tap the **bin** on one with completed sets — a confirmation names the set count
- [ ] Cancel it — the exercise stays
- [ ] Confirm it — the exercise goes
- [ ] Do all of the above **in airplane mode**, then reconnect: the server agrees

### The clock

- [ ] The header shows elapsed time, counting up
- [ ] Tap **pause** — the clock freezes and a "Paused" banner appears
- [ ] Background the app for a minute, reopen — still paused, still frozen
- [ ] Tap the banner — it resumes from where it stopped, not from where it would have been
- [ ] Background the app while *running* for a minute, reopen — the clock caught up
- [ ] Pause, wait, resume, pause again, resume — the time lost adds up across both

### Sync

- [ ] **Turn airplane mode off**
- [ ] Wait up to a minute, or tap **Finish**
- [ ] No errors

### The backend

```bash
docker exec coresync-postgres-1 psql -U coresync -d coresync -c "
SELECT s.name, s.status, count(ss.id) AS sets, s.total_volume_kg
FROM workout_sessions s
LEFT JOIN session_exercises se ON se.session_id = s.id
LEFT JOIN session_sets ss ON ss.session_exercise_id = se.id
GROUP BY s.id ORDER BY s.started_at DESC LIMIT 3;"
```

- [ ] The session is there
- [ ] Set count matches what you logged
- [ ] Volume matches what the header showed

```bash
docker exec coresync-postgres-1 psql -U coresync -d coresync -c "
SELECT name, duration_seconds,
       EXTRACT(EPOCH FROM (completed_at - started_at))::int AS wall_clock
FROM workout_sessions ORDER BY started_at DESC LIMIT 3;"
```

- [ ] For the paused session, `duration_seconds` is **less than** `wall_clock`, by
      roughly the time you spent paused
- [ ] For a session you never paused, the two match

```bash
docker exec coresync-postgres-1 psql -U coresync -d coresync -c "
SELECT e.name FROM session_exercises se
JOIN exercises e ON e.id = se.exercise_id
ORDER BY se.created_at DESC LIMIT 5;"
```

- [ ] Real exercise names, matching what you picked

---

## What to report back

For anything that failed or felt wrong:

- which step
- what you expected and what happened
- whether it was reproducible
- the API console output at that moment, if any

Small things count. A tick that needs two taps, a keyboard covering the input, a list
that stutters — those are exactly what a device finds and a test never will.
