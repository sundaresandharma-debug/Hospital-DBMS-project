# Third-party software audit

Last audited: 16 October 2026. Re-run this audit whenever a dependency, script, font, icon set or external service is added.

## Runtime requests to third parties

**None.** All scripts, styles, fonts and icons are served from the site's own origin, enforced by the
`Content-Security-Policy` header in `app.py`. There are no analytics, advertising, tag-manager, chat,
social or error-tracking SDKs.

| Removed | Why |
|---|---|
| Google Fonts (`fonts.googleapis.com`, `fonts.gstatic.com`) | Sent every visitor's IP address to Google without consent. Replaced by self-hosted copies. |
| cdnjs Font Awesome 6.5.0 (`cdnjs.cloudflare.com`) | Same issue (IP disclosure to a third-party CDN). Replaced by a self-hosted copy of only the solid icon set. |
| `python-dotenv` (Python package) | Listed in `requirements.txt` but never imported. |

## Bundled assets (`static/vendor/`)

| Asset | Version | Licence | Licence file |
|---|---|---|---|
| Inter (latin, weights 400–800) via @fontsource | 5.1.0 | SIL Open Font License 1.1 | `static/vendor/licenses/INTER-OFL.txt` |
| Font Awesome Free (core CSS + solid icons) | 6.5.0 | Icons CC BY 4.0, fonts SIL OFL 1.1, code MIT | `static/vendor/licenses/FONT-AWESOME-FREE-LICENSE.txt` |

The Font Awesome attribution comment at the top of each CSS file must be kept, as its licence requires.

## Python dependencies (`requirements.txt`)

| Package | Licence | Notes |
|---|---|---|
| Flask (plus its dependencies Jinja2, itsdangerous, click, blinker, MarkupSafe) | BSD-3-Clause | Web framework; `itsdangerous` signs unsubscribe tokens |
| Werkzeug | BSD-3-Clause | Password hashing, routing |

## Service providers (data processors)

| Provider | Purpose | Data processed |
|---|---|---|
| Vercel Inc. (per `vercel.json`) | Hosting | All application data and request logs. A data processing agreement must be in place before launch. |
| Your SMTP email provider (optional, set with `SMTP_*`) | Sending confirmation and password-reset emails | Recipient email address, name and the one-time link. Needs a data processing agreement too. |
