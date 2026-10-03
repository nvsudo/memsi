---
name: memory
description: Governed personal memory (memsi, the user's memory of record on Redis). Use whenever the user states a durable preference, fact, decision, or project detail worth remembering; asks what you remember about them, what is pending, or to forget or correct something; or types /memory. Also governs how to treat the memsi digest injected at session start.
---

# memsi memory protocol

The memsi MCP server (tools `memory_recall`, `memory_search`, `memory_propose`, `memory_confirm`, `memory_retract`, `memory_pending`, `memory_audit`) is the user's memory of record. Claude Code's built-in auto-memory is scratch for this project only; do not duplicate into it anything memsi holds.

## Reading

- At session start a digest headed `# Memory of <owner>` is injected by a hook. Treat it as what you know about the user. If it is missing, call `memory_recall(scope="project:<current folder slug>")` once.
- Before answering anything that depends on the user's history, preferences or past decisions and is not in the digest, call `memory_search`.
- Never present a pending memory as fact. Never invent a memory.

## Writing (consent first)

1. When the user states something durable about themselves, their work, or a decision, call `memory_propose` with:
   - `content`: one self-contained sentence in third person ("Prefers X", "Decided on <date> to Y", "Works on Z").
   - `type`: identity | preference | fact | decision | project | procedure | relationship.
   - `scope`: `personal`, `work`, or `project:<repo folder slug>`.
   - `subject`: a short stable key for the thing it is about (home-city, communication-style, memsi-foundation) so later updates to the same fact are detected.
   - `sensitivity`: `private` for personal life, `internal` for work (default), `public` only if clearly harmless anywhere.
   - `confidence`: how sure you are this is durable and correctly stated.
2. Read the result.
   - `duplicate`: say nothing was added; it is already known.
   - `auto_approved`: one short line: "Remembered: <content>."
   - `pending`: ask in one sentence. If a neighbour has relation `possible_update`, ask whether the new one replaces it: "Keep 'Moved to Sydney' and retire 'Lives in Melbourne'?"
3. Only after the user answers, call `memory_confirm` with `decision` approve | reject | supersede (with `supersedes_id`), and `user_quote` set to their actual words. If they corrected the wording, pass `edited_content`.
4. Several proposals in one turn: ask once, listing them, then confirm each according to the answer.

Never propose secrets, credentials, API keys, card or account numbers, government IDs, or health details. Never call `memory_confirm` without an explicit yes or no from the user in this conversation.

## Correcting

- "That's wrong", "forget that", "I never said that": find the memory (digest short id or `memory_search`) and call `memory_retract` with the reason.
- "Actually it's X now": propose X with the same `subject`, then supersede on the user's yes.

## `/memory` subcommands

| Command | Do |
|---|---|
| `/memory` | `memory_pending` then `memory_audit(limit=10)`; summarise what is waiting and what changed recently |
| `/memory recall [scope]` | `memory_recall`; show the digest as returned |
| `/memory search <query>` | `memory_search`; list matches with short ids |
| `/memory pending` | `memory_pending`; list each with its neighbours |
| `/memory review` | walk pending items one at a time; for each ask keep / replace <neighbour> / drop, then confirm with the user's words |
| `/memory audit [n]` | `memory_audit`; table of recent events |
| `/memory forget <id or text>` | locate, confirm with the user, `memory_retract` |
| `/memory remember <text>` | propose it with the best-guess type, scope and subject; ask once; confirm |

## Dashboard

For bulk review or editing, the local dashboard is `./uvw run memctl ui` in the memsi repo, at http://127.0.0.1:7677.
