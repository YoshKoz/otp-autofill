# otp-autofill

Hands-free email-OTP autofill for Firefox Nightly, backed by local Thunderbird
mail. When **you** open a login page that's asking for a verification code, the
extension fills the code and submits — no mouse takeover, no inbox-watching
daemon, no Claude in the loop.

## How it stays secure (threat: someone else / a remote login)

The trigger is **your local browser showing an OTP-entry page**, never the email
arriving. So:

- **Remote attacker logs into your account** → the code challenge renders on
  *their* browser. Your local Firefox has no OTP page open → nothing arms → the
  code sits unused in your inbox. 2FA holds.
- Gates, all must pass before a fill:
  1. **Local OTP page present + tab focused & visible** (content script).
  2. **Ordering** — code mail arrived *after* the page armed (`armTs`).
  3. **Domain match** — mail sender's registrable domain == the page's domain
     (a code meant for one site can't fill a login page on another site).
  4. **Freshness** — code mail younger than 180s.
  5. **Single use** — each code served at most once.
- **Not defended:** someone driving your actual logged-in desktop session
  (physical access / remote desktop). No software OTP helper survives that.

## Architecture

```
content.js (page)  --activeTab-->  background.js  --nativeMessaging-->  native_host.py  -->  local TB mboxes
   detects OTP field                brokers the query    (spawned on demand,        (tail-scanned,
   fills + submits                  (content scripts       no daemon)                last ~1MB each)
                                     can't call
                                     nativeMessaging
                                     directly)
```

- `native_host.py` — native-messaging host. Spawned by Firefox *on demand* while
  an OTP page is open; tail-scans the local TB mboxes (last ~1MB each, fast),
  applies the gates, returns one code. No daemon, no IMAP, no creds.
- `otp_autofill.json` — native-messaging manifest (→ `~/.mozilla/native-messaging-hosts/`).
- `extension/` — WebExtension: `content.js` detects the OTP field + fills/submits
  (single field *and* split N-box layouts), `background.js` brokers the native
  query (content scripts can't call nativeMessaging directly).

## Requirements

- Firefox Nightly (native-messaging + the unsigned-install path used here)
- Local Thunderbird profile with the account(s) you log in with
- Python 3, `zip` (used by `install.sh` to package the `.xpi`)
- A code-extraction module — `native_host.py` loads it from a hardcoded local
  path (`EXTRACTOR` near the top of the file); point that at your own OTP-parsing
  script, or inline the logic if you don't have one.

## Install

```
./install.sh
```

then the one-time browser steps it prints (set `xpinstall.signatures.required=false`,
install `otp-autofill.xpi`).

## Tuning

- Sites the extractor doesn't recognize → add phrasing to its keyword list (see
  `EXTRACTOR` in `native_host.py` for where that module is loaded from).
- New multi-part TLDs → `MULTI_TLD` in `native_host.py`.
- Field/button heuristics → `SIGNAL` / `NEGATIVE` / `SUBMIT_RE` in `content.js`.
- Debug: `~/.cache/otp-fill/host.log`.
