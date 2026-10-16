# Launch compliance checklist

How each launch requirement is met in this codebase, and what the operator still has to do before going live.
The legal pages describe the software's actual behaviour, but they are templates: **have them reviewed by qualified counsel for your jurisdiction.**

## Before launch (operator actions)

1. The app seeds sample patients and demo accounts (`admin` / `admin123` etc.) and shows demo logins and a "Reset Demo Data" button. Remove these before real patients use it.
2. Set a strong random `SECRET_KEY` (the code default is public).
3. Set `STAFF_INVITE_CODE` to let staff self-register; leave it empty to disable staff sign-up entirely.
4. Set `CONSULTATION_FEE` to the real fee (default 800 INR).
5. Fill in every `[bracketed]` item in `static/legal/*.html` (retention periods, refund windows, payment method, governing law, hosting provider) and get legal sign-off. Bump `POLICY_VERSION` in `app.py` whenever the Terms or Privacy Policy change.
6. Note: on Vercel the SQLite file lives in `/tmp` and is lost between cold starts. Use a persistent, encrypted database before storing real patient data.

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
| **Unsubscribe link in emails** | The portal sends no email today. `email_utils.py` provides the only sanctioned builders: marketing messages always include a signed unsubscribe link plus `List-Unsubscribe` and `List-Unsubscribe-Post` (RFC 8058 one-click) headers. `/unsubscribe` handles both the link (with confirm step) and one-click POST. Users can also toggle updates in their profile. |
| **Licensed fonts and images** | Plus Jakarta Sans and Outfit (SIL OFL 1.1) and Font Awesome Free (icons CC BY 4.0, fonts OFL 1.1, code MIT) are vendored with their licence files in `static/vendor/licenses/`. No photos or other images are used. |
| **Data deletion requests** | Patients: *My Medical Profile → Privacy & My Data* to download all their data (JSON export), and to request deletion (password confirmation). Staff: *Privacy Requests* view to erase or reject (with reason) within 30 days; outcome is shown to the requester. Erasure deletes the login and non-clinical data; clinical records required by law are unlinked from the account and retained, as the Privacy Policy explains. |

## Other fixes made along the way

- `app.py` used `sqlite3.IntegrityError` without importing `sqlite3`, so duplicate records crashed with a 500 instead of returning 409.
- The patient "My Medical Profile" view had no load/save JavaScript; it now loads and saves.
- The staff patients table rendered columns under the wrong headers.
- Security headers added (CSP, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `X-Frame-Options`); session cookie is `Secure` on Vercel; API responses are `no-store`.

## Known gaps (not changed)

- Patient records are matched to a login by username **or mobile number**, so two accounts sharing a mobile number can see each other's records. Consider matching by username only.
- Passwords need only 6 characters and there is no login rate limiting.
