"""
extract_description_urls.py

Scans YouTube video descriptions for URLs using regex, then inserts each
found URL into `video_description_urls` and checks whether it is still live.

Status values written to the `url_status` column:
  blocked   - domain is on the blocklist (skipped, no HTTP request made)
  active    - 2xx response
  redirect  - 3xx response (final destination not followed)
  not_found - 404
  dead      - connection error, timeout, or DNS failure
  error     - unexpected exception

Run anytime; already-checked URLs are skipped unless you set RECHECK=True.
"""

import os
import re
import time
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

load_dotenv()

# ── DB connection ──────────────────────────────────────────────────────────────

PG_CONFIG = {
    "host":     os.getenv("PGHOST", "localhost"),
    "port":     os.getenv("PGPORT", "5432"),
    "dbname":   os.getenv("PGDATABASE"),
    "user":     os.getenv("PGUSER"),
    "password": os.getenv("PGPASSWORD"),
}

# ── Settings ───────────────────────────────────────────────────────────────────

SOURCE_TABLE  = "youtube_videos"   # ← your actual table name
VIDEO_ID_COL  = "video_id"
TITLE_COL     = "title"
DESC_COL      = "description"

DEST_TABLE    = "video_description_urls"

# Re-check URLs that were already checked on a previous run
RECHECK       = False

# Seconds to wait between HTTP requests (be polite)
REQUEST_DELAY = 0.5

# HTTP timeout in seconds
HTTP_TIMEOUT  = 8

# ── Blocklist ──────────────────────────────────────────────────────────────────
# Any URL whose registered domain matches an entry here is recorded as
# `blocked` and no HTTP request is made.

BLOCKED_DOMAINS = {
    # Video platforms
    "youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "tiktok.com",
    # Social media
    "instagram.com", "twitter.com", "x.com", "facebook.com", "fb.com",
    "linkedin.com", "pinterest.com", "reddit.com", "threads.net",
    # Link shorteners / redirectors
    "bit.ly", "tinyurl.com", "ow.ly", "t.co", "goo.gl", "buff.ly",
    "ift.tt", "dlvr.it", "short.io", "rebrand.ly", "lnk.to", "ffm.to",
    "smarturl.it", "linktr.ee", "beacons.ai",
    # Support / fan funding
    "patreon.com", "ko-fi.com", "buymeacoffee.com",
    # Podcast / audio
    "open.spotify.com", "podcasts.apple.com", "anchor.fm",
    # Misc common noise
    "discord.gg", "discord.com", "mailchi.mp",
}

def is_blocked(url: str) -> bool:
    """Return True if the URL's domain (or a parent domain) is on the blocklist."""
    try:
        host = urlparse(url).hostname or ""
        host = host.lower().lstrip("www.")
        parts = host.split(".")
        for i in range(len(parts) - 1):
            candidate = ".".join(parts[i:])
            if candidate in BLOCKED_DOMAINS:
                return True
    except Exception:
        pass
    return False

# ── URL regex ──────────────────────────────────────────────────────────────────

URL_RE         = re.compile(r'https?://[^\s<>"\')\]]+', re.IGNORECASE)
TRAILING_PUNCT = re.compile(r'[.,;:!?)>\]]+$')

def extract_urls(text: str) -> list[str]:
    seen, urls = set(), []
    for match in URL_RE.finditer(text):
        url = TRAILING_PUNCT.sub("", match.group())
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls

# ── HTTP check ─────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

def check_url(url: str) -> tuple[str, int | None]:
    """
    Returns (status_label, http_status_code).
    Tries HEAD first; falls back to GET if the server rejects HEAD.
    """
    try:
        resp = requests.head(url, headers=HEADERS, timeout=HTTP_TIMEOUT,
                             allow_redirects=False)
        if resp.status_code in (405, 501):
            resp = requests.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT,
                                allow_redirects=False, stream=True)
            resp.close()

        code = resp.status_code
        if 200 <= code < 300:
            label = "active"
        elif 300 <= code < 400:
            label = "redirect"
        elif code == 404:
            label = "not_found"
        else:
            label = "dead"
        return label, code

    except requests.exceptions.ConnectionError:
        return "dead", None
    except requests.exceptions.Timeout:
        return "dead", None
    except Exception:
        return "error", None

# ── DDL ────────────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {DEST_TABLE} (
    id             SERIAL PRIMARY KEY,
    video_id       TEXT        NOT NULL,
    url            TEXT        NOT NULL,
    position       INT         NOT NULL,
    url_status     TEXT,                   -- active | redirect | not_found | dead | blocked | error
    http_status    INT,                    -- raw HTTP status code (NULL if blocked/dead/error)
    checked_at     TIMESTAMPTZ,
    inserted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (video_id, url)
);
"""

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    conn = psycopg2.connect(**PG_CONFIG)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    print(f"Table `{DEST_TABLE}` ready.\n")

    cur.execute(
        f"SELECT {VIDEO_ID_COL}, {TITLE_COL}, {DESC_COL} "
        f"FROM {SOURCE_TABLE} ORDER BY {VIDEO_ID_COL}"
    )
    rows = cur.fetchall()
    print(f"Loaded {len(rows)} videos.\n")

    total_inserted = total_skipped = total_checked = 0

    for row in rows:
        vid   = row[VIDEO_ID_COL]
        title = (row[TITLE_COL] or "")[:60]
        desc  = row[DESC_COL] or ""

        urls = extract_urls(desc)
        if not urls:
            print(f"[{vid}] {title!r}  →  no URLs")
            continue

        print(f"[{vid}] {title!r}  →  {len(urls)} URL(s)")

        for position, url in enumerate(urls):
            # Upsert the row
            cur.execute(
                f"""
                INSERT INTO {DEST_TABLE} (video_id, url, position)
                VALUES (%s, %s, %s)
                ON CONFLICT (video_id, url) DO NOTHING
                """,
                (vid, url, position),
            )
            if cur.rowcount:
                total_inserted += 1
            else:
                total_skipped += 1

            # Skip if already checked (unless RECHECK=True)
            if not RECHECK:
                cur.execute(
                    f"SELECT checked_at FROM {DEST_TABLE} WHERE video_id=%s AND url=%s",
                    (vid, url),
                )
                already = cur.fetchone()
                if already and already["checked_at"] is not None:
                    print(f"    skip (already checked)  {url[:80]}")
                    continue

            # Blocked?
            if is_blocked(url):
                label, code = "blocked", None
            else:
                time.sleep(REQUEST_DELAY)
                label, code = check_url(url)
                total_checked += 1

            cur.execute(
                f"""
                UPDATE {DEST_TABLE}
                SET url_status = %s, http_status = %s, checked_at = NOW()
                WHERE video_id = %s AND url = %s
                """,
                (label, code, vid, url),
            )

            status_str = f"{label}" + (f" ({code})" if code else "")
            print(f"    {status_str:<20}  {url[:80]}")

        conn.commit()

    print(
        f"\nDone.  Inserted: {total_inserted}  |  "
        f"Already existed: {total_skipped}  |  "
        f"URLs checked: {total_checked}"
    )

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()