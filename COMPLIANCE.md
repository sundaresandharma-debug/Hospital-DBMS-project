# Launch compliance checklist

How each launch requirement is met in this codebase, and what the operator still has to do before going live.
The legal pages describe the software's actual behaviour, but they are templates: **have them reviewed by qualified counsel for your jurisdiction.**

## Before launch (operator actions)

1. The app seeds sample patients and demo accounts (`admin` / `admin123` etc.) and shows demo logins and a "Reset Demo Data" button. Remove these before real patients use it.
2. Set a strong random `SECRET_KEY` (the code default is public).
3. Set `STAFF_INVITE_CODE` to let staff self-register; leave it empty to disable staff sign-up entirely.
4. Set `CONSULTATION_FEE` to the real fee (default 800 INR).
5. Fill in every `[bracketed]` item in `static/legal/*.html` (retention periods, refund windows, payment method, governing law, hosting provider) and get legal sign-off. Bump `POLICY_VERSION` in `app.py` whenever the Terms or Privacy Policy change.
6. Set up email: `SMTP_HOST`, `SMTP_PORT` (587, or 465 for SSL), `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`, and `APP_BASE_URL` (your site address, used in links). Until then, confirmation and reset links are written to the server log (Vercel → Logs) instead of being emailed.
7. Note: on Vercel the SQLite file lives in `/tmp` and is lost between cold starts, and each server instance has its own copy. Accounts, links, rate limits, analytics and the error log all reset with it. Use a persistent, encrypted database before storing real patient data, and add Vercel Firewall rate-limit rules for limits that hold across instances.

## Checklist

| Requirement | Where / how |
|---|---|
| **Privacy policy & Terms of service** | `/privacy`, `/terms` (`static/legal/`). Linked from the sign-up consent checkbox and the footer on every screen. Acceptance time and policy version are stored per user (`USER_DATA.TERMS_ACCEPTED_AT`, `POLICY_VERSION`). |
| **Refund & Cookie policies** | `/refunds`, `/cookies`. Refund policy is linked next to every price shown (consultation booking, medicine purchase). |
| **Cookie consent banner** | Shown on first visit (`#cookie-banner`). "Necessary only" and "Accept all" have equal weight; "Manage preferences" offers per-category toggles (off by default). Reopen any time via "Cookie settings" in the footer. Only a strictly necessary session cookie is used today; any future analytics must be gated on `hasCookieConsent('analytics')` in `static/js/app.js`. |
| **Form consents** | Sign-up requires: Terms + Privacy acceptance (required, unticked); explicit health-data consent for patients (required, unticked); optional updates opt-in (unticked). Enforced server-side in `/api/auth/register`, not just in the browser. |
| **Data minimization** | Sign-up no longer invents age (30) and gender for new patients. Patients no longer receive other patients' names, ages, conditions or contact numbers from `/api/beds`, nor doctors' salaries and personal phone numbers from `/api/employees`. Patients can no longer open other patients' prescriptions or consultations by ID. No email, ID number, card details or location are collected. |
| **Audit third-party SDKs** | See `THIRD_PARTY_NOTICES.md`. Google Fonts and the cdnjs Font Awesome CDN were removed and self-hosted under `static/vendor/`, so the site makes **zero third-party requests**. A Content-Security-Policy (`default-src 'self'`) enforces this. Unused `python-dotenv` removed from `requirements.txt`. |
| **Remove dark patterns & hidden fees** | Patients can no longer type their own consultation fee; the published fee is shown before booking and enforced server-side. Medicine checkout states the total is the full amount. Bed reservation states that no charge is made. Opt-ins are never pre-ticked. Cookie choices have equal prominence. Deletion is self-service (no "email us to cancel"). |
| **Remove fake reviews & unsupported claims** | No reviews/testimonials exist. Removed: fake hotline and website on prescriptions, "Digitally verified & validated medical record", "Sanitized", "24/7 Emergency EMT", "Real-time", "Advanced", and hard-coded counts ("20 patients", "10 doctors", "70 beds") that become false as data changes. |
| **Accessibility: alt text & colour contrast** | The app has no `<img>` content; all 86 decorative icons are `aria-hidden`, and icon-only buttons (sign out, close, show password, delete, remove row) have `aria-label`s. Low-contrast colours were fixed (muted text, primary/gradient buttons, toasts, danger hover) to reach ≥ 4.5:1. Verified with axe-core (WCAG 2.0/2.1 A + AA): 0 violations across login, sign-up, patient and all staff views, and the legal pages. |
| **Keyboard navigation** | Skip link; visible `:focus-visible` outline; ward bed map rebuilt as `<button>`s with descriptive labels (tooltips also show on focus); ARIA tabs with arrow-key support; dialogs have `role="dialog"`, move focus in, trap Tab, close on Escape and restore focus; every form field has a `<label for>`; toasts announced via `aria-live`. Accessibility statement at `/accessibility`. |
| **Age consent for kids' data** | Sign-up asks whether the person is 18+; under-18 accounts require a parent/guardian name and an explicit guardian consent checkbox (stored with timestamp). Staff cannot register as minors. Staff registering a patient under 18 must record a guardian. Enforced server-side. |
| **Unsubscribe link in emails** | The portal sends only account emails (confirmation and password reset), which don't need an unsubscribe link. `email_utils.py` provides the only sanctioned builders: marketing messages always include a signed unsubscribe link plus `List-Unsubscribe` and `List-Unsubscribe-Post` (RFC 8058 one-click) headers. `/unsubscribe` handles both the link (with confirm step) and one-click POST. Users can also toggle updates in *Account & Privacy*. |
| **Licensed fonts and images** | Inter (SIL OFL 1.1) and Font Awesome Free (icons CC BY 4.0, fonts OFL 1.1, code MIT) are vendored with their licence files in `static/vendor/licenses/`. No photos or other images are used. |
| **Data deletion requests** | Everyone: *Account & Privacy* to download all their data (JSON export) and to delete their account immediately (password + typing DELETE). Each deletion is logged as completed in the staff *Privacy Requests* view. Erasure deletes the login and non-clinical data; clinical records required by law are unlinked from the account and retained, as the Privacy Policy explains. |

## Other fixes made along the way

- `app.py` used `sqlite3.IntegrityError` without importing `sqlite3`, so duplicate records crashed with a 500 instead of returning 409.
- The patient "My Medical Profile" view had no load/save JavaScript; it now loads and saves.
- The staff patients table rendered columns under the wrong headers.
- Security headers added (CSP, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `X-Frame-Options`); session cookie is `Secure` on Vercel; API responses are `no-store`.

## Production readiness

| Item | Where / how |
|---|---|
| **1. Real login and logout** | Passwords hashed with Werkzeug. Sign-in by username or email. A fresh session on every sign-in (prevents session fixation), expiring after 8 hours; `HttpOnly`, `SameSite=Lax`, `Secure` on Vercel. Logout clears the session server-side. If a session expires mid-use, the app returns to the sign-in screen with a message. |
| **2. Password reset** | "Forgot password?" on the sign-in form sends a one-time link (valid 1 hour, stored only as a SHA-256 hash). The reply is the same whether or not the account exists. Signed-in users can also change their password in *Account & Privacy*. |
| **3. Email verification** | Sign-up now asks for an email address and sends a one-time confirmation link (valid 24 hours). Unconfirmed users see a banner with "Resend link". Changing the email requires confirming the new one. |
| **4. Loading states** | Every list shows a spinner while loading. Submit buttons show a spinner and are disabled until the request finishes, so forms can't be sent twice. |
| **5. Empty states** | Every list has an empty message that says what to do next (for example "Add one with “Register Patient”"). |
| **6. Clear error messages** | The API always answers with JSON and a plain-language message, including 404 and 500. Failed lists show "Couldn't load …" with a **Try again** button. Network failures say "Can't reach the server…". Sign-in gives one message for any wrong username or password, so it can't be used to discover accounts. |
| **7. Form validation** | Server-side checks in `security.py` for usernames, emails, mobile numbers, passwords (8–128 characters), ages, amounts, quantities, text lengths and appointment times (must be in the future). The same rules are mirrored in the HTML (`pattern`, `minlength`, `type="email"`), with fields outlined in red once edited. |
| **8. Rate limiting** | Sign-in: 20 attempts per 15 minutes per network, and an account locks for 15 minutes after 5 wrong passwords. Sign-up, password reset, resend-confirmation, password change, account deletion, error reports and analytics are also limited. See the Vercel note above. |
| **9. Database backups** | Staff *System → Download backup* gives a consistent SQLite snapshot. `python backup.py [folder] [keep]` makes timestamped backups and deletes old ones, for running on a schedule. |
| **10. Row-level security** | Patient accounts only ever see records linked to their own username (previously also anyone sharing their mobile number). Staff-only endpoints check the role on every request; patients can't open other patients' consultations, prescriptions or purchases. |
| **11. API keys off the frontend** | No keys or secrets in the browser code. `SECRET_KEY`, `STAFF_INVITE_CODE` and SMTP credentials come only from environment variables; the server logs a warning if `SECRET_KEY` is missing on Vercel. |
| **12. Mobile layout** | Below 990px the sidebar becomes a slide-in menu (☰ button, closes with Escape or a tap outside). Forms stack into one column, tables scroll inside their cards, and dialogs fit small screens. Tested at 390px with no horizontal scrolling. |
| **13. Custom 404 page** | `static/404.html` for unknown pages (and `500.html` for server errors), with a link home. Unknown API addresses return a JSON 404. |
| **14. Analytics** | Built in, first-party and cookieless: counts page views per page per day, nothing about the visitor, and skipped for browsers with Do Not Track or Global Privacy Control. Staff see the last 30 days on *System*. No cookie consent needed and no third party involved. |
| **15. Error tracking** | Server exceptions and browser errors are stored in an error log (newest 500) and printed to the server log (Vercel → Logs). Staff see them on *System*. |
| **16. Privacy policy page** | `/privacy`. |
| **17. Terms page** | `/terms`. |
| **18. Delete account button** | *Account & Privacy → Delete my account*, for patients and staff. The last staff account can't be deleted. |
| **19. Onboarding flow** | A short welcome tour after first sign-in. Patients: confirm email, complete the health profile, book a first appointment. Staff: bed map, consultations and prescriptions, Privacy and System pages. It can be replayed from *Account & Privacy*. |

## Known gaps (not changed)

- Data, rate limits and links are per server instance on Vercel until a persistent database is used (see "Before launch").
- The password check doesn't block common or breached passwords.
