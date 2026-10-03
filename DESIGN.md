# Governed Personal Memory on Redis — Phase 1 Design

Status: phase 1 build started 2026-10-03 in ~/memsi (core, dev + Redis backends, dashboard inbox/digest/browse/timeline, memctl, MCP server, 18 tests). Awaiting Redis Cloud URL to exercise the Redis backend. Decisions: raw Redis 8 (JSON + Search + Streams), in-chat approval, local MCP for Claude Code + Claude Desktop, personal tool first.

## 1. What this is

A governed memory layer, not a memory store. One Redis-backed MCP server that every AI client reads from on every session and proposes writes to. Writes land as `pending` and become `approved` only after the user says yes in-chat. Contradictions are surfaced, never silently overwritten.

Three principles:

1. **Always read.** Every session starts with a token-budgeted digest. Search is available on demand.
2. **Write on approval.** The model proposes, the user approves, the server records both the decision and the user's verbatim words.
3. **Raise, don't resolve.** The server detects neighbours and returns them. The calling model and the user resolve. The server stays dumb and copyable.

## 1a. User stories (product language)

**Problem.** Knowledge workers use several AI assistants a day. Each keeps its own opaque memory of them: unreviewable, drifting, contradictory, vendor-locked. The user re-explains themselves constantly and cannot see what each tool decided to remember.

**Proposition.** One memory of record per person that every assistant reads from, that nothing writes to without consent, and that the owner can see, correct and carry anywhere.

**Differentiator.** Consent on write, conflicts surfaced not resolved, full audit and undo. Existing memory features write silently.

### Phase 1: the owner

| Epic | Stories | Value | Design sections |
|---|---|---|---|
| 1. Known from the first message | Sessions start with my preferences, projects and decisions. The assistant looks up more mid-conversation when needed. | Removes the re-explain tax and the cost of switching tools. | 3 (`memory_recall`, `memory_search`), 9a |
| 2. One memory, every assistant | Claude Code, Desktop, later ChatGPT and Cursor read the same store. | Portability; memory belongs to the person, not the vendor. | 2 (MCP single door) |
| 3. Nothing kept without my yes | Assistant proposes, I confirm; my words of approval are recorded; trusted low-risk memories auto-approve. | Consent is the differentiator. | 3 (`propose`, `confirm`), 6, 7 |
| 4. Asked, not overwritten | Updates ask to supersede; contradictions are surfaced; duplicates merge silently. | Memory quality compounds instead of rotting. | 6, 8 |
| 5. See and undo | Timeline of every proposal and decision per app; one-action retract. | Makes in-chat approval verifiable and safe. | 3 (`audit`, `retract`), 5 (events stream) |
| 6. Private stays private | Sensitivity levels per memory; per-app read ceilings. | Foundation for the company phase. | 4, 7 (`read_filters`) |
| 7. Tune trust per app | Adjust auto-approve, conflict sensitivity, retention per app and type. | The configuration surface you tune when copying to others. | 7 |
| 8. Scattered memories become one | Claude Code auto-memory synced both ways through the gate; claude.ai and ChatGPT imported. | Migration path; nobody adopts an empty memory. | 9b |
| 9. See what assistants are told | Dashboard inbox with conflicts side by side; digest preview; browse, search, edit with audit. | Transparency is the emotional core. | 9c |
| 10. Never lost, never slow | Nightly backup and restore; no perceptible latency; zero running cost. | Table stakes for a daily habit. | 10a, 11 |

### Phase 2: the adopter and the operator

| Epic | Stories | Value |
|---|---|---|
| 11. Hand it to a colleague in 15 minutes | Isolated store per person from a config template and installer; adopter connects their own accounts. | Tests whether this is a hack or a product; per-person params give structured feedback. |
| 12. Works where I chat | claude.ai and ChatGPT on the phone via remote MCP with login; Slack approval buttons. | Reach where usage actually happens. |

### Phase 3: the team and the company

| Epic | Stories | Value |
|---|---|---|
| 13. Team memory with gatekeepers | `team:<slug>` scope for shared decisions and customer context; team lead approves entries. | Organisational knowledge made consistent across assistants. |
| 14. Policy without friction | Admin sets per-tool sensitivity ceilings, sees cross-user audit; per-user isolation enforced in Redis. | Governance is the buying trigger. |
| 15. Grow into managed infrastructure | Swap backend to Redis Agent Memory without client changes. | For Redis: the reference and demo narrative from raw Redis to the managed product. |

## 2. Surfaces (how Claude touches it)

| Surface | Job | Phase |
|---|---|---|
| MCP server (stdio) | The only door. Same server for Claude Code, Claude Desktop, later ChatGPT/Cursor. | 1 |
| Tool descriptions + MCP `instructions` | The cross-client behavioural contract. Only instruction channel in clients without a system prompt. | 1 |
| Claude Code skill `memory-protocol` | Tells Claude Code when to recall, propose, confirm. | 1 |
| Claude Code `SessionStart` hook | Injects the digest deterministically so "always read" doesn't depend on the model. | 1 |
| Claude Code `Stop` / `PreCompact` hook | Reminder (or headless extraction pass) to propose anything worth keeping. | 2 |
| Remote MCP (HTTP + OAuth) | claude.ai, ChatGPT, phone. | 2 |
| Direct API backends (`memory_20250818`, OpenAI Responses MCP) | Apps the user builds. | 3 |

Note: Claude Code has its own auto-memory. The skill should say this store is authoritative and Claude Code's local memory is scratch.

## 3. MCP tools

| Tool | Model-callable | Purpose |
|---|---|---|
| `memory_recall(scope?, budget_tokens=1500)` | yes | Digest of approved memories for session start. Ranked by scope match, recency, type weight. |
| `memory_search(query, filters?, k=8)` | yes | Hybrid vector + tag search over approved (and optionally pending, flagged). |
| `memory_propose(content, type, scope, subject?, sensitivity?, confidence)` | yes | Dedup + neighbour check. Returns `{id, status: pending|auto_approved|duplicate, neighbours[]}`. |
| `memory_confirm(id, decision: approve|reject|supersede, supersedes_id?, user_quote)` | yes | Records the user's decision. `user_quote` is required and stored. |
| `memory_retract(id, reason)` | yes | Soft delete with audit. Easy undo is what makes in-chat approval safe. |
| `memory_pending()` | yes | Anything proposed but never confirmed (expires after 7 days). |
| `memory_audit(since)` | yes | What was approved/retracted recently. Lets the user review what the model approved on their behalf. |

Approve/reject are model-callable because approval is in-chat. The guard rails are: mandatory `user_quote`, the audit stream, cheap retraction, and auto-approve only where config allows.

## 4. Record schema (JSON at `mem:{owner}:item:{id}`)

```json
{
  "id": "01J9...",
  "content": "Prefers direct, short answers with no closing offers",
  "type": "preference",            // identity | preference | fact | decision | project | procedure | relationship
  "scope": "work",                 // personal | work | project:<slug>
  "subject": "communication-style",// optional key used for update/contradiction grouping
  "sensitivity": "internal",       // public | internal | private
  "status": "approved",            // pending | approved | rejected | superseded | retracted
  "confidence": 0.9,
  "source": {"app": "claude-code", "model": "claude-fable-5-1", "session": "..."},
  "approval": {"by": "user", "quote": "yes keep that", "at": "2026-10-02T..."},
  "valid_from": "2026-10-02", "valid_to": null,
  "supersedes": null,
  "tags": ["style"],
  "embedding": [/* float32[] */],
  "created_at": 1759363200
}
```

Multi-dimensional routing = filters over `scope x type x sensitivity x status x source`. Every key carries an `{owner}` prefix from day one so copying to another person or tenant is a prefix change.

## 5. Redis layout

- `mem:{owner}:item:{id}` JSON document (above)
- `mem:{owner}:idx` RediSearch index on JSON: vector (HNSW, cosine) on `embedding`, TAG on `type scope sensitivity status source.app subject`, NUMERIC on `created_at confidence`
- `mem:{owner}:events` Stream, append-only: `proposed | auto_approved | approved | rejected | superseded | retracted | conflict_raised`
- `mem:{owner}:config` Hash: the feedback params (section 7), hot-reloadable
- `mem:{owner}:digest:{scope}` cached recall output, short TTL, invalidated on any approval

## 6. Write path

```
propose
  -> embed
  -> vector search top-k within scope (and same subject if given)
  -> cosine >= dup_threshold            => return duplicate, no write
  -> cosine in [conflict_lo, dup)       => write as pending, return neighbours flagged possible_update_or_conflict
  -> no neighbours
       -> auto-approve rule matches     => approved, event auto_approved
       -> else                          => pending, event proposed
model asks user in-chat
  -> confirm(approve)                   => approved
  -> confirm(supersede, supersedes_id)  => new approved, old superseded with valid_to=now
  -> confirm(reject)                    => rejected
unconfirmed after 7d                    => expired
```

The server never calls an LLM. The calling model decides duplicate vs update vs contradiction using the neighbours returned, and asks the user. Phase 1 keeps the server to embeddings + Redis.

## 7. Controlled feedback params (`config.yaml`, mirrored to `mem:{owner}:config`)

```yaml
owner: nik
thresholds:
  duplicate: 0.92
  conflict_low: 0.75
auto_approve:
  - { type: preference, min_confidence: 0.9, sources: [claude-code], require_no_neighbours: true }
  - { type: project,    min_confidence: 0.85, sources: [claude-code] }
never_auto_approve_types: [identity, relationship]
read_filters:
  claude-code:    { sensitivity_max: private }
  claude-desktop: { sensitivity_max: private }
  chatgpt:        { sensitivity_max: internal }   # phase 2
recall:
  budget_tokens: 1500
  type_weights: { identity: 3, preference: 2, decision: 2, project: 1.5, fact: 1, procedure: 1, relationship: 1 }
  recency_half_life_days: 60
ttl_days:
  project: 180
  fact: 365
pending_expiry_days: 7
```

These are the knobs you tune per person when copying the system.

## 8. Conflict semantics

| Case | Signal | Resolution |
|---|---|---|
| Duplicate | cosine >= 0.92 | Server drops it, returns existing id |
| Update | neighbour, same subject, different value, time-ordered | Model proposes supersede, user confirms, old gets `valid_to` |
| Contradiction | neighbour, same subject, both claimed current | Model must ask the user; nothing is written as approved until they answer |

Most "conflicts" turn out to be updates once temporal validity is modelled.

## 9. Phase 1 deliverables

1. `docker-compose.yml`: Redis 8 (or Redis Cloud URL)
2. MCP server (stdio) with the seven tools, embeddings, index bootstrap
3. `memory-protocol` skill for Claude Code
4. `SessionStart` hook that injects `memory_recall`
5. `install.sh` that writes MCP config into Claude Desktop and Claude Code
6. `config.yaml` with the params above
7. `memctl` CLI: `recall | search | pending | audit | retract | export | import` for when you want to look without a model in the loop

## 10. Phase 2 and 3 (sketch)

- Phase 2, copy for others: owner prefix becomes a CLI flag, config template, export/import, remote MCP with OAuth so claude.ai and ChatGPT join. Slack approval buttons as an alternative to in-chat.
- Phase 3, intra-company: per-user stores plus a `team:<slug>` scope with its own approvers, Redis ACLs per owner, admin policy over `read_filters`, and the option to swap the storage backend for Redis Agent Memory (Iris) to inherit extraction.

## 9a. How memory gets loaded into a chat

Two tiers, always:

1. **Digest, every session, automatic.** `memory_recall` returns a ~1500-token digest: identity and preferences first, then decisions and project memories for the detected scope, ranked by type weight and recency. Scope is inferred from context (Claude Code: the cwd's project slug; Desktop: the project name if any) plus the always-on `personal` and `work` scopes.
2. **Search, mid-conversation, on demand.** When the digest isn't enough the model calls `memory_search`. Tool description tells it to do so before answering anything about the user's history, preferences or past decisions.

Per client, how tier 1 actually fires:

| Client | Mechanism | Fires every chat? | Model involved? |
|---|---|---|---|
| Claude Code | `SessionStart` hook (matchers: startup, resume, clear, compact) runs `memctl recall --scope auto --budget 1500`; stdout is injected as context | Yes, deterministic. The `compact` matcher re-injects after context compaction. | No |
| Claude Code | `memory-protocol` skill | No. Skills govern behaviour (when to propose/confirm/search). Not a loading mechanism. | Yes |
| Claude Code | `/memory` user-invocable skill: `recall`, `search <q>`, `pending`, `audit` | Only when typed | Yes |
| Claude Desktop | MCP server `instructions` field + `memory_recall` description ("call first in every conversation") | Most chats, not guaranteed. First turn shows one tool call. | Yes |
| Claude Desktop | Project instructions: "Call memory_recall before your first reply" | Reliable inside that Project | Yes |
| Claude Desktop | MCP prompt `recall` the user picks manually | Only when invoked | No |
| Any | `memctl` CLI outside chat | Manual | No |

Coexistence: Claude Code's built-in auto-memory and claude.ai's memory feature keep running. CLAUDE.md states the Redis store is authoritative and the built-in memory is scratch. Phase 2 can import both.

Cost of "every chat": ~1500 input tokens per session plus one Redis round trip. Negligible.

## 9b. Syncing with other memories

Principle: Redis is the system of record. Every other memory is either a view (written from Redis) or a feed (emits proposals into the gate with provenance). Nothing enters as approved without passing the gate.

| Source | Direction | Mechanism | Phase |
|---|---|---|---|
| Claude Code auto-memory (markdown per fact + index, per project dir) | Two-way | Redis -> files on approval for `project:*` scope, with `redis_id` + content hash in frontmatter. Files -> Redis via a Stop hook that diffs the memory dir against a hash manifest and emits `memory_propose` (source `claude-code-automemory`, type mapped from frontmatter). Skip files whose hash matches what Redis wrote (loop prevention). Pending items batch-reviewed via `/memory pending`. | 1 |
| claude.ai / Claude Desktop account memory | In only | No public API. (a) In-chat: "propose everything you remember about me" with the connector attached. (b) `memctl import --source claude-ai` from the Settings memory export. Redis -> claude.ai happens only organically via the recall digest being present in conversations. | 1 (manual), adapter later |
| ChatGPT memory | In only | Same two paths as claude.ai once the remote MCP exists. | 2 |
| Claude API memory tool (`memory_20250818`), own agents | None needed | Redis is the backend. | 3 |
| Managed Agents memory stores | Optional, in | Pull via API into proposals if ever used. | later |

Adapter contract: `iter_candidates() -> [{content, type, scope, source, external_id, observed_at}]`. The sync runner dedups on `external_id` + hash, then calls the same propose path as the MCP tool.

## 9c. Viewing and editing memory

| Layer | What | Writes? | Phase |
|---|---|---|---|
| Redis Insight | Raw key browser over `mem:{owner}:*`, run FT.SEARCH, inspect JSON. Escape hatch only: edits here bypass the event stream. | Look, don't edit | 0 (free) |
| `memctl` CLI | recall, search, pending, audit, retract, export, import. Used by hooks and nightly backup. | Through core write path | 1 |
| `memctl ui` local web dashboard | FastAPI + Jinja + HTMX, no node build. Separate long-running process from the stdio MCP server; both import the same core package. localhost only, token auth when remote. | Through core write path, source `dashboard` | 1 |
| TUI inbox | Thin Textual view over the same API, only if wanted. | Through core write path | optional, later |

Dashboard views:
- **Inbox**: pending proposals with semantic neighbours side by side; approve / reject / supersede / edit-then-approve; bulk actions for sync batches.
- **Browse & edit**: filters on scope, type, sensitivity, status, source; keyword + semantic search; inline edit re-embeds and emits an `edited` event.
- **Digest preview**: render exactly what `memory_recall` returns for a chosen scope and budget. The trust feature.
- **Timeline**: the event stream, filterable by source app and decision.
- **Config**: feedback params as a form, hot-reloaded to `mem:{owner}:config`.
- **Health**: bytes used vs plan cap, last export, Redis RTT, embedder loaded.

Rule: one write path. CLI, dashboard and MCP tools all call the same `propose` / `confirm` / `retract` / `edit` functions in core, so the audit log is complete regardless of entry point.

## 10a. Latency budget, cloud vs local (estimates, same-metro region, warm connection)

| Step | Local Docker | Redis Cloud (Sydney from Sydney) | Redis Cloud (Sydney from Melbourne) |
|---|---|---|---|
| Embed one memory, bge-small in-process, warm | 10-30 ms | same | same |
| Redis round trip | <1 ms | 5-15 ms | 15-30 ms |
| FT.SEARCH execution on a few thousand vectors | 1-3 ms | same | same |
| **recall** (1 search, or cache hit) | ~15-35 ms | ~25-50 ms | ~35-65 ms |
| **search** (embed + 1 search) | ~15-35 ms | ~25-50 ms | ~35-65 ms |
| **propose** (embed + search + JSON.SET + XADD, pipelined) | ~15-40 ms | ~35-80 ms | ~50-100 ms |
| **confirm** (JSON.SET + XADD, pipelined) | ~1 ms | ~10-30 ms | ~20-60 ms |
| Cold TLS connect (once per server process) | n/a | ~30-60 ms | ~60-120 ms |
| Model turn that wraps any of the above | 2,000-20,000 ms | same | same |

Rule of thumb: cloud adds 1-3 round trips per memory operation, i.e. 10-80 ms. Embedding costs about the same as one cloud round trip. The LLM turn is 50-500x larger. Cloud latency is invisible in interactive use.

Where it is visible: bulk paths (export, import, re-embedding) if written as one command per record. Always pipeline those, or use `FT.SEARCH` with paging and `MGET`/`JSON.MGET` so N records cost ~N/100 round trips. The SessionStart hook sits on the critical path of starting a Claude Code session, so keep recall to one pipelined call and serve from the cached digest when nothing has changed.

Design rules that follow: one persistent connection per server process (no connect per call), pipeline every multi-command write, cache the recall digest in Redis with a short TTL, and keep the embedder loaded in memory for the life of the process (first embed after startup costs ~1-2 s to load the model).

## 11. Decisions and open items

Decided:
- Language: Python (redis-py, FastMCP, uv). Embedding provider is a pluggable interface.
- Redis host: Redis Cloud, region nearest the user (Sydney on AWS). Local Docker stays available via `REDIS_URL`.

Facts behind the Redis Cloud choice (Essentials plans, Sep 2026 docs):
- Free 30 MB: 30 connections, 100 ops/sec, 5 GB/month bandwidth, no replication or backups, inactive databases deleted after about 2 weeks idle.
- Paid 250 MB ($5/month): 256 connections, 1000 ops/sec, 100 GB/month, replication and backups.
- Capacity estimate: ~5 KB per memory with 768-dim float32 vectors (~6k memories in 30 MB); ~2.5 KB with 384-dim (~12k).
- Latency: one round trip per recall, one or two pipelined per propose. Same-metro RTT 5-15 ms. Imperceptible next to embedding and LLM time.
- Mitigation for the free tier: nightly `memctl export` to a local JSONL file, and `memctl import` to restore.

- Embedding default: in-process `BAAI/bge-small-en-v1.5` via sentence-transformers (384-dim, no daemon, ~130 MB model). Ollama and hosted providers behind the same interface.
- Plan: free 30 MB to start, with a nightly `memctl export` (launchd job) to `~/.memory/backups/YYYY-MM-DD.jsonl`. Upgrade to 250 MB when the store is relied on daily.

Still open (not blocking phase 1):
- Exact wording of the tool descriptions and MCP `instructions` field (this is the behavioural contract, worth a dedicated pass)
- Whether the `Stop` hook does a headless extraction pass with `claude -p` or just reminds the model to propose
- Scope naming convention for projects (`project:<slug>`) and who creates new scopes
