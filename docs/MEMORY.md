# Memory

What MIMO keeps about you, how it decides what matters, and how you correct it.

## Shape

One SQLite table (`memories`) plus an FTS5 mirror (`memories_fts`) kept in sync by triggers, so the
table stays the single source of truth and the index can always be rebuilt from it
(`INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')`).

| Field | Meaning |
|---|---|
| `content` | The fact, in your words |
| `category` | interest, skill, goal, preference, project, education, other |
| `importance` | 1–5. Set from the category when saved, adjustable by you |
| `access_count`, `last_used` | How often a real search returned it, and when |

## Importance

Base values: **goal** and **project** 4, **skill / preference / interest / education** 3,
**other** 2. Recall adds a small lift (`+0.1` per use, capped at 10 uses) when ranking, so a fact
you keep looking up climbs without ever outranking a goal on its own.

## Recall

A search with words goes through FTS5, ranked by `bm25` and then by importance. Prefix matching
means "robot" finds "robotics"; user text is quoted and stripped, so an FTS operator cannot be
injected. A query that returns rows counts as a recall and bumps `access_count`; simply listing
everything does not.

Below FTS5 (an old SQLite build without it) the same query falls back to `LIKE`, ordered by
importance — slower, same answers.

## Correction and deletion

`PUT /memory/{id}` changes wording, category or importance; a correction that would duplicate an
existing fact is refused. `DELETE /memory` with a keyword removes matches. The Memory dashboard in
the app shows every fact with its importance and recall count, with Correct and Forget on each row.

## What is deliberately not stored

Passwords, tokens, card numbers and session cookies are never memories. The Memory agent's tools
(`remember`, `recall`, `forget`) write to the same table, so nothing can bypass these rules.

## Where the next gain is

A hybrid vector index only if a measured evaluation shows FTS5 recall below 80% on paraphrase
queries — the threshold is recorded in `docs/DECISIONS.md` (D5). Until then, latency and simplicity
win.
