#!/usr/bin/env python3
"""Native-messaging host for the otp-autofill Firefox extension.

The extension connects ONLY while the user's local browser is showing an
OTP-entry page. It sends {hostname, armTs}; this host tail-scans the local
Thunderbird mboxes for a fresh verification code whose sender domain matches
the page, that arrived AFTER the page armed, and returns it once.

Security gates enforced here (the browser enforces "page is open" + focus):
  - domain match : sender registrable-domain == page registrable-domain
  - ordering     : code mail timestamp >= armTs - SKEW
  - freshness    : code mail within FRESH_SEC
  - single use   : a code is served at most once (used.json)

No daemon, no inbox watching: this process is spawned by Firefox on demand and
exits when the port closes. Reads local mbox files only — no IMAP, no creds.
"""
import sys, os, json, struct, re, time, importlib.util
from datetime import timezone
from email import message_from_string, header as eheader
from email.utils import parsedate_to_datetime

# ---- config ----------------------------------------------------------------
PROFILE = "/home/yoshkoz/.thunderbird/v31m5jij.default-release"
MBOXES = [
    f"{PROFILE}/ImapMail/outlook.office365.com/INBOX",
    f"{PROFILE}/ImapMail/imap.gmail.com/INBOX",
    f"{PROFILE}/ImapMail/imap.ziggo.nl/INBOX",
    f"{PROFILE}/Mail/Local Folders/Security",
]
TAIL_BYTES = 1_000_000      # scan only last ~1MB of each mbox (recent mail)
FRESH_SEC  = 180            # code mail must be younger than this
SKEW_SEC   = 90            # allow code that landed slightly before arm (clock skew / fast mail)
STATE_DIR  = os.path.expanduser("~/.cache/otp-fill")
USED_FILE  = f"{STATE_DIR}/used.json"
LOG_FILE   = f"{STATE_DIR}/host.log"
EXTRACTOR  = "/home/yoshkoz/code/projects/verify-code-grab.py"

# Multi-part public suffixes we care about (extend as needed).
MULTI_TLD = {"co.uk", "org.uk", "gov.uk", "ac.uk", "com.au", "net.au",
             "co.nz", "co.jp", "com.br", "co.za"}


def log(msg):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


# ---- reuse the (already battle-tested) extractor ---------------------------
def load_extractor():
    spec = importlib.util.spec_from_file_location("vc", EXTRACTOR)
    vc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vc)
    return vc

VC = load_extractor()


# ---- domain helpers --------------------------------------------------------
def registrable(host):
    """Crude eTLD+1: handles the common multi-part suffixes in MULTI_TLD."""
    host = (host or "").lower().strip().strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) < 2:
        return host
    last2 = ".".join(parts[-2:])
    if last2 in MULTI_TLD and len(parts) >= 3:
        return ".".join(parts[-3:])
    return last2


SENDER_RE = re.compile(r"[\w.+-]+@([\w.-]+)")


def sender_domain(from_hdr):
    m = SENDER_RE.search(from_hdr or "")
    return registrable(m.group(1)) if m else ""


# ---- mbox tail scan --------------------------------------------------------
FROM_SPLIT = re.compile(rb"\nFrom ")


def tail_messages(path):
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    try:
        with open(path, "rb") as f:
            if size > TAIL_BYTES:
                f.seek(size - TAIL_BYTES)
            chunk = f.read()
    except OSError:
        return
    # split into message blobs on the mbox "From " separator. Each piece begins
    # with the REST of the envelope line (e.g. "- Tue Jun 24 ...") — drop that
    # first line so the real RFC822 headers parse.
    for raw in FROM_SPLIT.split(chunk)[1:]:   # drop first (partial) chunk
        nl = raw.find(b"\n")
        body = raw[nl + 1:] if nl != -1 else b""
        try:
            yield message_from_string(body.decode("latin-1", "replace"))
        except Exception:
            continue


def decode_subject(msg):
    try:
        return str(eheader.make_header(eheader.decode_header(msg.get("Subject", ""))))
    except Exception:
        return msg.get("Subject", "") or ""


def find_code(hostname, arm_ts, used):
    want = registrable(hostname)
    now = time.time()
    best = None
    for path in MBOXES:
        for msg in tail_messages(path):
            try:
                d = msg.get("Date")
                dt = parsedate_to_datetime(d) if d else None
                if dt is None:
                    continue
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ts = dt.timestamp()
            except Exception:
                continue
            if now - ts > FRESH_SEC:           # too old
                continue
            if ts < arm_ts - SKEW_SEC:          # arrived before the page armed
                continue
            frm = str(msg.get("From", ""))
            if want and sender_domain(frm) != want:   # wrong site
                continue
            code = VC.extract_code(decode_subject(msg), VC.body_text(msg))
            if not code:
                continue
            key = f"{code}:{int(ts)}"
            if key in used:                     # already used
                continue
            if best is None or ts > best[2]:
                best = (code, key, ts, frm)
    return best


# ---- single-use bookkeeping ------------------------------------------------
def load_used():
    try:
        with open(USED_FILE) as f:
            data = json.load(f)
    except Exception:
        data = {}
    cutoff = time.time() - 3600
    return {k: v for k, v in data.items() if v > cutoff}


def save_used(used):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = USED_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(used, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, USED_FILE)


# ---- native messaging framing ----------------------------------------------
def read_msg():
    raw_len = sys.stdin.buffer.read(4)
    if len(raw_len) < 4:
        return None
    n = struct.unpack("<I", raw_len)[0]
    return json.loads(sys.stdin.buffer.read(n).decode("utf-8"))


def write_msg(obj):
    data = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def main():
    while True:
        req = read_msg()
        if req is None:
            break
        try:
            hostname = req.get("hostname", "")
            arm_ts = float(req.get("armTs", 0)) / 1000.0   # JS ms -> s
            # Empty/unknown host (e.g. file:// pages) has no domain to match —
            # refuse, so a local page can't vacuum up any fresh code.
            if not registrable(hostname):
                log(f"QUERY host=<empty> -> refused")
                write_msg({})
                continue
            used = load_used()
            hit = find_code(hostname, arm_ts, used)
            log(f"QUERY host={hostname} armTs={int(arm_ts)} -> "
                f"{'HIT ' + hit[0] if hit else 'none'}")
            if hit:
                code, key, ts, frm = hit
                used[key] = time.time()
                save_used(used)
                log(f"SERVE {code} -> {hostname} (from {frm[:40]})")
                write_msg({"code": code})
            else:
                write_msg({})
        except Exception as e:
            log(f"ERR {e!r}")
            write_msg({"error": str(e)})


if __name__ == "__main__":
    main()
