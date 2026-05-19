"""
find_viral_product_reviews.py

Install:
    pip install requests psycopg2-binary python-dotenv

.env:
    YOUTUBE_API_KEY=your_key_here
    PGHOST=localhost
    PGPORT=5432
    PGDATABASE=youtube_research
    PGUSER=postgres
    PGPASSWORD=your_password
"""

import os
import time
import math
import requests
import psycopg2
import psycopg2.extras
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from datetime import datetime, timezone


load_dotenv()


# =============================================================================
# CONFIG
# =============================================================================

API_KEY = os.getenv("YOUTUBE_API_KEY")

PG_CONFIG = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": os.getenv("PGPORT", "5432"),
    "dbname": os.getenv("PGDATABASE"),
    "user": os.getenv("PGUSER"),
    "password": os.getenv("PGPASSWORD"),
}

START_DATE = "2015-01-01T00:00:00Z"
END_DATE = "2021-01-01T00:00:00Z"

MIN_VIEWS = 10_000_000

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

SEARCH_COST = 100
VIDEOS_COST = 1
VIDEO_BATCH_SIZE = 50

DAILY_QUOTA_BUDGET = 9000
CHECKPOINT_EVERY_QUERIES = 5
MAX_PAGES_PER_QUERY = 4

quota_used_estimate = 0


REVIEW_TERMS = [
    #"best",
    #"review",
    #"unboxing",
    "comparison",
    #"setup",
    #"gear",
    #"kit",
    #"what I use",
    #"worth it",
    #"vs",
    #"budget",
    #"beginner",
    #"how to choose",
]


PRODUCT_TERMS = [
    #"camera gear",
    "podcast microphone",
    "streaming setup",
    "bike gear",
    "bikepacking gear",
    "cycling accessories",
    "drone",

    #"youtube setup",
    #"vlogging setup",
    #"best camera for youtube",
    #"microphone for youtube",
    #"lighting kit",
    #"tripod",
    #"camera bag",

    #"gaming setup",
    #"gaming mouse",
    #"mechanical keyboard",
    #"gaming headset",
    #"gaming chair",
    #"stream deck",
    #"monitor setup",

    #"headphones",
    #"wireless earbuds",
    #"bluetooth speaker",
    #"studio headphones",

    #"kitchen gadget",
    #"coffee gear",
    #"air fryer",
    #"robot vacuum",
    #"smart home",
    #"security camera",

    #"home gym",
    #"resistance bands",
    #"adjustable dumbbells",
    #"fitness tracker",
    #"camping gear",

    #"laptop",
    #"smartwatch",
    #"iphone accessories",
    #"phone accessories",
]


DESCRIPTION_LINK_TERMS = [
    "links below",
    "link in description",
    "affiliate",
    "amazon",
    "gear list",
    "my gear",
    "kit",
    "what i use",
    "products mentioned",
]


# =============================================================================
# USER PROMPTS / QUOTA SAFETY
# =============================================================================

def ask_continue(message):
    while True:
        ans = input(
            f"\n{message}\nContinue? [y]es / [s]kip / [q]uit: "
        ).strip().lower()

        if ans in ("y", "yes"):
            return "yes"
        if ans in ("s", "skip"):
            return "skip"
        if ans in ("q", "quit"):
            return "quit"

        print("Please enter y, s, or q.")


def estimate_search_cost(num_queries, max_pages):
    return num_queries * max_pages * SEARCH_COST


def estimate_video_cost(num_video_ids):
    batches = math.ceil(num_video_ids / VIDEO_BATCH_SIZE)
    return batches * VIDEOS_COST


def quota_guard(extra_units):
    global quota_used_estimate

    projected = quota_used_estimate + extra_units

    if projected > DAILY_QUOTA_BUDGET:
        decision = ask_continue(
            f"Estimated quota would reach {projected:,} units, "
            f"above your budget of {DAILY_QUOTA_BUDGET:,}."
        )

        if decision == "quit":
            raise SystemExit("Stopped by user.")

        if decision == "skip":
            return False

    return True


def spend_quota(units):
    global quota_used_estimate
    quota_used_estimate += units


# =============================================================================
# DATABASE
# =============================================================================

def get_conn():
    missing = [k for k, v in PG_CONFIG.items() if not v and k != "port"]
    if missing:
        raise RuntimeError(f"Missing PostgreSQL config values: {missing}")

    return psycopg2.connect(**PG_CONFIG)


def init_db():
    sql = """
    CREATE TABLE IF NOT EXISTS youtube_product_review_videos (
        video_id TEXT PRIMARY KEY,
        title TEXT,
        description TEXT,
        channel_id TEXT,
        channel_title TEXT,
        published_at TIMESTAMPTZ,
        view_count BIGINT,
        like_count BIGINT,
        comment_count BIGINT,
        duration TEXT,
        query_source TEXT,
        url TEXT,
        views_per_day NUMERIC,
        viral_score NUMERIC,
        link_intent_score INTEGER,
        raw_json JSONB,
        inserted_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    ALTER TABLE youtube_product_review_videos
        ADD COLUMN IF NOT EXISTS link_intent_score INTEGER;

    CREATE INDEX IF NOT EXISTS idx_youtube_reviews_published_at
        ON youtube_product_review_videos (published_at);

    CREATE INDEX IF NOT EXISTS idx_youtube_reviews_view_count
        ON youtube_product_review_videos (view_count);

    CREATE INDEX IF NOT EXISTS idx_youtube_reviews_viral_score
        ON youtube_product_review_videos (viral_score);

    CREATE INDEX IF NOT EXISTS idx_youtube_reviews_link_intent_score
        ON youtube_product_review_videos (link_intent_score);
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)


def test_db_upsert():
    fake_video = {
        "id": "TEST_VIDEO_ID",
        "snippet": {
            "title": "Test Camera Gear Review",
            "description": "This is a test review of camera gear with amazon links below.",
            "channelId": "TEST_CHANNEL",
            "channelTitle": "Test Channel",
            "publishedAt": "2018-01-01T00:00:00Z",
        },
        "statistics": {
            "viewCount": str(MIN_VIEWS + 1),
            "likeCount": "1000",
            "commentCount": "100",
        },
        "contentDetails": {
            "duration": "PT10M"
        }
    }

    saved = upsert_videos([fake_video], "db self test")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM youtube_product_review_videos WHERE video_id = %s",
                ("TEST_VIDEO_ID",)
            )

    print(f"Database upsert self-test passed. Rows saved temporarily: {saved}")


# =============================================================================
# YOUTUBE API
# =============================================================================

def youtube_get(url, params, retries=3):
    params = dict(params)
    params["key"] = API_KEY

    for attempt in range(retries):
        r = requests.get(url, params=params, timeout=30)

        if r.status_code == 200:
            return r.json()

        if r.status_code in (403, 429, 500, 502, 503, 504):
            wait = 2 ** attempt
            print(f"Request failed {r.status_code}; retrying in {wait}s...")
            time.sleep(wait)
            continue

        raise RuntimeError(f"YouTube API error {r.status_code}: {r.text}")

    raise RuntimeError(f"YouTube API failed after {retries} retries: {r.text}")


def search_video_ids(query, max_pages=5):
    ids = []
    page_token = None
    pages_used = 0

    for _ in range(max_pages):
        params = {
            "part": "snippet",
            "type": "video",
            "q": query,
            "order": "viewCount",
            "maxResults": 50,
            "publishedAfter": START_DATE,
            "publishedBefore": END_DATE,
            "safeSearch": "none",
        }

        if page_token:
            params["pageToken"] = page_token

        data = youtube_get(SEARCH_URL, params)
        pages_used += 1

        for item in data.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if vid:
                ids.append(vid)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return ids, pages_used


def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def fetch_video_details(video_ids):
    results = []

    for batch in chunks(video_ids, VIDEO_BATCH_SIZE):
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(batch),
            "maxResults": 50,
        }

        data = youtube_get(VIDEOS_URL, params)
        results.extend(data.get("items", []))

    return results


# =============================================================================
# SCORING / FILTERING
# =============================================================================

def parse_int(value):
    try:
        return int(value)
    except Exception:
        return 0


def compute_scores(video):
    stats = video.get("statistics", {})
    snippet = video.get("snippet", {})

    views = parse_int(stats.get("viewCount"))
    likes = parse_int(stats.get("likeCount"))
    comments = parse_int(stats.get("commentCount"))

    published_at = datetime.fromisoformat(
        snippet["publishedAt"].replace("Z", "+00:00")
    )

    now = datetime.now(timezone.utc)
    age_days = max((now - published_at).total_seconds() / 86400, 1)

    views_per_day = views / age_days

    viral_score = (
        math.log10(views + 1)
        + 0.35 * math.log10(comments + 1)
        + 0.20 * math.log10(likes + 1)
        - 0.15 * math.log10(age_days + 1)
    )

    return views, likes, comments, published_at, views_per_day, viral_score


def compute_link_intent_score(title, description):
    text = f"{title} {description}".lower()

    score = 0

    for term in DESCRIPTION_LINK_TERMS:
        if term.lower() in text:
            score += 3

    url_count = text.count("http://") + text.count("https://")
    score += min(url_count, 20)

    if "amzn.to" in text:
        score += 5

    if "amazon.com" in text:
        score += 4

    if "bit.ly" in text or "goo.gl" in text or "tinyurl" in text:
        score += 2

    return score


def looks_like_product_review(title, description):
    text = f"{title} {description}".lower()

    review_hits = [
        "review",
        "unboxing",
        "hands on",
        "first impressions",
        "worth it",
        "comparison",
        " vs ",
        "versus",
        "setup",
        "gear",
        "kit",
        "best",
        "budget",
        "beginner",
    ]

    product_hits = [
        "camera",
        "microphone",
        "podcast",
        "streaming",
        "youtube",
        "tripod",
        "lighting",
        "gaming",
        "keyboard",
        "mouse",
        "headset",
        "headphones",
        "earbuds",
        "speaker",
        "coffee",
        "air fryer",
        "robot vacuum",
        "smart home",
        "security camera",
        "fitness",
        "home gym",
        "bike",
        "cycling",
        "camping",
        "laptop",
        "smartwatch",
        "drone",
        "iphone",
        "phone",
        "accessories",
        "gear",
    ]

    return any(x in text for x in review_hits) and any(x in text for x in product_hits)


# =============================================================================
# UPSERT
# =============================================================================

def upsert_videos(videos, query_source):
    rows = []

    for video in videos:
        snippet = video.get("snippet", {})
        details = video.get("contentDetails", {})

        title = snippet.get("title", "")
        description = snippet.get("description", "")

        views, likes, comments, published_at, views_per_day, viral_score = compute_scores(video)
        link_intent_score = compute_link_intent_score(title, description)

        if views < MIN_VIEWS:
            continue

        if not looks_like_product_review(title, description):
            continue

        video_id = video["id"]

        rows.append((
            video_id,
            title,
            description,
            snippet.get("channelId"),
            snippet.get("channelTitle"),
            published_at,
            views,
            likes,
            comments,
            details.get("duration"),
            query_source,
            f"https://www.youtube.com/watch?v={video_id}",
            views_per_day,
            viral_score,
            link_intent_score,
            psycopg2.extras.Json(video),
        ))

    if not rows:
        return 0

    sql = """
	INSERT INTO youtube_product_review_videos (
	    video_id,
	    title,
	    description,
	    channel_id,
	    channel_title,
	    published_at,
	    view_count,
	    like_count,
	    comment_count,
	    duration,
	    query_source,
	    url,
	    views_per_day,
	    viral_score,
	    link_intent_score,
	    raw_json
	)
    VALUES %s
    ON CONFLICT (video_id) DO UPDATE SET
        title = EXCLUDED.title,
        description = EXCLUDED.description,
        channel_id = EXCLUDED.channel_id,
        channel_title = EXCLUDED.channel_title,
        published_at = EXCLUDED.published_at,
        view_count = EXCLUDED.view_count,
        like_count = EXCLUDED.like_count,
        comment_count = EXCLUDED.comment_count,
        duration = EXCLUDED.duration,
        query_source =
            CASE
                WHEN youtube_product_review_videos.query_source IS NULL
                    THEN EXCLUDED.query_source
                WHEN youtube_product_review_videos.query_source = EXCLUDED.query_source
                    THEN youtube_product_review_videos.query_source
                ELSE youtube_product_review_videos.query_source || '; ' || EXCLUDED.query_source
            END,
        url = EXCLUDED.url,
        views_per_day = EXCLUDED.views_per_day,
        viral_score = EXCLUDED.viral_score,
        link_intent_score = EXCLUDED.link_intent_score,
        raw_json = EXCLUDED.raw_json,
        updated_at = NOW();
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, rows)

    return len(rows)


# =============================================================================
# MAIN
# =============================================================================

def main():
    if not API_KEY:
        raise RuntimeError("Missing YOUTUBE_API_KEY in .env")

    print("\nRunning database setup and self-test before using YouTube quota...")
    init_db()
    test_db_upsert()

    queries = [
        f"{product_term} {review_term}"
        for review_term in REVIEW_TERMS
        for product_term in PRODUCT_TERMS
    ]

    estimated_search_units = estimate_search_cost(
        len(queries),
        MAX_PAGES_PER_QUERY
    )

    print("\n=== YouTube Viral Product Review Collector ===")
    print(f"Upload date range: {START_DATE} to {END_DATE}")
    print(f"Minimum current views: {MIN_VIEWS:,}")
    print(f"Queries planned: {len(queries):,}")
    print(f"Max search pages per query: {MAX_PAGES_PER_QUERY}")
    print(f"Potential search quota if fully run: {estimated_search_units:,} units")
    print(f"Daily quota budget: {DAILY_QUOTA_BUDGET:,} units")
    print("\nNote: YouTube search calls are expensive; video detail calls are cheap.")

    decision = ask_continue("Start collection?")
    if decision != "yes":
        print("Stopped before starting.")
        return

    seen_ids = set()

    for i, query in enumerate(queries, start=1):
        planned_search_cost = MAX_PAGES_PER_QUERY * SEARCH_COST

        print("\n" + "=" * 72)
        print(f"[{i}/{len(queries)}] Query: {query}")
        print(f"Estimated quota used so far: {quota_used_estimate:,}")
        print(f"Planned max search cost for this query: {planned_search_cost:,}")

        if i == 1 or (i - 1) % CHECKPOINT_EVERY_QUERIES == 0:
            decision = ask_continue(
                f"About to run query batch starting with:\n  {query}"
            )

            if decision == "quit":
                print("Stopped by user.")
                return

            if decision == "skip":
                print("Skipping this query.")
                continue

        if not quota_guard(planned_search_cost):
            print(f"Skipped query due to quota guard: {query}")
            continue

        try:
            ids, pages_used = search_video_ids(
                query,
                max_pages=MAX_PAGES_PER_QUERY
            )

            actual_search_cost = pages_used * SEARCH_COST
            spend_quota(actual_search_cost)

            print(f"Search pages used: {pages_used}")
            print(f"Actual search quota estimate: {actual_search_cost:,}")

        except Exception as e:
            print(f"Search failed for query '{query}': {e}")
            continue

        new_ids = [vid for vid in ids if vid not in seen_ids]
        seen_ids.update(new_ids)

        video_lookup_cost = estimate_video_cost(len(new_ids))

        print(f"Found video IDs: {len(ids):,}")
        print(f"New video IDs: {len(new_ids):,}")
        print(f"Estimated detail lookup cost: {video_lookup_cost:,}")
        print(f"Projected quota after details: {quota_used_estimate + video_lookup_cost:,}")

        if not new_ids:
            continue

        if not quota_guard(video_lookup_cost):
            print("Skipped detail lookup due to quota guard.")
            continue

        decision = ask_continue(
            f"Fetch details for {len(new_ids):,} new videos?"
        )

        if decision == "quit":
            print("Stopped by user.")
            return

        if decision == "skip":
            print("Skipped detail lookup.")
            continue

        try:
            videos = fetch_video_details(new_ids)
            spend_quota(video_lookup_cost)

            saved = upsert_videos(videos, query)

            print(f"Videos returned by details endpoint: {len(videos):,}")
            print(f"Saved/updated matching videos: {saved:,}")
            print(f"Estimated quota used so far: {quota_used_estimate:,}")

        except Exception as e:
            print(f"Detail/upsert failed for query '{query}': {e}")

        time.sleep(0.2)

    print("\nDone.")
    print(f"Estimated quota used: {quota_used_estimate:,}")


if __name__ == "__main__":
    main()