# 18 · Device validation checklist

Everything below has to be done on a phone, by a person. It is here because the parts of
this product that are wrong are not the parts that fail a test — they are the parts where
the code is correct and the experience is not: a rest timer that stops when the screen
locks, a sync that resolves on the wrong side, a photo that comes back rotated.

**How to use this.** Work down a section in order; the steps within one depend on each
other. Record the result as one of:

- **pass** — observed, in the state described
- **fail** — with what you saw
- **blocked** — with what is missing (usually a credential from
  [17 · Release runbook](17-release-runbook.md))

A step you did not do is not a pass. An empty result column is more useful than an
optimistic one.

**Before starting.** Both dev servers running, the phone on the same Wi-Fi, and
`EXPO_PUBLIC_API_URL` set to the machine's LAN address rather than `localhost` — on a
phone `localhost` is the phone.

---

## A · Account and sign-in (14)

| # | Step | Expected |
|---|---|---|
| A1 | Register with a new email | Verification screen, not a signed-in state |
| A2 | Open the verification link | Signed in, landed on the dashboard |
| A3 | Register again with the same email | Identical response to A1 — the API must not confirm the address exists |
| A4 | Sign out, sign in with the password | Signed in |
| A5 | Sign in with the wrong password five times | Locked out, with a message that says so |
| A6 | Force-quit the app, reopen | Still signed in — the refresh token survived |
| A7 | Leave the app closed past the access-token TTL, reopen | Silent refresh; no sign-in screen |
| A8 | Airplane mode, open the app | Cached screens render; no crash and no infinite spinner |
| A9 | Request a password reset, open the link | Reset completes |
| A10 | Reuse the same reset link | Refused |
| A11 | Google sign-in (needs runbook §2) | Signed in; one `auth_identities` row |
| A12 | Google sign-in a second time | Same account, not a duplicate |
| A13 | Apple sign-in (needs runbook §3) | Signed in |
| A14 | Delete the app, reinstall, Apple sign-in again | Same account — Apple sends the name only on the first authorisation ever |

## B · Logging a workout (22)

| # | Step | Expected |
|---|---|---|
| B1 | Start an empty workout | Timer runs from 00:00 |
| B2 | Add an exercise from search | Appears with one empty set |
| B3 | Log a set with weight and reps | Marked complete; volume updates |
| B4 | Log a set that beats a previous best | PR badge appears |
| B5 | Log a set that exactly equals the previous best | **No** badge — equalling is not beating |
| B6 | Log 16 reps at a heavy weight | No 1RM claim; the estimate is capped at 15 reps |
| B7 | Rest timer starts on set completion | Counts down |
| B8 | Lock the screen mid-rest, unlock after it should have ended | Timer shows the correct elapsed time, not a frozen one |
| B9 | Background the app mid-rest, return | Same |
| B10 | Reorder two exercises | Order persists after leaving and returning |
| B11 | Remove an exercise with logged sets | Confirmation names how many sets are lost |
| B12 | Pause the workout, wait a minute, resume | Paused time excluded from duration |
| B13 | Finish the workout | Summary shows volume, sets, duration, PRs |
| B14 | Check the finished session in history | Same numbers as the summary |
| B15 | Start a workout from a routine | Exercises pre-filled, once each |
| B16 | Previous performance shows under each exercise | Last session's numbers |
| B17 | Airplane mode, log five sets, finish | Saved locally; the UI does not claim a sync |
| B18 | Restore connectivity | Sync completes; the session appears server-side |
| B19 | Repeat B17–B18 twice on the same session | One session on the server, not three |
| B20 | Airplane mode, start a routine workout, restore | Exercises appear **once** — the double-seeding case |
| B21 | Force-quit mid-workout, reopen | Resume prompt; sets intact |
| B22 | Discard a workout | Confirmation names the set count; nothing on the server afterwards |

## C · Nutrition (12)

| # | Step | Expected |
|---|---|---|
| C1 | Search a common food | Results within a second |
| C2 | Search with a Greek accent (`γάλα` vs `γαλα`) | Same results either way |
| C3 | Log a food, adjust the portion | Macros scale |
| C4 | Log to each of the four meals | Each appears under the right heading |
| C5 | Day totals against the target | Remaining calories correct |
| C6 | Copy yesterday forward | Entries duplicated, not moved |
| C7 | Edit a logged entry | Totals update |
| C8 | Delete an entry | Totals update |
| C9 | Log water | Total updates |
| C10 | Change the day, return | Correct day's entries |
| C11 | Log food offline | Queued; syncs on reconnect |
| C12 | Cross local midnight while logging | Entry lands on the day the user is in, not UTC's |

## D · Progress photos (14)

Needs runbook §5, or the local MinIO running.

| # | Step | Expected |
|---|---|---|
| D1 | Add a front photo from the library | Appears in the grid |
| D2 | **Take a photo with location services on**, then add it | Uploads |
| D3 | Pull that object from the bucket, run `exiftool` | **No GPS block, no device serial** |
| D4 | Same for the `_thumb.jpg` | Also clean — it is a separate object |
| D5 | Add a portrait photo taken sideways | Comes back upright, not rotated |
| D6 | Add a second front photo on a later date | Comparison appears |
| D7 | Comparison shows the span and weight delta | Correct against the logged weights |
| D8 | Compare a front with a back photo | Warned that the poses differ |
| D9 | Kill the app mid-upload, reopen | No broken tile; a pending or absent photo, never a half one |
| D10 | Add a photo, then delete it | Gone from the grid |
| D11 | Check the bucket after D10 | The object **and** its thumbnail are gone |
| D12 | Keep a signed URL, wait past its expiry, open it | Refused |
| D13 | Sign in as a second account | Sees none of the first account's photos |
| D14 | Add a 20 MB photo | Refused with a clear message, not a hang |

## E · Notifications (10)

Needs runbook §1.

| # | Step | Expected |
|---|---|---|
| E1 | First launch after signing in | Permission prompt appears |
| E2 | Grant it, then check `user_devices` | An active `ExponentPushToken` row |
| E3 | Beat a PR **with the app closed** | Banner arrives |
| E4 | Tap the banner | Opens the right screen, not the dashboard |
| E5 | Turn off one category, trigger it | Nothing arrives |
| E6 | Other categories still arrive | Yes |
| E7 | Set quiet hours over now, trigger | Deferred, not dropped |
| E8 | Wait until quiet hours end | It arrives |
| E9 | Revoke notification permission in iOS Settings, trigger | Token marked inactive; no retry loop |
| E10 | Re-grant permission | A new active token; the old one stays inactive |

## F · The rest of the app (12)

| # | Step | Expected |
|---|---|---|
| F1 | Calendar month view | Trained days lit; today ringed |
| F2 | Page back through six months | No skipped month; grid height does not change |
| F3 | Weight chart with a week of data | Dots and trend line both drawn |
| F4 | Log a 2 kg jump | Trend lags — it must not spike |
| F5 | Measurements: fill two fields, save | Only those two change |
| F6 | Goals: set a fat-loss goal with a positive rate | Targets go down, not up |
| F7 | Achievements list | Earned ones distinguishable from locked |
| F8 | Coach: ask a question | Streams a reply |
| F9 | Coach: airplane mode mid-reply | Clear error, no stuck spinner |
| F10 | Exercise detail | Image loads; no demo shown for an exercise without one |
| F11 | Switch to Greek | Every visible string translates; no English left |
| F12 | Rotate to landscape on the main screens | No clipped text, no overlap |

## G · Presentation and accessibility (10)

| # | Step | Expected |
|---|---|---|
| G1 | Dark mode | Every screen; no white flash on navigation |
| G2 | Light mode | Same |
| G3 | Largest system text size | Nothing clipped or overlapping |
| G4 | VoiceOver through a workout | Every control is reachable and named |
| G5 | Header on the register screen | Does not overlap the status bar |
| G6 | Tap targets on the set rows | Nothing under 44 pt |
| G7 | A small phone (SE-class) | No horizontal scrolling |
| G8 | Keyboard over the weight input | Field stays visible |
| G9 | Pull to refresh on each tab | Refreshes; the spinner ends |
| G10 | Battery over a 45-minute logged workout | No unreasonable drain |

---

**Total: 94 checks.** They are ordered by how much they would cost to get wrong: an
account you cannot recover, a workout that is lost, a photo that publishes somebody's
address.
