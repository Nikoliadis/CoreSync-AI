# 17 · Release runbook — the things code cannot do

Everything in this file is blocked on an account, a credential or a physical device.
None of it can be finished from the repository, which is exactly why it is written down:
work that has no owner and no artefact is the work that gets described as "nearly done"
for a month.

Each item says what it unblocks, what to do, and — the part that matters — **how you know
it worked**. A step whose success cannot be observed is not a step, it is a hope.

Companion to [16 · Phase 6 hardening status](16-phase-6-hardening-status.md).

---

## 1. Expo project id — unblocks push notifications

**State:** the whole push path is built and tested. The app cannot mint a device token
without a project id, so it logs a warning and registers nothing. That is deliberate: an
app that registers a fabricated token produces a notification system that reports success
and delivers nothing.

```bash
cd mobile
npx eas init          # creates the project, prints the id
```

Then set it in `mobile/.env`:

```
EXPO_PUBLIC_PROJECT_ID=<the id eas init printed>
```

and in `backend/.env`:

```
PUSH_ENABLED=true
```

**How you know it worked.** Not "the toggle is on" — that is a toggle. In order:

1. Open the app on a real device. Expo Go will ask for notification permission; if it
   does not, the project id is still missing.
2. `docker exec coresync-postgres-1 psql -U coresync -d coresync -c "select id, platform, is_active, left(push_token, 18) from user_devices;"` — there must be a row with
   `is_active = true` and a token starting `ExponentPushToken`.
3. Trigger something that notifies (beat a personal record) and confirm the banner
   arrives **with the app closed**. Foreground delivery proves nothing; the whole point
   is the device you are not looking at.
4. Kill the app, revoke notification permission in iOS Settings, and trigger again. The
   dispatcher must mark that token inactive on the `DeviceNotRegistered` response rather
   than retrying forever — check `is_active` flipped to false.

**Note:** `EXPO_ACCESS_TOKEN` is only needed if the Expo project enforces push security.
It is a *server* credential. It goes in `backend/.env` and never in a mobile build.

---

## 2. Google iOS client id — unblocks Google sign-in on the phone

**State:** built on both sides. The button is hidden until the id is set, which is
deliberate — a button that mints a token the server refuses is worse than no button.

The web client id already in use is **not** usable from a phone: Google restricts web
clients to http/https redirect URIs, and a native app redirects to a custom scheme.

1. console.cloud.google.com → the same project as the web client → APIs & Services →
   Credentials → Create OAuth client ID → **iOS** → bundle id `ai.coresync.app`.
2. `mobile/.env`: `EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID=<the new id>`
3. `backend/.env`: `GOOGLE_IOS_CLIENT_ID=<the same id>`

Both, or the server rejects the token — Google stamps the requesting client id into
`aud`, and the verifier accepts a fixed set.

**How you know it worked.** The button appears; signing in returns to the app signed in;
and `select provider, subject from auth_identities` shows a `google` row. Then sign out
and sign in again — the second one must reuse the same account row rather than creating a
second one.

---

## 3. Apple Developer account — unblocks Sign in with Apple

**State:** built and tested, including the multi-audience verification that native iOS
needs. It cannot be exercised end to end without a real Apple Developer account, and
saying otherwise would be a claim, not a verification.

The audience distinction is intentional and must not be "simplified":

| Flow | `aud` claim | Setting |
|---|---|---|
| Native iOS | the app's bundle id | `APPLE_BUNDLE_ID=ai.coresync.app` |
| Web | the Services ID | `APPLE_SERVICE_ID=<your Services ID>` |

A verifier that knows only one rejects every sign-in from the other.

**How you know it worked.** A real sign-in on a real device completes, and Apple's
private-relay address is stored as given. Then delete the app, reinstall, and sign in
again: Apple sends the name and email **only on the first authorisation ever**, so the
second run is the one that proves the account was persisted rather than re-derived from
the payload.

---

## 4. Deploying the web app — unblocks App Store review

The privacy policy has to live at a public URL before the app can be submitted. It is
written and in the repository at `frontend/app/privacy/page.tsx`; what it needs is a
deployment and a lawyer, in that order.

**How you know it worked.** The policy loads at `https://coresync.app/privacy` with no
authentication, and `mobile/.env`'s `EXPO_PUBLIC_WEB_URL` points at the same origin so
the Settings link resolves.

**Not a technical step:** the text has not been reviewed by anyone qualified. It
describes what the code actually does, which is the necessary part and not the
sufficient one.

---

## 5. Progress photos in production — unblocks the photo feature outside local dev

Locally this runs against the MinIO in `docker-compose.yml` and works today. Production
needs a **private** container and a credential scoped to it.

```
STORAGE_BACKEND=s3compat
S3_ENDPOINT_URL=<the S3-compatible endpoint>
S3_BUCKET=<bucket>
S3_ACCESS_KEY=…
S3_SECRET_KEY=…
```

With `STORAGE_BACKEND=none` the photo endpoints answer 503 and the clients say photos are
unavailable. That is the correct behaviour for a deployment that has not decided where
this data lives — it is the most sensitive data in the system.

**How you know it worked.** Upload a photo *taken on a phone, with location services on*.
Then download the stored object straight from the bucket and run `exiftool` on it. There
must be no GPS block. Do the same for the `_thumb.jpg`, which is a separate object and
the one an implementation is most likely to forget.

Then check the container is private: take a signed URL, wait for it to expire, and load
it again. It must fail. If it still loads, the bucket is public and every photo in it is
public with it.

---

## 6. Device validation

The largest remaining piece, and the one nothing in CI can substitute for. A feature is
not complete because a toggle exists, a column exists, an endpoint exists, a screen
exists, or unit tests pass. It is complete when the journey works on a phone somebody is
holding.

See [18 · Device validation checklist](18-device-validation.md).
