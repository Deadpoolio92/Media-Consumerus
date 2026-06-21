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
locally at <http://localhost:8000>.

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

The pivot is locked (fork Yamtrack, stay merge-able, private). Stock Yamtrack runs locally.
Build order (locked, design doc Approach A): **E3 → E1 → E2 → E10 → E9 → polish → E8.**

**▶ NEXT EPIC = E9 (Crunchyroll sync).** E3/E1/E2/E10 are all done; the v1 personal library
is imported and LIVE (see E10 below). E9 = port v1's verified Crunchyroll sync as a new
self-contained integration module. Sources to port: `../Media Tracker v1/gas/Crunchy_*.gs`;
endpoint list + the one shape nuance in [planning/DESIGN.md](planning/DESIGN.md) →
"Crunchyroll"; scope/approach in [planning/BACKLOG.md](planning/BACKLOG.md) (E9). The E9 plan
doc now EXISTS: **[planning/E9-crunchyroll-plan.md](planning/E9-crunchyroll-plan.md)** (DRAFT) —
blocked on **three maintainer decisions** before `/plan-eng-review`: (1) **auth model** —
manual bearer-token paste (one-shot importer only) vs. `etp_rt`-cookie/device flow (enables an
unattended daily beat); (2) **capability scope** — which of C1 dub/sub→E1 / C2 watchlist→status /
C3 history→progress / C4 upload to port; (3) **catalog breadth** — library-only sync vs. ingest
the full ~1500-title CR browse catalog. Core design challenge documented in the plan: CR uses its
own series-id namespace, but the fork keys anime by MAL id — needs a CR-code→MAL-id resolver
(E10's `out/resolved.json` gives a ~318-title seed map; Jikan title-search fallback for new ones).

**Done / planned:**

- **E3 (hide unused media types) — RESOLVED config-only (2026-06-18).** Upstream already ships
  per-user `{type}_enabled` flags + a Preferences UI honored across nav/search/calendar/stats.
  No code needed: untick manga/comic/book/boardgame in Preferences. (See decision-log.)
- **E1 (dub/sub) — ✅ COMPLETE (all T1–T7 done 2026-06-20).** Full spec:
  **[planning/E1-dub-sub-plan.md](planning/E1-dub-sub-plan.md)** (per-task DONE notes recorded
  there). Scope is *availability* tracking: `AnimeAvailability` model (OneToOne→`Item`, JSON
  locale-code lists), manual entry + **MyDubList** auto-fill (daily Celery task + async
  on-add), last-write-wins, shared `app/languages.py` map.
  - **Done:** **T1** `AnimeAvailability` model + migration `0062` + admin · **T2**
    `app/languages.py` (faithful 26-entry port of v1 `LANGUAGES`, code↔display helpers) ·
    **T3** manual entry (`AnimeForm` save-override upserts on change only; `views.py` badge
    context key; "AVAILABILITY" card in `media_details.html`; `locale_display` filter in NEW
    `app/templatetags/availability_tags.py`) · **T4** `app/providers/mydublist.py`
    (fetch+invert+normalize+match) · **T5** daily Celery beat sync (`tasks.py`
    `sync_dub_availability` + `apply_mydublist_locales` helper; `settings.py`
    `MYDUBLIST_CONFIDENCE` + beat entry; 6 task tests) · **T6** on-add fetch (`tasks.py`
    `fetch_one_availability` + `signals.py` `post_save(Anime)` enqueue, best-effort;
    CC BY attribution badge wired via `mydublist_credit` tag; `tests/conftest.py` autouse
    stub; 7 task/signal tests) · **T7** full test sweep (NEW `tests/providers/test_mydublist.py`
    18 mocked-network tests + tag/form/badge/E2-readiness gaps; 87 pass on the E1 surface,
    714 collect clean). **T1–T3 unblock the E10 import** (fields exist end-to-end).
    All additive; no upstream core model/file edited except an additive context key + the
    anime badge card + a `post_save(Anime)` signal; `mydublist.py` is a standalone module
    (not wired into `services.py`).
  - **T4 schema finding (verified 2026-06-20):** MyDubList is NOT one JSON keyed by MAL id —
    it's **inverted/split**: `dubs/confidence/<tier>/dubbed_<lang>.json` (tiers
    low/normal/high/very-high; 27 lowercase lang NAMES; shape `{dubbed:[mal_id…],
    partial:[mal_id…]}`). Values are MAL ids (no AniList id-map needed). Maintainer chose:
    tier `high` (configurable `MYDUBLIST_CONFIDENCE`), region-collapsed → es-419/pt-BR/zh-CN,
    include all 27 langs, merge `partial` as available. `fetch_dataset` inverts → `{str(mal_id):
    [codes]}` (11,847 titles @ high). **CC BY 4.0 requires the `mydublist.ATTRIBUTION` credit
    line in the badge UI** (TODO, fold into T5/T6).
  - **E1 fully shipped (T1–T7).** Availability tracking is end-to-end: model + manual entry
    - MyDubList auto-fill (daily Celery beat + best-effort on-add signal) + badge with CC BY
    credit, all tested (87 on the E1 surface; provider tests fully offline). E1 fully shipped and merged, but not yet exercised against a live
    Celery worker / Postgres (only the pytest SQLite suite + a live MyDubList fetch smoke
    test). Daily beat runs `crontab(hour=4)`; tune `MYDUBLIST_CONFIDENCE` if coverage feels
    thin.
- **E2 (list filters) — ✅ COMPLETE (all T1–T6 done 2026-06-20).**
  Full spec + per-task DONE notes: **[planning/E2-list-filters-plan.md](planning/E2-list-filters-plan.md)**.
  Adds rating / language / genre / year filters to the per-type list view.
  - **Key finding (baked into the plan):** genre + year are NOT in the DB (only in live
    provider metadata). Maintainer chose to **denormalize** them: NEW `ItemMetadata`
    (OneToOne→`Item`, a sibling of `AnimeAvailability`; migration `0063`), populated from the
    catalog provider via `app/metadata_fields.py` + `tasks.py`
    (`fetch_one_metadata` on-add signal on Movie/TV/Season/Anime/Game +
    `sync_catalog_metadata` daily beat `crontab(4:30)`, which doubles as the backfill).
  - **Filters:** rating (`score__gte`/unrated) + year (`release_year`) in SQL;
    genre + language **in Python** (`_apply_python_filters`) to dodge the JSONField
    `__contains` SQLite caveat — so the whole suite stays green on SQLite. Choices via
    `MediaManager.get_filter_options`; language is anime-only (reads E1's `AnimeAvailability`,
    labelled via `app/languages.py`) and hidden until data exists. Filters are **ephemeral
    query params** (no User-model migration). UI: NEW `templates/app/components/
    list_filter_dropdown.html` + Alpine wiring in `media_list.html`.
  - **Tested:** 86 on the E2 surface (NEW `test_metadata_fields.py`,
    `test_media_manager_filters.py`; +classes in `test_tasks.py`; +2 view tests). `ruff`
    clean on E2 files; `djlint` clean on both templates; `makemigrations --check` clean.
    Not yet committed (awaiting go-ahead); not yet run against a live Celery worker / Postgres
    (SQLite pytest only). **Run `sync_catalog_metadata` once after deploy to backfill** existing
    items' genre/year. (Pre-existing/env-only suite fails: `test_integration.py` allauth
    client-IP, `test_metadata::test_book` live network — both unmodified by E2.)
  - **Next per build order (E3→E1→E2→E10→E9→polish→E8): E10 (v1 personal-data import).** E1's
    T1–T3 *and* E2's `ItemMetadata` both land into a real, filterable library now.
  - **Dev env:** local `uv` venv is set up (`uv sync --group test`); run Django/pytest via
    `uv run` from `src/` with `DJANGO_SETTINGS_MODULE=config.test_settings` (SQLite). Docker
    Desktop was not running this session.
- **E10 (v1 data import) — ✅ COMPLETE; import is LIVE (T1–T8, 2026-06-21).** Full
  spec + per-task notes: **[planning/E10-import-plan.md](planning/E10-import-plan.md)**;
  runbook: **[planning/e10-import/README.md](planning/e10-import/README.md)**. Standalone
  script tree under [planning/e10-import/](planning/e10-import/) (**zero `src/` edits**); the
  load reuses Yamtrack's unmodified CSV importer.
  - **Maintainer decisions:** sheet via public-link `/browse` fetch · pre-resolve + review
    report · full-fidelity (episode-level) expansion · **personal library only** (drop the
    ~1,195 blank-status CR-catalog anime; keep status-bearing + the 39 progressed-but-blank
    as In progress).
  - **Pipeline:** `parse.py` (T2) → `resolve.py` (T3, Jikan→MAL + TMDB, cached/throttled,
    confidence + `overrides.csv`) → `expand.py` (T4) → `transform.py` (T5,
    `out/yamtrack_import.csv` + `out/review_report.md`) → `dryrun.py` (T6) + `load_dubsub.py`
    (T7, seeds E1 `AnimeAvailability`). **446 records → 2,147 rows** (435 high/5 med/5 low/1
    override, 0 unmatched; 16 multi-season anime flagged). Validated through the **real
    `YamtrackImporter`** on throwaway SQLite (full season/episode FK linking). **35 offline
    tests pass** (`.venv/Scripts/python -m pytest` from `planning/e10-import/`; local
    `pytest.ini` disables pytest-django).
  - **Executed live (2026-06-21):** ran the real `YamtrackImporter` in-container for user
    `Deadpoolio` (mode *new*; DB backed up to `db/_pre_e10_backup_*`). **Imported movie 95 /
    anime 318 / tv 32 / season 99 / episode 1602, 0 warnings**; seeded **310 `AnimeAvailability`**
    dub/sub rows. Verified counts + Lethal Weapon S1 18/18, S2 20/20 + Trigun Stampede
    (Completed, 7.0, dubs). `overrides.csv` fixes Code Geass→1575, Dragon Raja→44408, So I'm a
    Spider→37984; Dragon Ball Movies excluded (catch-all). Everything stays local/uncommitted
    (planning/ is gitignored). Library was empty pre-import.
  - **Next epic per build order: E9 (Crunchyroll sync).**
- **Title/UX polish — ✅ SHIPPED + MERGED (2026-06-21, PR #4 → `dev`).** Ad-hoc UX fixes (not
  an epic), prompted by the maintainer after E10 made the library browsable. (1) **English
  anime titles:** MAL's canonical `title` is romaji/native (e.g. "Shingeki no Kyojin"); new
  `mal.get_title()` ([src/app/providers/mal.py](src/app/providers/mal.py)) prefers
  `alternative_titles.en` (falls back when MAL has none), applied to anime/manga **detail +
  search + related/recommendations** (the last via nested `…{node{title,alternative_titles}}`
  field expansion). Gated by `MAL_PREFER_ENGLISH_TITLE` (settings, default `True`, toggleable
  like `MAL_NSFW`). (2) **Backfill command:** `python manage.py backfill_mal_titles`
  (`--dry-run`/`--sleep`; NEW additive `app/management/` tree) rewrites already-stored
  `Item.title` rows — **run live: 326/420 anime titles updated, 0 failed** (94 have no distinct
  English title and keep romaji). (3) **Two-line cards:** `media_card.html` `line-clamp-1`→
  `line-clamp-2` + inline 2-line `min-height` (shared card → fixes both the list grid and the
  detail-page related/recs sections). 4 new offline `get_title` tests + provider/view suites
  green; `ruff`/`djlint` clean. `.gitignore`/`CLAUDE.md` deliberately kept out of PR #4.
  - **Fork gotchas learned this session (load-bearing for future work):** the local Docker
    image is **BAKED** (`build: .`, `pull_policy: build`), `src/` is **NOT** bind-mounted — any
    `src/` change needs `docker compose up -d --build` to take effect (and clear the provider
    cache via `cache.clear()` for detail-page re-fetch). The live SQLite DB is the **mounted
    `./db` volume** (survives rebuilds; back it up before data mutations — see
    `db/_pre_titles_backup_*`). Tailwind CSS is **prebuilt** (`static/css/main.css`); the image
    only runs `collectstatic`, never recompiles Tailwind, so a brand-new arbitrary/utility class
    won't exist in the CSS — reuse already-compiled classes or set the style inline (djlint H021
    is ignored project-wide). Tests run via the host `uv` venv from `src/` with
    `DJANGO_SETTINGS_MODULE=config.test_settings`, NOT in-container (the prod venv lacks pytest).

**Backlog + sequence:** [planning/BACKLOG.md](planning/BACKLOG.md). v1 (Google Sheet + Apps
Script) lives at `../Media Tracker v1` — source for the E10 personal-data import (transform
v1 export → Yamtrack CSV) and the `LANGUAGES` map E1 ports.

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

## GBrain Configuration (configured by /setup-gbrain)

- Mode: local-stdio
- Engine: pglite (`~/.gbrain/brain.pglite`, config at `~/.gbrain/config.json` mode 0600)
- Embeddings: ollama:nomic-embed-text (768d) — requires the local Ollama app running
- Setup date: 2026-06-19
- MCP registered: yes (user scope, `gbrain serve`)
- Artifacts sync: off
- Current repo policy: **read-write** (`github.com/deadpoolio92/media-consumerus`)
- Code index: this repo is imported as gbrain source `gstack-code-media-consumerus`
  (388 pages / 2363 chunks; 1 file skipped — the ~3.9MB
  `src/integrations/imports/data/kitsu-mu-mapping.json` exceeds Postgres's
  tsvector 1MB limit, not worth indexing). Refresh after code changes with
  `gbrain sync --strategy code --skip-failed` — but first stop the MCP serve
  (it holds the lock; see gotcha below), then restart Claude Code after.
- `jq` installed at `~/bin/jq.exe` (was missing; needed by `gstack-gbrain-repo-policy`)

**Windows / PGLite gotcha:** PGLite is single-writer — only one `gbrain`
process can hold the DB lock at a time. The long-lived MCP `gbrain serve` is
fine, but a leftover serve from a prior session will starve the new session's
MCP (`claude mcp list` → "✘ Failed to connect") and make CLI calls
(`gbrain doctor`/`search`/`sources list`) time out. Fix: kill stray
`gbrain serve` / `bun … cli.ts serve` processes, then `rm -rf
~/.gbrain/brain.pglite/.gbrain-lock`, then restart Claude Code. Avoid running
`gbrain` CLI commands while the MCP serve is up (they contend for the lock and
leave stale locks).

## GBrain Search Guidance (configured by /setup-gbrain)
<!-- gstack-gbrain-search-guidance:start -->

GBrain is set up and this repo's code is indexed. Prefer gbrain over Grep when
the question is semantic or you don't yet know the exact identifier. Two indexed
corpora, reachable via the `mcp__gbrain__*` tools (or the `gbrain` CLI when the
serve is stopped):

- This repo's code (source `gstack-code-media-consumerus`, 388 pages).
- The `default` brain memory (notes/plans/decisions).

Prefer gbrain when:

- "Where is X handled?" / semantic intent, no exact string yet →
  `mcp__gbrain__search` / `mcp__gbrain__query`.
- "Where is symbol Y defined / referenced?" → `code-def` / `code-refs`
  (verified working, e.g. `code-def Media` → `src/app/models.py`).
- "What calls Y? / what does Y call?" → `code-callers` / `code-callees`.
- "What did we decide / plan before?" → search the `default` source.

Grep is still right for known exact strings, regex, and file globs. Re-index
after code changes per the "Code index" note above.

<!-- gstack-gbrain-search-guidance:end -->
