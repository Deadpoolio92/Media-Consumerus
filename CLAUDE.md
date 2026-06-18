# CLAUDE.md — Media Tracker (personal Yamtrack fork)

A **private, personal** media tracker. This file guides Claude Code and any AI agent
working in this repo.

## What this is

A self-hosted **personal media tracker** for "stuff I've consumed or want to consume":
anime, TV, movies, and video games. It is built as a **fork of
[Yamtrack](https://github.com/FuzzyGrim/Yamtrack)** (an open-source Django media tracker on
exactly the stack we'd have chosen anyway), enhanced to fill the gaps the maintainer's old
v1 Google-Sheet tracker had.

**This is the v2 pivot (2026-06-16).** v1 was a Google Sheet + ~150KB of Apps Script. The
original v2 plan was a from-scratch rewrite, open-source, with a web-content half (saving
articles / YouTube links). All three of those are now **reversed**:

- **Fork, don't rebuild.** Yamtrack already nails the catalog-tracking 80% on our stack.
  We fork it and spend effort only on our missing 20%.
- **Private, personal-use only.** Not open-source, not distributed. (Yamtrack has ~3k
  stars; recognition upside is low and the maintainer only needs it for himself. Going
  public later is still possible — see License note.)
- **No web-content half.** Articles / YouTube / TikTok are **dropped**; the maintainer uses
  Obsidian vaults for that, which suits it better.

The enhancement requirements come from a hands-on Yamtrack evaluation (the match/beat/cut
table). The full prioritized list is in **[planning/BACKLOG.md](planning/BACKLOG.md)**.

## Status

**This IS the fork — Yamtrack cloned and running locally.** This repo is the cloned
Yamtrack fork (`origin` = `https://github.com/Deadpoolio92/Media-Consumerus.git`, default
branch `dev`; `upstream` = `FuzzyGrim/Yamtrack`, push-disabled). The planning docs from the
old scratch repo now live here in [planning/](planning/). Yamtrack's own files (`src/`,
`docs/`, `README.md`, `LICENSE`, `docker-compose*.yml`) are upstream's — leave them
untouched (see Fork strategy). No enhancement code written yet, but stock Yamtrack now runs
locally at http://localhost:8000.

**Local run (merge-safe).** Config lives in a git-ignored `docker-compose.override.yml`
(via `.git/info/exclude`, so it never touches the tracked compose file). It builds from the
local `Dockerfile` (image `media-consumerus:local`, NOT the published ghcr image — so `src/`
changes actually run), and sets `SECRET`, `TMDB_API`, `REGISTRATION`, `ADMIN_ENABLED` inline
(no separate `.env`). Run: `docker compose up -d --build`. Note: after registering your
account, set `REGISTRATION=False` in the override and re-up to lock it to you. Optional
provider keys (IGDB for games) are omitted so Yamtrack's bundled defaults apply.

**Windows gotcha (fixed, committed):** a `.gitattributes` forces LF on `*.sh`/`*.conf`/
`entrypoint.sh`/`Dockerfile`. Without it, `core.autocrlf=true` checks them out as CRLF and
the container crash-loops with `exec /entrypoint.sh: no such file or directory`. If new
shell/conf files are added later, make sure they end up LF.

**Verified asset:** v1's reverse-engineered Crunchyroll sync was live-tested on 2026-06-16
and **still works** — every endpoint returns 200 with the JSON shapes v1 parses. The CR
logic is portable to the fork as-is. See [planning/DESIGN.md](planning/DESIGN.md) →
"Crunchyroll" for the endpoint list and the one shape nuance (cms/series returns locales
top-level, not nested).

### ▶ Resume here (next session)

The pivot is locked (fork Yamtrack, stay merge-able, private). The planning docs are in
this fork and stock Yamtrack runs locally. Open next steps:

1. **Register + load data** — open http://localhost:8000, create your account, then set
   `REGISTRATION=False` in `docker-compose.override.yml` and `docker compose up -d` to lock
   it down. Add a few items across types so the UI has real data to evaluate.
2. **Run the Yamtrack eval** — the maintainer still owes the hands-on ~30-min pass to
   confirm/refine the backlog (checklist already produced; results feed
   [planning/BACKLOG.md](planning/BACKLOG.md)).
3. **`/plan-eng-review`** — turn [planning/BACKLOG.md](planning/BACKLOG.md) into concrete,
   merge-able Django changes (new apps / fields / settings flags), starting with the
   highest-value, lowest-merge-risk P0 items (dub/sub field E1, list filters E2,
   hide-types toggle E3, re-watching status E4). **Before E4**, check `upstream/dev` for
   the `harshil/fix-rewatch-tracking` work — may land upstream (see BACKLOG E4).

v1 (the Google Sheet + Apps Script) lives at `../Media Tracker v1`. It is the source for
the personal-data import (transform v1 export → Yamtrack CSV import format).

## Product scope (post-pivot)

| Decision | Choice |
|---|---|
| Goal | **Private, personal-use only.** Fork Yamtrack; enhance the gaps. Not open-source, not distributed. |
| Base | Fork of `FuzzyGrim/Yamtrack`, kept **merge-able with upstream** (see Fork strategy). |
| Media types used | **Anime, TV, Movies, Video games.** Manga/comics, Books, Board games = **hidden via a settings toggle** (kept in code, not built out, not deleted). |
| Web content | **Dropped.** Articles / YouTube / TikTok live in Obsidian instead. |
| Auto-tracking | Keep Yamtrack's integrations (Plex/Jellyfin/Emby, Trakt). Add the verified Crunchyroll sync (port v1). Each independently toggleable. |
| Users | Single-user. Keep Yamtrack's multi-user model as-is (no change needed). |
| Migration | Import v1's personal layer (status/rating/progress/notes/dates/dub-sub) by transforming the v1 export into Yamtrack's CSV import. |

## Fork strategy — STAY MERGE-ABLE with upstream

**This is the load-bearing engineering constraint.** The maintainer is solo; staying close
to upstream means inheriting Yamtrack's bug fixes, new providers, and features for free.
Every change must be made with "can I still pull upstream?" in mind.

- **Additive over invasive.** Prefer new Django apps, new model fields (additive
  migrations), new templates/partials, and settings flags over editing Yamtrack's core
  files. Touch core only when there's no additive path.
- **Hide, don't delete.** Unwanted media types (manga/books/board games) become a
  **settings toggle** that hides them from nav/search/calendar — never a code deletion.
  Deletions cause merge conflicts on every upstream pull.
- **Upstream remote.** Add Yamtrack as an `upstream` git remote; pull + merge periodically.
  Keep our work on top so conflicts stay small and legible.
- **Isolate bespoke features.** Streaming-provider links, game license/coupon fields,
  cross-category search, dub/sub — build as self-contained modules where possible so an
  upstream merge rarely collides with them.
- When a change would force a big core edit, **flag it** and weigh it against the merge cost
  before doing it.

## Tech stack (inherited from Yamtrack)

**Django + Postgres + Tailwind (+ HTMX) + Celery/Redis + Docker Compose.** This is
Yamtrack's stack and exactly what v2 had independently chosen — forking costs nothing
technically. Django admin gives a working data backend; Celery handles periodic sync.

**Catalog providers (Yamtrack's, confirmed):** TMDB (TV/movies), MyAnimeList **or** AniList
(anime/manga), IGDB (games), OpenLibrary / Hardcover (books). Our cross-category search
enhancement fans out across these and merges results.

## The enhancement backlog

The "what to build on top of Yamtrack" list lives in **[planning/BACKLOG.md](planning/BACKLOG.md)**,
derived from the match/beat/cut evaluation and ordered by value vs. merge-risk. Highlights:
dub/sub tracking, streaming-provider links (per-title via TMDB watch-providers + CR link
for anime — per-episode multi-provider is **not** available from public APIs), game
install-links/licenses/coupons, cross-category search, calendar filtering + speed, and
list filters (rating / language / genre / year).

## Hosting

Self-hosted for the maintainer only via Docker Compose (local machine or a personal
always-on host). **No public distribution, no published image, no landing page, no GHCR
release.** Keep secrets (TMDB, etc.) in `.env`; never commit. Keep a checked-in
`.env.example`.

## License (since "recognition" came up)

For **private personal use there are zero license obligations** — copyleft only triggers on
distribution. If the fork is ever published, Yamtrack's license (copyleft OSS) must be
honored (share source). Forking privately now does not burn the option to publish later.

## Conventions

- **Secrets:** all keys in `.env`; never commit. Maintain `.env.example`.
- **Commits:** small, logically separated, present-tense summary; one concern per commit.
- **Branches:** feature branches off `main`; open a PR to merge.
- **Fork hygiene:** keep an `upstream` remote; favor additive changes; don't delete upstream
  features (hide them). See Fork strategy.
- **Heads-up:** this working copy lives inside a Google Drive folder. Let git own the
  `.git` directory; avoid editing files while Drive is mid-sync to prevent conflict copies.

## gstack

This project uses **gstack**. Use the **`/browse`** skill for all web browsing; do **not**
use `mcp__claude-in-chrome__*` tools. Skills, in sprint order
(Think → Plan → Build → Review → Test → Ship → Reflect):

- **Think:** `/office-hours`, `/spec`
- **Plan:** `/plan-ceo-review`, `/plan-eng-review`, `/plan-design-review`,
  `/design-consultation`, `/autoplan`
- **Build:** `/codex`, `/investigate`
- **Review:** `/review`, `/code-review`, `/design-review`, `/cso`
- **Test:** `/qa`, `/qa-only`, `/verify`
- **Ship:** `/ship`, `/land-and-deploy`, `/canary`, `/benchmark`
- **Reflect:** `/retro`, `/learn`, `/document-release`, `/document-generate`

gstack is installed globally at `~/.claude/skills/gstack` and auto-updates; nothing is
checked into this repo.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in
doubt, invoke the skill.

- Product ideas / brainstorming → `/office-hours`
- Strategy / scope → `/plan-ceo-review`
- Architecture → `/plan-eng-review`
- Design system / plan review → `/design-consultation` or `/plan-design-review`
- Full review pipeline → `/autoplan`
- Bugs / errors → `/investigate`
- QA / testing site behavior → `/qa` or `/qa-only`
- Code review / diff check → `/review`
- Visual polish → `/design-review`
- Ship / deploy / PR → `/ship` or `/land-and-deploy`
- Author a backlog-ready spec/issue → `/spec`
