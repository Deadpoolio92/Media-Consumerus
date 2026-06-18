# Enhancement Backlog — Media Tracker (Yamtrack fork)

What to build **on top of** a Yamtrack fork. Derived from the hands-on match/beat/cut
evaluation (2026-06-16). Everything here is scoped to be **additive / merge-able** with
upstream Yamtrack (see [CLAUDE.md](../CLAUDE.md) → "Fork strategy").

**Legend:** Priority = value vs. merge-risk. Effort is solo-dev with Claude Code.
Merge-risk = how likely the change collides with an upstream pull (lower is better).

## Summary

| ID | Enhancement | Priority | Effort | Merge-risk | Source |
|----|-------------|----------|--------|-----------|--------|
| E1 | Dub/Sub tracking field (anime) | **P0** | S | low | #4 |
| E2 | List filters: rating / language / genre / year | **P0** | S–M | low | #12 |
| E3 | Hide unused media types (manga/comics/books/board games) via settings toggle | **P0** | S | low | #2 |
| E4 | Add "Re-watching" status (no Yamtrack equivalent) | **P0** | S | low | #4 |
| E5 | Calendar: per-category filter + fix slowness | **P1** | M | low–med | #8 |
| E6 | Streaming-provider links (per title) | **P1** | M | low | #4 |
| E7 | Game extras: install/play links, licenses, coupons | **P1** | M | low | #3 |
| E8 | Cross-category search (fan-out + merge) | **P2** | L | medium | #5 |
| E9 | Crunchyroll sync (port v1, verified portable) | **P2** | L | low | v1 |
| E10 | v1 data import (transform sheet → Yamtrack CSV) | **P2** | M | low | #7 |

## Confirmed "Match" (no work — keep Yamtrack as-is)

Episode/season tracking (#1), metadata-vs-personal split (#6), importers framework (#7),
integrations Plex/Jellyfin/Emby + Trakt (#9), multi-user/auth (#10), self-host story (#11),
add-item flow (#13).

## Dropped (do not build)

Web content — articles / YouTube / TikTok (#14). Goes to Obsidian instead. The original v2
differentiator; intentionally cut.

---

## P0 — quick, additive, high daily value

### E1 — Dub/Sub tracking field (anime)
- **Gap:** v1 tracked Dub/Sub audio + subtitle languages per anime; Yamtrack doesn't.
- **Approach:** add `audio_locales` / `subtitle_locales` fields to the anime detail (or a
  small related model). Populate from the catalog provider; for CR-sourced anime reuse v1's
  locale data (verified live). Additive migration + template badge.
- **Note:** unblocks the language filter in E2.

### E2 — List filters: rating / language / genre / year
- **Gap:** Yamtrack's list views lack filters for rating, dub/sub language, genre, year.
- **Approach:** additive query params + filter UI partial over the existing list view.
  Language filter depends on E1. Genre/year/rating already exist in the data model.
- **Merge-risk:** low if added as a new template partial + a filter mixin rather than
  rewriting the list view.

### E3 — Hide unused media types via settings toggle
- **Gap:** maintainer won't use manga/comics/books/board games.
- **Approach:** a per-user (or global) settings flag that hides chosen media types from
  nav, search, and calendar. **Do not delete** the upstream code — hiding keeps us
  merge-able. Render-time filter on the type list.

### E4 — Add "Re-watching" status
- **Gap:** v1 had a "Re-Watching" status. **Confirmed 2026-06-16: Yamtrack has no
  equivalent** (no "Repeating" or similar). This is a real feature, not a relabel.
- **Approach:** add "Re-watching" as a new status enum value; wire it into the status
  picker, the list filters (E2), and any status-driven logic. Mirror v1's behavior:
  Completed → Re-Watching on re-entry.

## P1 — medium

### E5 — Calendar: per-category filter + speed
- **Gap:** calendar shows all categories at once, can't filter to just anime/TV, and is
  **slow**.
- **Approach:** additive category filter (keep "all" as default, add per-type views).
  **Investigate the slowness first** (`/investigate`) — likely N+1 provider fetches or
  unindexed queries; cache upcoming-episode lookups and/or add DB indexes.
- **Merge-risk:** low–med (perf fix may touch a core query — keep the diff tight).

### E6 — Streaming-provider links (per title)
- **Gap:** Yamtrack shows a "streaming" area but links nothing.
- **Realistic scope:** **per-title, per-region** "where to watch" via **TMDB watch-providers**
  (JustWatch data), plus the **Crunchyroll deep-link for anime** (v1 already builds these).
- **NOT feasible from public APIs:** per-episode, multi-provider deep links. Don't chase it.
- **Approach:** fetch + store provider availability on metadata refresh; render links on the
  detail page.

### E7 — Game extras: install/play links, licenses, coupons
- **Gap:** games need where-to-play links (Steam / EA / etc.), license keys, special coupons.
- **Approach:** additive fields on the game personal layer (a related "game extras" model is
  cleanest and most merge-safe). Treat license/coupon as personal vault data (consider not
  exporting them).

## P2 — bigger / more involved

### E8 — Cross-category search (fan-out + merge)
- **Gap:** Yamtrack search requires picking a category first (each type → a different
  provider: TMDB / MAL or AniList / IGDB / OpenLibrary).
- **Approach:** add an "all categories" mode that fans out to all providers in parallel and
  merges/ranks results, **alongside** the existing single-category search (keep both).
- **Merge-risk:** medium — touches the search flow. Build the fan-out as a wrapper over the
  existing per-provider search rather than replacing it.

### E9 — Crunchyroll sync (port v1)
- **Status:** v1's endpoints were **live-verified 2026-06-16** — all return 200 with the
  expected shapes. Logic is portable.
- **Approach:** new self-contained integration module (mirrors Yamtrack's existing
  integration pattern). Port v1's catalog/watchlist/history fetch + the dub/sub locale
  extraction. **Shape nuance:** `cms/series/{id}` returns locales at top-level
  (`.audio_locales`), while `discover/browse` nests them under `.series_metadata` — handle
  both (v1 already does).
- **Auth:** v1 uses manual bearer-token paste (~3-min validity). Decide later whether to
  keep manual-paste or implement the `etp_rt`-cookie / device-token flow.

### E10 — v1 data import
- **Gap:** maintainer's existing tracked data lives in the v1 Google Sheet.
- **Approach:** one-time transform of the v1 export (personal layer:
  status/rating/progress/notes/dates/dub-sub) into **Yamtrack's CSV import format**, then
  use Yamtrack's existing importer. Re-fetch catalog metadata via providers; fall back to
  sheet values on match miss.
- **Source:** `../Media Tracker v1` (the v1 Apps Script repo).

---

## Open items to resolve during `/plan-eng-review`

- E5: root-cause the calendar slowness before designing the fix.
- E6: confirm TMDB watch-providers coverage for the maintainer's actual anime/TV mix.
- E9: keep manual token paste vs. build the CR token flow.
