# Design: Media Tracker (personal Yamtrack fork)

> ## ⚠️ PIVOT (2026-06-16) — this design is partly SUPERSEDED
>
> The current source of truth is **[CLAUDE.md](../CLAUDE.md)** and the enhancement list in
> **[BACKLOG.md](BACKLOG.md)**. The original "from-scratch, open-source, two-mode" design
> below is kept as a **historical record**. What changed:
>
> 1. **Fork Yamtrack, don't rebuild from scratch.** Stay merge-able with upstream.
> 2. **Private, personal-use only** — not open-source, not distributed.
> 3. **Web-content half (articles / YouTube) is DROPPED** — Obsidian handles that.
> 4. **Manga/comics/books/board games are hidden via a settings toggle**, not built out.
>
> The build order, "two modes," open-source distribution, and web-content sections below no
> longer apply. The data-model split, provider list, and Crunchyroll work are still relevant
> and carry into the fork.

## Crunchyroll — verified portable (2026-06-16)

v1's reverse-engineered CR sync was live-tested with a fresh bearer token. **Every endpoint
returned HTTP 200 with the JSON shapes v1 parses** — the integration has not rotted and is
portable to the fork (backlog item E9).

Endpoints (all require an `Authorization: Bearer` token; v1 uses manual paste, ~3-min
validity):

| Endpoint | Used for | v1 parse path |
|---|---|---|
| `GET /accounts/v1/me` | account_id | `.account_id` |
| `GET /content/v2/discover/browse?n=...&sort_by=alphabetical` | full catalog | `data[].type` / `.id` / `.series_metadata.audio_locales` / `.subtitle_locales` |
| `GET /content/v2/cms/series/{id}` | direct dub/sub lookup | `.data[0].audio_locales` (**top-level**, not nested — see nuance) |
| `GET /content/v2/discover/{acct}/watchlist?order=desc&n=...` | status sync | `.panel.episode_metadata.series_id` (or `.panel.movie_metadata.movie_listing_id`) |
| `GET /content/v2/{acct}/watch-history?page_size=...` | S/E progress | `.panel.episode_metadata.series_id` / `.season_number` / `.episode_number` |
| `POST /auth/v1/token` | OAuth token mint (alive; client-creds) | — |

**Shape nuance:** `cms/series/{id}` returns locales at the **top level** (`.audio_locales`),
while `discover/browse` nests them under `.series_metadata.audio_locales`. v1 handles both
via a fallback chain — preserve that when porting.

Source: v1 Apps Script at `../Media Tracker v1/gas/` (`Crunchy_Code.gs`,
`Crunchy_Global_var.gs`, `Crunchy_Diagnostics.gs`). Worth porting alongside: the language
map and studio-normalization map in `Crunchy_Global_var.gs`.

---

## Historical design (pre-pivot, 2026-06-14) — for reference only

Status: APPROVED (2026-06-14), later superseded by the 2026-06-16 pivot above.
Origin: a `/office-hours` design session. The full session artifact lives in the
maintainer's local gstack store.

## Problem

v1 is a Google Sheet + ~150KB of Apps Script that tracks anime, TV, and movies (metadata
from Jikan/TMDB/Gemini, plus a reverse-engineered Crunchyroll sync). It works but is tied
to Google Sheets, slow, awkward (modal dialogs over a spreadsheet), and hard to share.

v2 is a from-scratch, self-hostable web app. North star: **Yamtrack**
(https://github.com/FuzzyGrim/Yamtrack), extended with a content-saving half Yamtrack
lacks.

## The product: a personal media + content hub

One place for "stuff I've consumed or want to consume." Two modes under one roof:

1. **Catalog media** — anime, TV, movies, manga/comics, books, video games. Rich metadata
   from databases (TMDB, Jikan/AniList, Open Library/Google Books, IGDB/RAWG). Tracked by
   status, progress, rating, notes.
2. **Web content** — articles, YouTube/TikTok videos. Arbitrary URLs, no central catalog;
   metadata scraped from the page (Open Graph, oEmbed). Save it, categorize it, mark
   read/watched. (Pocket / Raindrop territory.)

## Scope decisions

| Decision | Choice |
|---|---|
| Goal | Open-source, self-hostable by others |
| Media types | Anime, TV, Movies, Manga/comics, Books, Video games, Articles, Web videos |
| Auto-tracking | "Auto-everything" (Crunchyroll + Plex/Jellyfin/Trakt + metadata refresh) — phased |
| Users | Single-user now; every table carries `user_id` (multi-user is a later add, not a rewrite) |
| Web-content capture | Paste-URL first; mobile share-sheet later |
| Migration | Import v1 personal layer; re-fetch catalog metadata; fall back to sheet values on miss |

## Principles (agreed)

1. One app, two modes (shared library/tags/status; different add-flows and fields).
2. The core win is killing the Google Sheet. Everything else builds on that.
3. Auto-everything is the destination, not the first release. Manual core ships first.
4. Crunchyroll sync is a maintenance commitment (unofficial API). Keep it only because CR
   is the maintainer's main anime source.
5. The stack must allow always-on background jobs (rules out pure serverless for sync).
6. "Done" includes distribution: Docker image + README + one-command setup.

## Stack (decided: the Yamtrack path)

**Django + Postgres + Tailwind (+ HTMX) + Celery/Redis + Docker Compose.** Chosen so the
hardest parts (episode/chapter models, importers, Plex/Jellyfin sync, calendar,
notifications) can be adapted from Yamtrack's source in the same framework. Django admin
gives a working data backend immediately; Celery is the proven periodic-sync pattern.

(Alternatives considered: a Next.js/TypeScript monolith, and a Vercel-frontend +
decoupled-sync-service split. The deciding factor was de-risking solo-dev completion by
leaning on Yamtrack's existing solutions.)

## Architecture (intended)

- **Web:** Django + Tailwind, HTMX for interactivity.
- **DB:** Postgres (SQLite OK for the first local spike).
- **Jobs:** Celery + Redis (beat schedule) for periodic sync + metadata refresh.
- **Data model:** base item with a `media_type` discriminator + per-type detail tables.
  Keep the personal layer (status/rating/progress/notes/dates) separate from catalog
  metadata so metadata re-fetch never touches user data. Every row carries `user_id`.
- **Catalog providers:** pluggable interface (TMDB, Jikan/AniList, Open Library/Google
  Books, IGDB/RAWG). New media type = new provider + detail model.
- **Web-content ingestion:** URL → fetch → parse Open Graph / oEmbed → save title,
  thumbnail, author, source. Custom Django app; no external catalog.
- **Integrations (phased, optional, independently toggleable):** Crunchyroll (verify
  endpoints first, then port v1 logic) → Plex/Jellyfin/Emby → Trakt. One breakage must not
  sink the app.
- **Importer:** one-time job reading the v1 Google Sheet (CSV export or Sheets API) →
  brings over the personal layer → enriches via the catalog providers.

## Build order

1. Spike: Django + Postgres + Tailwind in Docker Compose; one item model; admin visible.
2. Catalog core, one type first (anime via Jikan + TMDB; port v1 fetch + normalization).
3. Personal-layer / metadata split in the schema.
4. v1 importer.
5. Web-content mode (paste-URL → scrape → save + categorize).
6. Expand catalog types (TV/movies, then manga, books, games).
7. Celery + periodic metadata refresh (first "auto" piece).
8. Integrations, phased: Crunchyroll → Plex/Jellyfin → Trakt.
9. Polish + distribution: README, Docker image, GitHub Actions, live instance.
10. Roadmap: mobile share-sheet capture, multi-user accounts.

Steps 1–5 = the "kill the Google Sheet" milestone. Step 6 onward = "auto-everything."

## Hosting & distribution

- Self-host artifact: Docker image + `docker-compose.yml` in this repo.
- Maintainer's live instance: a free always-on host (Railway / Render / Fly). Sync needs a
  process that stays running.
- Vercel is serverless (no always-on worker) — fine for a future static landing page only,
  not the app.
- CI/CD: GitHub Actions (tests on PR, build + publish image on tagged release).
- Repo: PRIVATE during development; PUBLIC at launch.

## Success criteria

- `docker compose up` with a documented `.env`; no Google account required.
- A new self-hoster can stand up a working instance from the README in ~15 minutes.
- The maintainer's v1 data (anime/TV/movies personal layer) is imported and visible.
- Add a catalog item (search → pick → save) and save a web link (paste → auto-title →
  categorize) both work end-to-end.
- Faster and less fiddly than the v1 Sheet + dialog flow.

## Open questions

- Final name (and committing to "Media Consumerus" + walrus branding).
- Which media types ship in the very first release vs. follow-on (likely anime/TV/movies
  first, given v1).
- HTMX vs. a heavier JS frontend within Django (decide at the first UI spike).
- Simplest single-user auth (Django built-in is fine).
- Crunchyroll viability: do the v1 endpoints still work today?
