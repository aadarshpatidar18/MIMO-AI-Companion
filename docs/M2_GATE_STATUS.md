# M2 release gate — coverage status

Implements the gate in `docs/REVIEW_W1.md` §2 against the current tree. Baseline after
this round: **189 passed, 0 skipped** (`pytest -q -rs -p no:cacheprovider`).

Status words: **covered** = a test asserts the clause and a mutation was shown to kill it;
**partial** = the clause is half-asserted; **open** = nothing asserts it yet.

| Row | Status | Test / gap |
|---|---|---|
| E1 pairing issuance | covered | `test_security.py::test_pairing_code_requires_a_local_or_trusted_caller` (anonymous 401, non-admin 403). Mutant: issuer check removed → red. |
| E2 invalid/expired code | partial | `test_code_expires`, `test_new_code_invalidates_the_previous_one`. Equality-at-expiry not asserted. |
| E3 one-time redemption | partial | `test_code_is_single_use` is sequential; concurrent redemption untested. |
| E4 enrollment privilege binding | open | Request body cannot carry scopes or an owner, but no test pins that. |
| E5 enrollment abuse budget | partial | `test_pairing_attempts_are_rate_limited`; per-bucket independence and varied codes untested. |
| E6 failed redemption rollback | open | Needs injected failure between device and token insert. |
| T1 issuance and storage | covered | `test_raw_token_is_never_stored` (hash only, prefix and length). |
| T2 rotation and restart | partial | `test_rotation_invalidates_the_old_token_only_for_that_device`; restart after rotation untested. |
| T3 rotation atomicity | open | Needs injected rotation failure and a concurrent-rotation winner rule. |
| T4 immediate revocation | covered | `test_revocation_takes_effect_on_the_next_request`. Single process only. |
| T5 in-flight write revocation | open | Needs a paused commit race; depends on C5's transaction boundary. |
| S1 authentication vs authorization | covered | `test_auth_gate_closes_everything_but_health_and_pairing` (401) plus every `403` denial test. |
| **S2 indirect effects** | **covered** | `test_dispatch_policy.py` (5 tests). Mutants killed: collapse every capability to `chat:write` → 3 red; drop the check before `save_memory` → 1 red; ignore device scopes → 3 red; remove the direct-route scope check → 4 red. |
| S3 object-level authorization | partial | Single-owner by design; needs an owner/workspace fixture before a cross-owner test is meaningful. |
| S4 server-owned attribution | partial | `test_two_devices_share_one_history` asserts the stored `device_id` is the caller's; body cannot supply one today. |
| S5 release transport | open | Client-side; assert the release build refuses cleartext. |
| C1 shared persistence and context | covered | `test_two_devices_share_one_history`, `test_chat_through_a_shared_conversation_persists_and_reuses_history`. |
| **C2 explicit selection** | **covered** | `test_paired_chat_without_a_conversation_id_is_refused`. Mutant: implicit `default` fallback restored → red. |
| C3 ordering and pagination | covered | `test_append_and_read_in_order`, `test_pagination_with_after_id` (ids are `AUTOINCREMENT`, so equal timestamps cannot reorder). |
| C4 concurrent writes | partial | `test_concurrent_appends_keep_every_message_and_unique_ids` (4 threads, ids inside the write transaction). Two-device HTTP race not exercised. |
| **C5 whole-turn atomicity** | **covered** | `test_a_turn_is_stored_whole_or_not_at_all` (trigger aborts the assistant row; nothing survives; retry works). Mutant: append the user row separately → red. |
| C6 restart durability | partial | `test_messages_survive_reopening_the_database`; a fresh OS process is not exercised. |
| C7 safe retry | open | No client request-id column; needed only if clients auto-retry. |
| L1 length and request size | partial | `test_oversize_message_is_refused` and `test_conversation_message_length_is_enforced_by_the_api`; encoded-byte bound untested. |
| L2 device message rate | partial | `test_chat_rate_limit` (429). Boundary and per-device independence untested. |
| L3 concurrent rate admission | open | Limiter has a lock; no test fills n-1 slots and releases n. |

## What changed in this round

* `backend/core/security/dispatch.py` — one `ActionPolicy` mapping capability to the
  scope that grants it (`tool.invoke` → `agent:run`, memory reads/writes → `memory:*`).
* `backend/api.py` — `process_message` asks that policy immediately before each tool call
  and memory mutation, not at the route, so `/chat` and the dedicated routes answer the
  same question; denial is 403 with no downstream call and no stored turn. `/memory`
  routes now require their scope. A paired device must name its conversation.
* `backend/api.py` — a turn is written with `append_turn` in one transaction.
* `backend/core/agent/routes.py`, `backend/core/llm/routes.py` — run/control and
  read/manage scopes on the routes that previously only needed any live token.
* `backend/core/security/gate.py` — `require_scope(..., allow_unpaired=True)` keeps the
  pre-M2 fixtures working with authentication off while still refusing a *paired* device
  that lacks the scope.

## Next, in order

1. T5, C4, L3 (races), then E3, E6, T3 (transactional enrollment/rotation).
2. C6 and T2 across a fresh process; S5 in the Android release config.
3. C7 only if clients auto-retry; S3 once owner/workspace scoping is decided.

Not in this milestone: approval as a one-use decision for a single step, uncertain-outcome
state after a timeout, and a durable attempt record (review §1 findings 2 and 3). Those
sit in `backend/core/agent/` and block new effectful operators, not identity + conversations.
`/chat`'s legacy tools are now scope-gated, but they still do not pass through the agent's
plan/approval path — that is the next architectural slice, not a regression this gate hides.
