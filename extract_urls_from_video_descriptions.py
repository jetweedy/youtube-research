"""
extract_description_urls.py

Scans YouTube video descriptions for URLs using regex, then inserts each
found URL into a new `video_description_urls` table for later analysis.

Run once to create the table, then re-run anytime to catch new videos
(INSERT ... ON CONFLICT DO NOTHING makes it idempotent).
"""

import os
import re
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()  # loads .env from the current working directory

# ── DB connection ──────────────────────────────────────────────────────────────

PG_CONFIG = {
    "host":     os.getenv("PGHOST", "localhost"),
    "port":     os.getenv("PGPORT", "5432"),
    "dbname":   os.getenv("PGDATABASE"),
    "user":     os.getenv("PGUSER"),
    "password": os.getenv("PGPASSWORD"),
}

# ── Settings ───────────────────────────────────────────────────────────────────

SOURCE_TABLE  = "youtube_product_review_videos"
VIDEO_ID_COL  = "video_id"
TITLE_COL     = "title"
DESC_COL      = "description"

DEST_TABLE    = "video_description_urls"

# ── URL regex ──────────────────────────────────────────────────────────────────
# Matches http/https URLs; strips trailing punctuation that isn't part of the URL.

URL_RE = re.compile(
    r'https?://'               # scheme
    r'[^\s<>"\')\]]+',         # everything up to whitespace or closing bracket
    re.IGNORECASE,
)

TRAILING_PUNCT = re.compile(r'[.,;:!?)>\]]+$')

def extract_urls(text: str) -> list[str]:
    """Return a deduplicated, ordered list of URLs found in text."""
    seen = set()
    urls = []
    for match in URL_RE.finditer(text):
        url = TRAILING_PUNCT.sub("", match.group())
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls

# ── DDL ────────────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {DEST_TABLE} (
    id          SERIAL PRIMARY KEY,
    video_id    TEXT        NOT NULL,
    url         TEXT        NOT NULL,
    position    INT         NOT NULL,   -- 0-based order of appearance in description
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (video_id, url)              -- one row per unique URL per video
);
"""

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    conn = psycopg2.connect(**PG_CONFIG)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Create destination table if it doesn't exist
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    print(f"Table `{DEST_TABLE}` ready.\n")

    # Fetch all videos
    cur.execute(f'SELECT {VIDEO_ID_COL}, {TITLE_COL}, {DESC_COL} FROM {SOURCE_TABLE} ORDER BY {VIDEO_ID_COL}')
    rows = cur.fetchall()
    print(f"Loaded {len(rows)} videos.\n")

    total_inserted = 0
    total_skipped  = 0

    for row in rows:
        vid   = row[VIDEO_ID_COL]
        title = (row[TITLE_COL] or "")[:60]
        desc  = row[DESC_COL] or ""

        urls = extract_urls(desc)

        if not urls:
            print(f"[{vid}] {title!r}  →  no URLs found")
            continue

        inserted = 0
        skipped  = 0

        for position, url in enumerate(urls):
            cur.execute(
                f"""
                INSERT INTO {DEST_TABLE} (video_id, url, position)
                VALUES (%s, %s, %s)
                ON CONFLICT (video_id, url) DO NOTHING
                """,
                (vid, url, position),
            )
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1

        conn.commit()
        total_inserted += inserted
        total_skipped  += skipped
        print(f"[{vid}] {title!r}  →  {len(urls)} URL(s) found  |  {inserted} inserted, {skipped} already existed")

    print(f"\nDone. Total inserted: {total_inserted}  |  Already existed: {total_skipped}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()