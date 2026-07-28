# 11 · Security & Privacy

CoreSync holds health data, body measurements and progress photos. Under GDPR most of this is
**special-category data** (Article 9). The security bar is therefore higher than for a typical
consumer app, and privacy is a design constraint rather than a legal afterthought.

---

## 1. Threat model

### Assets, ranked by what a breach would actually cost

| Asset | Sensitivity | Why |
|---|---|---|
| **Progress photos** | Critical | Intimate images. A leak is unrecoverable and career-ending for the product |
| Credentials & tokens | Critical | Account takeover |
| Body metrics (weight, body fat, measurements) | High | Health data; deeply personal |
| Nutrition & training history | Medium-high | Reveals habits, location patterns, health status |
| AI conversations | High | Users disclose insecurities, health concerns, sometimes disordered eating |
| Email / identity | Medium | Phishing, credential stuffing |
| Payment data | — | **Never touches our systems.** Handled by Apple, Google and Stripe |

### Adversaries

| Actor | Capability | Primary controls |
|---|---|---|
| Opportunistic attacker | Automated scanning, credential stuffing, known CVEs | WAF, rate limits, patching, breach-list checks |
| Malicious user | Authenticated API access, crafted requests | Ownership scoping, input validation, quotas |
| Scraper | Mass enumeration of users, foods, exercises | UUID ids, rate limits, no bulk endpoints |
| Insider | Admin/DB access | Least privilege, audit logging, redacted admin views, step-up auth |
| Supply chain | Malicious dependency | Lockfiles, SCA scanning, pinned base images, provenance |

### Explicitly out of scope
Nation-state adversaries, physical attacks on Azure datacentres, compromised end-user devices.

---

## 2. OWASP Top 10 (2021) — control mapping

| Risk | Controls in CoreSync |
|---|---|
| **A01 Broken access control** | `user_id` is a required parameter on every repository read ([05](05-backend-architecture.md) §3) — there is no method signature that permits an unscoped fetch. UUIDv7 ids prevent enumeration. `404` not `403` for foreign resources. Role + entitlement checks server-side only. Automated IDOR test suite that replays every authenticated endpoint with a second user's ids |
| **A02 Cryptographic failures** | TLS 1.2+ everywhere, HSTS with preload. Argon2id password hashing (m=64 MiB, t=3, p=4). Tokens stored as SHA-256 hashes. AES-256 at rest (Azure-managed). Progress photos in a private container, served only via 15-minute SAS URLs. No secrets in code, config files or logs |
| **A03 Injection** | SQLAlchemy parameterised queries exclusively; raw SQL requires `text()` with bound parameters and a code-owner review. Pydantic validation on every input. React auto-escaping. Strict CSP. **Prompt injection** treated as a first-class case ([10](10-ai-architecture.md) §7.4) |
| **A04 Insecure design** | Threat modelling per feature. Safety limits in the schema, not only in code. Rate limits designed per endpoint from the start. Abuse cases in the test suite |
| **A05 Security misconfiguration** | Infrastructure as code (Bicep) — no click-ops. Non-root containers, read-only filesystems, distroless-style minimal images. Debug and docs endpoints disabled in production. Security headers enforced by middleware and asserted in tests |
| **A06 Vulnerable components** | Dependabot + `pip-audit` + `npm audit` in CI. Pinned lockfiles. Base images rebuilt weekly. Critical CVEs block deploy |
| **A07 Auth failures** | Full flow in [06](06-authentication.md): rotation with reuse detection, lockout, breach-list checks, no enumeration, constant-time verification |
| **A08 Data integrity failures** | Signed CI artifacts, image digest pinning, no unpinned third-party scripts, SRI where external scripts are unavoidable. EAS Update payloads signed |
| **A09 Logging & monitoring failures** | Structured logs with request ids, security-event stream (login failures, token reuse, privilege changes, admin actions), alerting on anomalies, 90-day hot retention |
| **A10 SSRF** | No user-supplied URL is ever fetched. Outbound calls go only to an allow-list of known hosts. Image processing operates on our own blobs, never on a remote URL |

---

## 3. Application controls

### 3.1 Input validation
Pydantic v2 on every request body, query parameter and path parameter. Strict types, explicit
bounds, `extra="forbid"` so unexpected fields are rejected rather than silently ignored. Length
limits on every string. `Decimal` for measurements. File uploads validated by **magic bytes, not
by extension or client-supplied MIME type**.

### 3.2 Output encoding
JSON responses are encoded, never templated. No HTML rendering of user content server-side. React
escapes by default and `dangerouslySetInnerHTML` is banned by lint rule with a single reviewed
exception (the theme bootstrap script in [07](07-frontend-web.md) §8, which contains no user data).

### 3.3 Security headers

```python
SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=(), payment=(self)",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'strict-dynamic' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline'; "        # Tailwind runtime styles
        "img-src 'self' data: blob: https://cdn.coresync.ai; "
        "connect-src 'self' https://api.coresync.ai; "
        "font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}
```

Nonce-based CSP with `strict-dynamic` — not an allow-list of CDN hostnames, which is trivially
bypassable via any hosted library on those domains.

### 3.4 CORS
Explicit origin allow-list (`https://coresync.ai`, `https://www.coresync.ai`, and localhost in
development). `allow_credentials=True` with `allow_origins=["*"]` is a contradiction the browser
rejects and a mistake we cannot make because the origin list is validated at startup. Mobile
clients do not send `Origin` and are unaffected.

### 3.5 CSRF
The API is token-based, so most endpoints are inherently CSRF-safe. The exception is the
refresh-token cookie flow: `SameSite=Lax`, path-scoped to `/v1/auth/refresh`, plus a
double-submit CSRF token on that endpoint.

### 3.6 File uploads

| Control | Detail |
|---|---|
| Direct-to-blob | Bytes never pass through the API ([02](02-system-architecture.md) §5.3) |
| SAS scope | Write-only, single blob, 15-minute expiry |
| Size | 15 MB enforced by the SAS policy, not only by the client |
| Type | Magic-byte verification post-upload; anything not JPEG/PNG/HEIC/WebP is deleted |
| Re-encoding | Every image is decoded and re-encoded server-side — this destroys embedded payloads and polyglot files |
| **EXIF** | Stripped unconditionally. Progress photos routinely carry GPS coordinates of the user's home |
| Serving | Private container, short-lived SAS, `Content-Disposition: attachment`, no direct public URL ever issued |
| Orphans | Unconfirmed uploads reaped after 24 hours |

### 3.7 Rate limiting & abuse
Per-endpoint buckets ([04](04-api-design.md) §3), at both WAF and application layers.
Progressive penalties for repeat offenders. Per-user AI token budgets. Upload quotas. Anomaly
detection on impossible usage patterns (e.g. 200 workouts logged in an hour).

---

## 4. Infrastructure security

| Layer | Controls |
|---|---|
| **Network** | Postgres and Redis reachable only via private endpoints — **no public network access**. App Service VNet-integrated. Azure OpenAI over a private endpoint |
| **WAF** | Azure Front Door with the OWASP managed ruleset, bot protection, per-IP volumetric limits, geo-blocking available for incident response |
| **Identity** | Managed identity for App Service → Key Vault, Blob, Postgres. **No connection strings with passwords in configuration** |
| **Secrets** | Key Vault with soft delete and purge protection; App Service reads Key Vault references. Rotation: JWT signing key quarterly, DB credentials quarterly, API keys on personnel change |
| **Containers** | Non-root user, read-only root filesystem, no shell in the production image, minimal base, Trivy scan in CI blocking on High/Critical |
| **Database** | TLS required, firewall closed to public, least-privilege application role (no `SUPERUSER`, no `CREATE`), separate migration role, PITR backups |
| **Admin access** | No standing production access. Just-in-time elevation via PIM with approval, MFA required, session recorded |

---

## 5. Logging & monitoring

**Security event stream** (separate from application logs, 90-day hot / 1-year archive):
authentication successes and failures, token reuse detections, password and email changes,
permission changes, admin actions, rate-limit breaches, upload rejections, AI safety flags.

**Alerts:**

| Condition | Severity |
|---|---|
| Refresh-token reuse detected | High — page on-call |
| > 100 failed logins from one IP in 5 min | Medium |
| Admin action outside business hours | Medium — review |
| Any access to `progress_photos` by a non-owner | **Critical — page immediately** |
| Error rate > 2 % for 5 min | High |
| Unusual data egress from Blob Storage | High |
| AI cost > 3× the daily baseline | Medium |

**Log hygiene:** a redaction processor strips passwords, tokens, full email addresses (hashed
instead), AI message bodies, diary contents and photo paths before anything reaches storage. PII
in logs is a breach in its own right.

---

## 6. Data classification

| Class | Data | Encryption | Access | Retention |
|---|---|---|---|---|
| **Restricted** | Progress photos, AI conversations | At rest + private container + SAS-only | Owner only; admin needs step-up + audit | Life of account |
| **Confidential** | Password hashes, tokens, body metrics, diary | At rest | Owner; service accounts | Per [03](03-database-schema.md) §12 |
| **Internal** | Aggregates, usage analytics | At rest | Engineering (aggregated) | 24 months |
| **Public** | Exercise catalog, verified foods, marketing | — | Everyone | — |

---

## 7. Privacy by design

| GDPR principle | Implementation |
|---|---|
| **Lawful basis** | Consent for special-category health data, captured explicitly at onboarding with granular toggles; contract for core service delivery |
| **Data minimisation** | We do not ask for what we do not use. No phone number, no address, no precise location, ever |
| **Purpose limitation** | AI training opt-in is separate, off by default, and revocable; photos are excluded unconditionally |
| **Storage limitation** | Retention schedule enforced by scheduled jobs, not by policy documents |
| **Accuracy** | Users can edit or delete any record |
| **Integrity & confidentiality** | Sections 2–5 above |
| **Accountability** | Records of processing, DPIA for the AI and photo features, audit logs |

**Consent UX:** granular, unbundled toggles for health-data processing, AI coaching, AI photo
analysis, model-improvement opt-in, and marketing email. Each is independently revocable in
settings, with the consequence of revoking stated plainly. No pre-ticked boxes, no dark patterns,
no "reject" hidden two levels deep.

---

## 8. Data subject rights

| Right | Implementation | SLA |
|---|---|---|
| **Access / portability** | `GET /users/me/export` → async job → ZIP of JSON + original photos, download link valid 7 days | < 24 h automated |
| **Rectification** | Every record is user-editable in-app | Immediate |
| **Erasure** | `DELETE /users/me` → 30-day grace (recoverable, and the user is told) → hard erasure job | 30 days |
| **Restriction** | Account freeze: data retained, processing stopped | On request |
| **Objection** | Opt out of AI processing and analytics while keeping the core service | Immediate |
| **Withdraw consent** | Any toggle, any time | Immediate |

**The erasure job is a tested, ordered procedure**, not a `DELETE FROM users` and a hope:

1. Delete Blob objects: photos, thumbnails, avatars, exports.
2. Delete `ai_embeddings` where `owner_user_id` matches — *including derived summaries*. Orphaned
   embeddings are the most commonly missed leak in an AI product.
3. Cascade-delete user-owned rows.
4. Anonymise rows that must survive: financial records (retained for tax law) keep an opaque id
   with all PII nulled; audit logs keep the actor id but drop identifying attributes.
5. Delete the `users` row.
6. Write a completion record to a separate, minimal erasure ledger (id + timestamp only) to prove
   compliance without retaining the person.
7. Purge from backups on their natural rotation, documented in the privacy policy as required.

An integration test seeds a user with data in **every** table and asserts that nothing remains
afterwards. That test is the only credible proof that erasure works.

---

## 9. Third-party processors

| Processor | Data | Region | Basis |
|---|---|---|---|
| Microsoft Azure | All | EU (West Europe) | DPA, EU data boundary |
| Azure OpenAI | Chat context, photos (analysis only) | EU, private endpoint, zero retention | DPA |
| Vercel | Web hosting, no PII at rest | EU edge | DPA |
| Sentry | Error traces (PII scrubbed) | EU | DPA |
| Expo / RevenueCat | Push tokens, purchase receipts | US | DPA + SCCs |
| Apple / Google / Stripe | Payment data (never ours) | — | Their controllers |

Sub-processors are listed publicly and changes are announced 30 days in advance.

---

## 10. Security testing

| Activity | Frequency | Gate |
|---|---|---|
| SAST (`ruff`+`bandit`, `semgrep`, CodeQL) | Every PR | Blocks on High |
| SCA (`pip-audit`, `npm audit`, Dependabot) | Every PR + daily | Blocks on Critical |
| Container scan (Trivy) | Every build | Blocks on High/Critical |
| Secret scanning (gitleaks + GitHub push protection) | Every commit | Blocks |
| DAST (OWASP ZAP baseline) | Nightly against staging | Reviewed |
| IDOR / authz suite | Every PR | Blocks |
| Dependency review | Every PR | Blocks on new Critical |
| **External penetration test** | Before launch, then annually | All High findings fixed before release |
| Threat model review | Per major feature | — |

---

## 11. Incident response

**Severity:** SEV1 data breach or full outage · SEV2 partial outage or security incident without
data loss · SEV3 degraded · SEV4 minor.

**Procedure:** detect → triage and assign an incident commander → contain (revoke tokens, rotate
secrets, block IPs, disable the affected feature via flag) → eradicate → recover → blameless
post-mortem within 5 working days.

**Breach notification:** supervisory authority within **72 hours** of becoming aware; affected
users without undue delay when the risk is high. The notification templates and the decision tree
are written *before* they are needed — during an incident is the worst possible time to draft
them.

**Runbooks** exist for: leaked credentials, token-reuse spike, DDoS, database compromise,
malicious insider, dependency compromise, and progress-photo exposure. Each is rehearsed at least
once a year.

---

## 12. Pre-launch checklist

- [ ] External penetration test complete; all High findings closed
- [ ] All secrets in Key Vault; none in code, config or CI logs
- [ ] TLS + HSTS preload; security headers verified by automated test
- [ ] Rate limiting live and load-tested
- [ ] IDOR suite green across every authenticated endpoint
- [ ] Erasure job verified by the all-tables integration test
- [ ] Export job verified for completeness
- [ ] Backups tested by an actual restore, not by a green tick
- [ ] Privacy policy, ToS, cookie policy and sub-processor list published
- [ ] DPIA completed for AI coaching and photo analysis
- [ ] Consent flows reviewed by counsel
- [ ] Incident runbooks written; on-call rota staffed
- [ ] Security logging and alerting verified end to end
- [ ] AI safety eval suite at 100 % pass ([10](10-ai-architecture.md) §8)

---

**Next:** [12 · DevOps & Deployment](12-devops-deployment.md)
