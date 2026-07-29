# Latency & Architecture Review

**Goal:** shorten the time between a player making a play and getting a response.
**Scope:** advice only — no code changed. This document maps your real critical path, honestly assesses the three ideas you floated (microservices, tools-as-MCP-server, RabbitMQ+Celery), and lists the changes that will actually move the needle.

---

## TL;DR

1. **Your latency is dominated by LLM inference time (seconds), not process/network overhead (microseconds–milliseconds).** Distributing the pipeline across services would *add* hops on top of multi-second LLM calls — strictly worse for the play→response time.
2. **Your instinct to "distribute = faster" is mostly wrong *for this codebase***, because the work is a single request-scoped, streaming workflow that is *already* concurrent in-process via asyncio + LangGraph parallel branches. You've done the hard part already.
3. **The real wins are inside the graph:** cap the planner's reasoning, run responding NPCs concurrently instead of sequentially, and trim the Graphiti search fan-out. These are small, local, high-ROI changes — not infrastructure rewrites.
4. **RabbitMQ + Celery is a good idea *only for the background work* you already fire-and-forget** (epilogue, memory, lore ingestion) — for durability/isolation, not latency. It is the wrong shape for the turn pipeline itself.
5. **Tools-as-MCP-server does almost nothing for play latency** because tools are not on the common play path. It's a reuse/shareability decision, not a latency one.
6. **Measure before you build.** Langfuse is already wired in (`langfuse_callback_handler` in `api/events.py`). Your traces already show per-node wall time. Go look at them before refactoring anything in this doc.

---

## The actual critical path (in-character dialogue turn)

From `api/events.py:send_message` → `graph.astream(...)` → the DM supervisor graph in `agents/dungeon_master/graph.py`:

```
send_message
  └─ state_loader ──────────────┐  (4 Postgres reads, parallel via to_thread)
       ├─ graphiti_loader ──────┤  (4 Graphiti hybrid searches, parallel)
       └─ intent_router ────────┘  (1 LLM call, structured output)
            └─ context_join (barrier: waits for graphiti_loader + intent_router)
                 └─ [ooc short-circuit] OR rules_referee (1 LLM call, only if adjudication)
                      └─ dm_planner (1 LLM call, structured output, UNBOUNDED reasoning)
                           └─ continuity_checker (1 LLM call) ── on reject ──> back to dm_planner (max 1 repair)
                                └─ fan-out:
                                     ├─ dm_narrator_opening  (1 LLM call, STREAMS to client)
                                     └─ npc_builder_caller   (only if new NPCs; whole sub-graph, SLOW)
                                          └─ npc_executor (DEFERRED join: runs each responding NPC SEQUENTIALLY)
                                               └─ per NPC: context_loader(2 graphiti) → emotion(LLM) → planner(LLM) → narrator(LLM, STREAMS, up to 3 retries)
                                                └─ dm_narrator_closing (1 LLM call, if closing narration)
                                                     └─ canon_manager (Postgres writes + Graphiti fire-and-forget)
                                                          └─ turn_epilogue (fire-and-forget: scene summary + faction sim — DOES NOT BLOCK)
                                                               └─ persist_messages (DB commits)
                                                                    └─ END
```

Two things stream token-by-token to the Socket.IO client and are already visible to the player as they generate: `dm_narrator_opening`/`closing` and each NPC's `npc_narrator`. So the player-perceived latency is really two numbers:

- **Time-to-first-token (TTFT):** everything *before* the first streamable node emits a token.
- **Time-to-turn-complete:** TTFT + all the NPC legs (sequential) + closing narration.

---

## Where the time actually goes (MEASURED in Langfuse — July 2026)

Pulled from your self-hosted Langfuse (`http://langfuse.localhost`), 861 `dungeon_master` traces. Numbers below are real wall times observed across 4 representative in-character turns (141s, 165s, 93s) plus one OOC short-circuit (13.7s), and one standalone `npc_builder` trace (30.6s). Every LLM hop is `ChatNanoGPT` = `zai-org/glm-5.2` via nano-gpt.

| Node | File | Measured wall time | Blocks TTFT? | Notes |
|---|---|---|---|---|
| state_loader | `context.py:79` | 0.06–0.37s | yes | 4 Postgres reads in parallel. Cheap. |
| graphiti_loader | `context.py:113` | **0.24–1.01s** | yes | **NOT a bottleneck** — my earlier 0.5–1.5s "reranker LLM call" worry was wrong; the 4 parallel searches finish in <1s. Downgraded. |
| intent_router | `intent.py:21` | **3.2–11.5s** | yes | "Cheap classifier" with thinking disabled + 512 tokens, yet 3–11s. Runs parallel with graphiti_loader so it's the gating item there. |
| rules_referee | `referee.py:16` | ~0s (skipped on dialogue) | yes (when adjudicating) | Not sampled in these traces. |
| **dm_planner** | `planner.py:12`, `llm_models.py:66` | **19–26s per call; 46s when it runs twice** | **yes — biggest TTFT blocker** | `ChatNanoGPT(**nanogpt)`, no reasoning cap. In the 165s trace continuity rejected and the planner re-ran, costing a second ~23s. |
| **continuity_checker** | `continuity.py:16` | **8.8–22.9s** | yes | **Surprisingly expensive.** `thinking_disabled=True`, max 512 tokens, yet up to 23s. Either the nano-gpt endpoint isn't honoring `thinking: disabled`, or structured output over a prompt containing the full `plan_json` is just slow on glm-5.2. Also the trigger for the planner redo. |
| dm_narrator_opening | `narration.py:33` | 13–16s | this *is* the first token (when present) | Streams. |
| dm_narrator_closing | `narration.py:55` | 11–13s | no | Streams. Optional. |
| npc_builder_caller | `builder.py:25` | ~30s (2-round build measured) | no (overlaps opening narration; but npc_executor waits for it) | Two `agent` LLM calls: 27s + 3.4s. `create_character` DB write is 0.01s. |
| **npc_executor** | `executor.py:97` | **32–43s per NPC, SEQUENTIAL** | no (narration streams), but **dominates total time (34–57% of the turn)** | 2 NPCs = 77–80s. Per NPC = emotion_updater (9–12s) + planner/thoughts (9–19s) + npc_narrator (11–16s) + context_loader (0.1–0.2s). |
| canon_manager | `canon.py:17` | 0.05–0.09s | no | Postgres writes; Graphiti saves fire-and-forget. |
| turn_epilogue | `epilogue.py:169` | ~0s (fire-and-forget) | no | Already off the critical path. |
| persist_messages | `canon.py:90` | 0.05–0.07s | no | **Negligible** — the "one commit per message" isn't actually hurting. Downgraded. |

**Measured turn profiles:**
- **OOC short-circuit:** ~13s total = intent_router (5.3s) + ooc_responder (8.3s). Everything else skipped.
- **1-NPC in-character:** ~93s = state_loader + max(graphiti,intent) (~11s) + dm_planner (19s) + continuity (9s) + dm_narrator_opening (16s) + 1 NPC (32s) + dm_narrator_closing (13s) + canon/persist (~0.1s).
- **2-NPC in-character:** ~140–165s, with npc_executor at 77–80s (~half) and dm_planner+continuity at 35–58s.
- **Outlier:** one trace reports `latency=1925s`, but its `dungeon_master` chain observation is only 141s — the trace stayed "open" ~1784s past the real work, almost certainly a fire-and-forget background LLM task (memory/scene-summary) that remained associated with the trace. **The synchronous work the player waits on was 141s.** Worth fixing as an observability issue (the trace `latency` field overstates real turn time when background tasks attach).

**The real picture:** ~95% of every turn is LLM generation time on glm-5.2, where each call costs 3–26s regardless of node. The two dominant terms are **npc_executor (sequential, total-time killer)** and **dm_planner + continuity_checker on the TTFT path**. Graphiti, Postgres, tools, canon, and persist are collectively <2s and **not the problem**. The wins are about (a) fewer LLM calls, (b) concurrent LLM calls, and (c) cheaper model config — not infrastructure.

---

## Your three proposals, honestly assessed

### 1. Split into microservices — **No, do not do this for latency.**

Every node transition would gain: serialize LangGraph state (large: messages, lore, secrets, clocks, threads, npc states) → network hop → deserialize. That is **strictly additive** latency on top of multi-second LLM calls. You would be paying 1–100ms × ~10 transitions/turn to remove microseconds of in-process function-call overhead.

Worse, your agents share a lot of in-memory, request-scoped state that does not cross a process boundary cleanly:
- The `Conversation` object and its transient `message_buffer` (`database/models/conversation.py`).
- The single shared SQLAlchemy `session` (`database/postgres_connection.py`), already a known sharp edge — see the `db_session.rollback()` in `agents/dungeon_master/builder.py:48` triggered by the unique-name constraint. Splitting services would force you to extract a data-access service *and* solve distributed transaction/session semantics — a big refactor for *negative* latency gain.
- The `DMContext` / `sio` / `sid` trio that lets nodes stream straight to the client's socket. Putting nodes in separate processes means re-plumbing streaming (currently 5 lines in `executor.py`) over a broker.

The DM turn is a **single request-scoped streaming workflow**, not a set of independently-scaling long-lived services. Microservices earn their cost when workloads scale or deploy independently; nothing about a single player's turn has that shape. The fan-outs you'd want (`graphiti_loader || intent_router`, `narrator || builder`) are **already concurrent in one process** via LangGraph parallel branches + `defer=True` join nodes. You implemented the good version already.

**Verdict:** keep it one process. Microservices here would make play→response *slower* and the codebase materially harder to run.

### 2. Tools as an MCP server — **Not for latency. Only if you want to share tools.**

First, a key fact about your play path: **the DM supervisor graph calls Python functions directly, not via the LangChain `@tool`/`ToolNode` mechanism.** `state_loader`, `intent_router`, `referee`, `planner`, `continuity`, `narrator`, `npc_executor`, `canon_manager`, `epilogue` all import and call `tools.participants`, `tools.world_state`, `database.graphiti_utils` as ordinary Python. The `ToolNode`/`@tool` path is used **only** by `spawn_npc_builder` and `spawn_lore_creator` (`agents/tool_agent.py`) — i.e. the NPC-build and lore-authoring sub-agents.

Consequences:
- On the **common play path** (no new NPCs), zero tool calls go through `ToolNode`. An MCP server would change **nothing** on that path's latency.
- On the **NPC-introduction path**, each `search_lore`/`search_entities`/`create_character` call would become a JSON-RPC round-trip over stdio/HTTP. Those calls already hit Graphiti (slow) or Postgres (fast), so the MCP framing overhead is small *relative to the tool's own work* — but it is still strictly additive, on a path that is already the slowest in the system and already overlaps with opening narration.

So MCP-for-tools is latency-neutral-to-slightly-negative. **The real reason to do it would be reuse**: if you want an external lore-editor UI, a separate admin CLI, or third-party agents to call the same `search_lore` / `save_lore_entry` / `apply_participant_state_update` surface, an MCP server is a clean way to expose it. That is an architecture/reuse call, not a latency call.

**Verdict:** don't do it to speed up play. Do it later, only if sharing tools across consumers becomes a real need.

### 3. RabbitMQ + Celery — **No for the turn pipeline. Yes (later) for the background jobs.**

Celery is a *durable, asynchronous, distributed task queue*. The DM turn is a *synchronous, request-scoped, streaming* workflow. They are opposite shapes:

- Celery tasks don't stream tokens to a Socket.IO client natively. You'd build a results backend + polling or a pub/sub channel to push tokens back — replicating, poorly, what `graph.astream(...)` + `sio.emit(...)` does in a handful of lines today.
- Every inter-agent message over RabbitMQ pays serialize → enqueue → broker → dequeue → deserialize. ~1–10ms × ~10 transitions/turn. Additive, on top of LLM seconds.
- The `Conversation`/`DMContext`/`session`/`sid` sharing problem from §1 applies again, and worse (now across machines).

**But** — Celery is *exactly right* for the fire-and-forget work you already have, just for different reasons than latency:

| Current fire-and-forget task | File | Why Celery would help |
|---|---|---|
| scene summary + faction simulation | `epilogue.py:190` (`_run_epilogue`) | Durability + retries; survives a process restart. Currently lost if uvicorn dies mid-task. |
| per-NPC memory extraction + Graphiti ingest | `nonplayer.py:244` (`process_and_save_memory`) | Same; plus isolates LLM-extraction load from the request event loop. |
| world events / secret / player-pref saves | `canon.py:27,33`; `graphiti_utils.py` | Same. |
| `bulk_save_lore_entries` | `lore_management.py:112` | Already uses `asyncio.create_task`; a durable queue with a real worker pool would be more robust under load. |

Moving these to Celery would **not shorten play→response** (they already don't block the response — that's the whole point of `fire_and_forget`). It *would* give you durability, retries, observability, and isolation of background LLM-extraction calls from request-serving capacity. That is a worthwhile operational improvement — just be honest that it's a reliability project, not a latency project. It also has a *tiny* positive latency effect: removing background LLM calls from the request event loop so they can't compete with a turn's own LLM calls for the GIL/loop under load.

**Verdict:** RabbitMQ+Celery for the *turn pipeline* = slower and vastly more complex. RabbitMQ+Celery (or a lighter queue like RQ/Dramatiq/arq) for the *epilogue/memory/lore-ingestion background jobs* = good, do it eventually, justify it as reliability not speed.

---

## What will actually shorten play→response

Ordered by ROI. None of these require services, brokers, or MCP.

### A. Cap the planner's reasoning effort (highest ROI, ~1 line)
`utils/llm_models.py:66`:
```python
dm_planner_model = ChatNanoGPT(**nanogpt)   # <-- no reasoning cap
```
Your own `_nano()` helper exists precisely to avoid GLM-5.2's "costly 7-minute trap" of unbounded reasoning, and every other planner-adjacent hop uses it (`dm_intent_model`, `dm_continuity_model` disable thinking; `dm_referee_model` caps at `"high"`). The planner — the single biggest call on the TTFT critical path — is the one that doesn't. Switch it to `_nano(reasoning_effort="medium"|"high", max_tokens=...)` and measure. This alone could cut multiple seconds off every single turn's time-to-first-token, and makes TTFT predictable instead of occasionally catastrophic.

### B. Run responding NPCs concurrently instead of sequentially (highest ROI for total time)
`agents/dungeon_master/executor.py:104`:
```python
for directive in plan.responding_npcs:
    ...
    input_messages = [*state.messages, *all_messages]   # each NPC sees prior NPCs' output
    delta = await _stream_npc_to_socket(...)             # awaited one at a time
    all_messages.extend(delta)
```
This is a sequential `for` loop, so N NPCs cost N × ~32–43s (measured). Two NPCs = 77–80s, which is ~half of a typical multi-NPC turn. Two observations that unlock parallelism:

1. The DM plan already assigns each NPC a `directive.guidance` and `.withheld_info`. NPCs who aren't directly replying to each other don't *need* each other's output — they can run off the pre-turn state + their directive alone, concurrently.
2. Even where there *is* a dependency (B reacts to A), you can run them concurrently on the pre-turn state and rely on the existing continuity/repair philosophy ("one pass, then proceed"). The quality risk is two NPCs stepping on each other; mitigate by having the plan flag `responds_to` so only truly independent NPCs fan out, and dependent ones stay ordered.

A clean first cut: group `responding_npcs` into independent vs dependent using a field the planner already almost gives you; `asyncio.gather` the independent ones (preserving their stream order by emitting each NPC's tokens as they arrive), keep the dependent chain sequential. For a 3-NPC scene where all three are independent, that's ~3× on the NPC leg — the single biggest total-time win available.

### B2. ~~Run `emotion_updater` and `planner` concurrently *inside* each NPC~~ — **RESOLVED differently (Jul 8): removed both nodes**
**Status:** instead of parallelizing them, both `emotion_updater` and `planner` were removed from `agents/nonplayer.py` and their responsibilities (emotion modeling + internal reasoning about wants/suspicions/next action) were folded into the narrator itself via a new `<internal_process>` block in the `npc-narrator` Langfuse prompt (v33). The NPC graph is now `context_loader → npc_narrator → END`, eliminating ~18–31s of pre-narration LLM hops per NPC. The narrator's prompt also now wires `{{dm_guidance}}` (the DM directive), which the old planner/emotions prompts never consumed. Original analysis preserved below for reference.

Measured per-NPC breakdown (now historical): `context_loader` (0.1–0.2s) → `emotion_updater` (9–12s) → `planner`/thoughts (9–19s) → `npc_narrator` (11–16s). The first three ran **sequentially before any narration streamed**, so each NPC ate ~20–30s of pre-speech latency. `emotion_updater` (emotional-state deltas) did not depend on `planner` (the NPC's thoughts) — both read the same `combined_dump`. Running them with `asyncio.gather` would have cut per-NPC pre-narration time by ~9–12s. Removing both cuts it by ~18–31s.

### C. Trim the Graphiti search fan-out — **DOWNGRADED (measured cheap)**
`context.py:125` fires 4 parallel `load_information` calls for the DM; `nonplayer.py:189` fires 2 per NPC. **Measured:** `graphiti_loader` is 0.24–1.01s and per-NPC `context_loader` is 0.1–0.2s — not a bottleneck. My original concern about the grok cross-encoder reranker being an LLM round-trip per search didn't show up in the data (your per-campaign groups are small enough that the reranker is cheap or not firing). **Skip this unless future traces show it growing.** The only sub-item worth keeping in mind: an embedding cache keyed by query (the same player query is re-embedded for the DM loader + every NPC) — but at <1s total it's a micro-optimization, not a priority.

### D. Don't let NPC building block responding NPCs
When new NPCs are introduced, `npc_builder_caller` runs concurrently with `dm_narrator_opening`, but `npc_executor` is `defer=True` and waits for **both** branches (`graph.py:127`, `after_registrar`). Measured NPC build is ~30s; opening narration is 13–16s. So the *existing* responding NPCs sit idle for ~15s before they can speak. Consider: let already-existing responding NPCs start as soon as opening narration finishes; only the *newly-built* NPC's response needs to wait for its own build. Longer term, pre-warm likely NPCs before the turn (the plan often foreshadows an encounter).

### E. Batch the message commits — **DOWNGRADED (measured negligible)**
`canon.py:93` `persist_messages` calls `conversation.add_message(...)` once per message, and `add_message` does `session.commit()` each time (`conversation.py:176`). **Measured:** the whole node is 0.05–0.07s. Batching to one transaction is cleaner code but not a measurable latency win. Do it only if you're already in the file for another reason.

### F. Right-size the narration / classifier models
Measured generation times on glm-5.2 (nano-gpt): `npc_narrator` 11–16s, `dm_narrator_opening` 13–16s, `dm_narrator_closing` 11–13s, `intent_router` 3–11s, `continuity_checker` 9–23s, `emotion_updater` 9–12s, `npc thoughts` 9–19s. These are the tokens the player *waits on* (narration) or that block TTFT (intent/continuity). Two angles:
- A faster/lower-latency model for the **streaming narration** hops maps directly to perceived speed (balanced against prose quality).
- For the **non-streaming classifier hops** (`intent_router`, `continuity_checker`, `emotion_updater`), latency matters more than prose quality — these are prime candidates for a smaller/faster model or stricter token/reasoning caps.

### H. Investigate why `continuity_checker` is so expensive (new, from traces)
`continuity_checker` uses `dm_continuity_model = ChatNanoGPT(**_nano(thinking_disabled=True, max_tokens=512))` — yet measured at **8.8–22.9s**. That's as expensive as the planner itself, for a hop that's supposed to be a cheap validation pass. Two things to check:
1. **Is `thinking: disabled` actually honored by the nano-gpt endpoint?** The `intent_router` (same `_nano(thinking_disabled=True, max_tokens=512)` config) is also 3–11s — suspiciously slow for "no thinking, 512 tokens." If the endpoint is ignoring the `extra_body.thinking` field, you're paying for reasoning you tried to turn off. A quick A/B: send one such call with and without the flag and compare latency/token counts in Langfuse.
2. **Trim the prompt.** `continuity_checker` includes the full `plan.model_dump_json(indent=2)` plus a 12-message window. A smaller prompt → fewer input tokens → faster time-to-first-token.
3. **Avoid the planner redo.** In the 165s trace, continuity rejected and the planner re-ran (+23s). The redo is the real cost. Consider: only redo on *severe* issues (secret leaks, agency violations), and auto-approve minor continuity nits with a note rather than re-planning.

### G. (Optional, later) Move fire-and-forget jobs to a durable queue
As in §3: reliability/isolation win, not a latency win. Use a lightweight async queue (arq/Dramatiq) before reaching for the Celery+RabbitMQ stack.

---

## Before you do anything: measure — DONE (July 2026)

Pulled real per-node wall times from your self-hosted Langfuse (`http://langfuse.localhost`), 861 `dungeon_master` traces. The findings above are **measured, not estimated**. Summary of what the data confirmed/refuted:

- **Confirmed:** `dm_planner` is a TTFT blocker (19–26s, and 46s when it re-runs after a continuity rejection). `npc_executor` is the total-time killer (32–43s per NPC, sequential, ~half of multi-NPC turns).
- **Refuted:** Graphiti is **not** a bottleneck (0.24–1.01s) — my original §C concern was wrong, downgraded. `persist_messages` is negligible (0.05–0.07s) — §E downgraded.
- **New, unexpected:** `continuity_checker` is 8.8–22.9s despite `thinking_disabled=True` + 512 tokens — same cost as the planner, for a validation hop. And `intent_router` (same config) is 3–11s. Either nano-gpt is ignoring `thinking: disabled`, or these prompts are larger/slower than expected. See §H.
- **New:** within each NPC, `emotion_updater` (9–12s) and `planner`/thoughts (9–19s) run **sequentially before narration streams** — ~20–30s of pre-speech latency per NPC that can be parallelized for free. See §B2.
- **Outlier note:** the 1925s trace was 141s of real graph work — the rest was a background task holding the trace open. Treat trace `latency` with care; use the `dungeon_master` chain observation's duration for real turn time.

If you want deeper cuts (e.g. percentile distributions across all 861 traces, or per-trace TTFT vs total-time), I can pull more via the Langfuse CLI.

---

## Recommended sequence (re-prioritized from measured data)

1. **§A — cap planner reasoning** (`llm_models.py:66`, ~1 line). Biggest TTFT win, and tames the planner-redo cost too. Measure before/after on the same prompts.
2. **§H — investigate `continuity_checker` / `intent_router` expense.** First verify whether `thinking: disabled` is actually honored by nano-gpt (quick A/B in Langfuse). If not, that alone explains ~10–20s of wasted TTFT across two hops. Then trim the continuity prompt and stop re-planning on minor nits.
3. **§B — concurrent responding NPCs** (independent group first via `asyncio.gather`). Biggest total-time win (~half of multi-NPC turns).
4. **§B2 — ~~run `emotion_updater` || `planner` inside each NPC~~ DONE (Jul 8): removed both nodes, folded into the narrator prompt (`npc-narrator` v33).** ~18–31s of pre-narration LLM hops eliminated per NPC.
5. **§F — right-size models** for the streaming narration hops and the non-streaming classifier hops (smaller/faster model where prose quality isn't the priority).
6. **§D — decouple NPC build from existing-NPC responses** (only if NPC-introduction turns are a real slice of traffic; ~15s idle today).
7. **§G — durable queue for background jobs.** Reliability project; do when lost memory writes on restart or background-load contention starts biting.
8. **Skip §C (Graphiti) and §E (commit batching)** — measured negligible. Only revisit if traces change.
9. **Revisit microservices / MCP / RabbitMQ-for-the-turn-pipeline only if** a future requirement appears that they actually solve (independent scaling, external tool consumers, cross-team ownership) — never as a latency play.

Rough expected impact if you do 1–4: a 2-NPC turn currently ~140–165s could drop toward ~70–90s, with TTFT (time to first narration token) dropping from ~60–90s toward ~25–40s. These are projections — re-measure in Langfuse after each change.

