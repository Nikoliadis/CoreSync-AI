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

### Routines

- [ ] Workouts tab lists your routines, grouped by folder, ungrouped ones last
- [ ] Tap **+** beside ROUTINES — the editor opens
- [ ] Add two exercises through the picker, set reps and set counts, save
- [ ] The routine appears in the list with the right exercise and set counts
- [ ] Open it — the prescription reads `3 × 8–12` per exercise
- [ ] Tap **Start** — the workout opens with every exercise already laid out
- [ ] **Each exercise appears exactly once** (not twice)
- [ ] Set rows are pre-filled with the prescribed reps and weight, and are *not* ticked
- [ ] Do the same **in airplane mode**, reconnect, and check the server agrees:

```bash
docker exec coresync-postgres-1 psql -U coresync -d coresync -c "
SELECT s.name, count(se.id) AS exercises
FROM workout_sessions s
LEFT JOIN session_exercises se ON se.session_id = s.id
GROUP BY s.id ORDER BY s.started_at DESC LIMIT 3;"
```

- [ ] Exercise count matches what you saw on screen — **not double**
- [ ] Templates screen lists starter routines; adopting one opens *your* copy
- [ ] Editing the adopted copy does not change the template
- [ ] Duplicate and delete both work

### Workout history

- [ ] Workouts tab shows finished sessions below the routines
- [ ] Each row reads date · duration · sets · volume
- [ ] A session with a PR shows a trophy
- [ ] Scroll to the bottom — older sessions load, none repeat and none are skipped
- [ ] Tap a session — its detail shows only the sets you actually completed

### Exercise images

- [ ] Picker rows show a small photograph, or a dumbbell placeholder
- [ ] Rows do **not** shift or jump as images load
- [ ] Tap a row's picture (not the row) — the exercise detail opens
- [ ] The detail shows a 4:3 photograph you can swipe, with paging dots
- [ ] Muscles and equipment are listed
- [ ] Active workout: each exercise card has a small thumbnail; tapping it opens the detail
- [ ] Open the same exercise twice — the second time the image appears instantly (disk cache)
- [ ] In airplane mode, an exercise you have not opened shows the placeholder and does not error

### Progress

- [ ] Home: tap the **Weight** tile — Progress opens
- [ ] Enter today's weight and save — the chart and headline update
- [ ] The chart shows scattered dots *and* a smooth trend line, on the same scale
- [ ] Switch 30d / 90d / 1y — the chart redraws
- [ ] With only one weigh-in, the chart still renders (no blank box, no crash)
- [ ] The change reads with a sign, e.g. `−1.2 kg`
- [ ] With no weigh-ins at all it reads `—`, **not** `0.0 kg`
- [ ] Tap **+** beside MEASUREMENTS, fill in *only* waist, save
- [ ] The other nine sites keep their previous values, they are not wiped
- [ ] Volume by muscle group shows bars, longest first

### Goals and targets

- [ ] Profile tab → **Goal and daily targets**
- [ ] Pick "Lose fat", enter a target weight and 0.5 kg/week, save
- [ ] Daily targets appear and are plausible for your height and weight
- [ ] Set an aggressive rate (e.g. 2 kg/week) — a warning appears *before* saving
- [ ] Save it — if the deficit hits the safety floor, an alert says the calories were raised
- [ ] Check the sign made it through:

```bash
docker exec coresync-postgres-1 psql -U coresync -d coresync -c "
SELECT goal_type, target_weight_kg, weekly_rate_kg FROM goals
WHERE ended_on IS NULL ORDER BY started_on DESC LIMIT 2;"
```

- [ ] For a fat-loss goal `weekly_rate_kg` is **negative**, not positive

### Achievements

- [ ] Profile tab → **Achievements**
- [ ] Earned badges show first, most recent first
- [ ] Unearned badges show a progress bar and "7 of 10", **not** a bare padlock
- [ ] Within a category, the closest unearned badge is above the furthest

### AI coach

- [ ] Home → **Ask the coach**
- [ ] Send a message — your own words appear immediately
- [ ] The reply **streams in word by word**, it does not appear all at once after a pause
- [ ] Ask something long enough to produce a multi-paragraph reply
- [ ] **No sentence is missing from the middle** of it (this is the frame-splitting bug)
- [ ] Send, then immediately tap Done — no crash, and the request stops
- [ ] With the API stopped, sending shows "No connection", not a spinner forever
- [ ] Coach insights appear on Home; Helpful / Dismiss both make them go away

### Notifications

- [ ] Home shows a bell; with unread items it carries a badge
- [ ] Tap it — the list shows unread items highlighted
- [ ] Tap one — it stops looking unread immediately and follows its link
- [ ] **Mark all as read** clears the badge
- [ ] Open notification settings, turn off one category, leave the app and return
- [ ] That category is **still off** (the toggle persisted)
- [ ] Turn on quiet hours 22:00–07:00, then set it back to Off — it clears

### Settings, profile, account

- [ ] Profile tab → your name → the editor opens
- [ ] Change your height and save
- [ ] Goals screen now shows targets recalculated from the new height
- [ ] Settings → switch to Imperial — height reads as feet and inches
- [ ] **It never reads 5'12"** (should be 6'0")
- [ ] Privacy policy link opens
- [ ] "Improve the coach" is **off** by default
- [ ] Tap **Delete account** — the dialog states the 30-day grace period explicitly
- [ ] Cancel it — nothing happens
- [ ] (On a throwaway account only) Confirm it — you are signed out everywhere

```bash
docker exec coresync-postgres-1 psql -U coresync -d coresync -c "
SELECT email, deleted_at FROM users ORDER BY created_at DESC LIMIT 3;"
```

- [ ] The deleted account has a `deleted_at`, and the row still exists (grace period)

### Push notifications — device only

**Prerequisites.** Push cannot work until both are true:

1. `eas init` has been run so `expo.extra.eas.projectId` exists (or `EXPO_PUBLIC_PROJECT_ID`
   is set). Without it no token can be minted and nothing below will pass.
2. The API worker runs with `PUSH_ENABLED=true`.

- [ ] Profile → Settings → Notifications: a **Turn on notifications** card is shown
- [ ] It explains *what* the notifications are before asking — the OS prompt has **not**
      already appeared on launch
- [ ] Tap **Allow notifications** — the system prompt appears
- [ ] Accept it — the card disappears and the Push toggle becomes meaningful

```bash
docker exec coresync-postgres-1 psql -U coresync -d coresync -c "
SELECT platform, device_name, is_active, (push_token IS NOT NULL) AS has_token
FROM user_devices ORDER BY created_at DESC LIMIT 3;"
```

- [ ] Your device is listed, `is_active` true, `has_token` true
- [ ] The token itself never appears anywhere in the app's own UI

**Delivery.** Trigger a PR celebration by logging a set that beats a record, then:

- [ ] A notification arrives on the device (may take up to a minute — the outbox runs on
      a timer)
- [ ] With the app **closed**, tap it — the app opens **on the workout**, not on Home
- [ ] With the app **open**, one arrives as a banner rather than silently
- [ ] With the app open, the Home bell badge increments without a tap

**Preferences actually control delivery.**

- [ ] Turn off "Personal records" in notification settings
- [ ] Beat another record — **no push arrives**
- [ ] The in-app list still shows it (in-app and push are separate channels)
- [ ] Turn it back on — the next one arrives

**Token lifecycle.**

- [ ] Force-quit and reopen — check the database still shows exactly **one** device row,
      not a new one per launch
- [ ] Sign out — the device row disappears
- [ ] Sign back in and re-allow — it reappears
- [ ] Sign in as a **different account** on the same phone; the first account's row must
      no longer have a token (notifications must not follow the phone to the wrong user)
- [ ] Delete the app, then send a notification — the row is marked `is_active = false`
      rather than retried forever

**Denial path.**

- [ ] On a fresh install, decline the OS prompt
- [ ] The card now offers **Open device settings**, not a dead "Allow" button
- [ ] Turning notifications on in iOS/Android settings and reopening the app registers
      the device

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
