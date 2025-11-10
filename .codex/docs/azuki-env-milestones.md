# Azuki Environment Milestones & Work Breakdown

This roadmap turns the GPT-generated build plan (M0–M18) into actionable chunks and appends Raylib/Web deliverables (M20–M21). Each milestone lists scope, key subtasks, deliverables, and validation steps. Execute sequentially unless otherwise noted.

| ID | Title | Core Outcome | Depends On |
| --- | --- | --- | --- |
| M0 | Data Autogen Wiring | JSON converter integrated, card table loads into engine | None |
| M1 | ECS Core & Zone Layout | Flecs world scaffolding + zone/instance pool wiring | M0 |
| M2 | Turn Pipeline Skeleton | Start/Main/End phases scheduled as ECS systems | M1 |
| M3 | Intent & Cost Systems | IKZ/tap/sacrifice enforcement + action→intent bridge | M2 |
| M4 | Card Play Mechanics | Entities/weapons/spells placement & cleanup | M3 |
| M5 | Cooldown & Charge | Tap gating via components; charge bypass verified | M4 |
| M6 | Attack Declaration | Combat targeting, defender micro-state events | M5 |
| M7 | Damage & Win Logic | Damage resolution, carapace, leader lethal | M6 |
| M8 | Gate & Portal System | Alley→Garden portal with GP scaling | M7 |
| M9 | Weapon Stack | Multi-weapon equip, stat aggregation, cleanup | M8 |
| M10 | Response Stack | LIFO stack for response spells/abilities | M9 |
| M11 | Conditions & Keywords | Frozen/shocked/keyword tags hooked into ECS queries | M10 |
| M12 | Effect VM Core | Opcode execution across abilities | M11 |
| M13 | Legal Masks | Multi-head action masks driven by ECS queries | M12 |
| M14 | Observation Builder | Populate flat obs vector from ECS state | M13 |
| M15 | Ports & Event Bus | Intent/event queues + serialization helpers | M14 |
| M16 | Puffer Binding | env_binding compliance & metadata | M15 |
| M17 | Determinism & Fuzz | Random rollouts + invariant checks | M16 |
| M18 | Performance Benchmark | Step throughput & sanitizer runs | M17 |
| M19 | CLI & Replay (Stretch) | Replay runner + optional CLI | M18 |
| M20 | Raylib Harness (Desktop) | Event-driven renderer + dev overlays | M15 |
| M21 | WebAssembly Build | PLATFORM_WEB pipeline, asset preload, emrun smoke test | M20 |

## Milestone Details

### M0 — Data & Autogen Wiring
- **Tasks**
  - Author `data/cards.azuki.json` using schema.
  - Run `tools/azuki_cards_convert.py --format json` to emit `cards_autogen.c/h`.
  - Integrate generated sources into build system.
- **Deliverables**: Compiled engine referencing JSON-driven card table, `tests/test_autogen_smoke.c`.
- **Validation**: Assert card counts (Raizan + Shao decks), spot-check leader/gate defs.

### M1 — ECS Core & Zone Layout
- **Tasks**
  - Stand up a Flecs world (or equivalent) and register foundational components (`Stats`, `ComputedStats`, `Keywords`, `Conditions`, `Owner`, `Zone`, `Tapped`, `Cooldown`).
  - Implement zone arrays + freelist storing ECS entity ids (while still hosting `CardInstance` structs for serialization).
  - Build `azk_reset` skeleton that spawns leaders/gates, seeds decks, and mirrors entities into the ECS world.
- **Deliverables**: Engine creation/reset wiring ECS + canonical arrays.
- **Validation**: `tests/test_zones_init` (leaders in garden, unique occupancy, ECS entity counts match zone occupancy).

### M2 — Turn Pipeline Skeleton
- **Tasks**
  - Implement phase enum + ECS system schedule (`StartPhaseSystem`, `MainPhaseSystem`, `EndPhaseSystem`).
  - Wire start-of-turn hooks (untap, draw, IKZ gain/token) as systems that operate purely on ECS components.
- **Deliverables**: Engine stepping `ACT_END_TURN` only while phases advance deterministically.
- **Validation**: `tests/test_turn_pipeline` verifying draw counts, IKZ token rule, and ECS phase flags.

### M3 — Intent & Cost Systems
- **Tasks**
  - Translate multi-head actions into ECS `Intent` components (attacker, card id, slot targets).
  - Implement IKZ tapping, sacrifice, discard, tap costs as dedicated systems that validate/manipulate ECS state before intents resolve.
  - Ensure illegal costs bubble up as `AZK_STEP_ILLEGAL` (used later by mask builder).
- **Deliverables**: Intent dispatcher + cost enforcement functions.
- **Validation**: `tests/test_costs` for insufficient IKZ/tap gating, plus intent serialization round trips.

### M4 — Card Play Mechanics
- **Tasks**
  - Place entities into Garden/Alley with replacement logic (updates both arrays + ECS Zone component).
  - Equip weapons, enforce slot limit, immediate ability triggers; weapon attachments become ECS child entities with bonuses.
  - Play spells (resolve + discard) by queuing effect programs + event entries.
- **Deliverables**: `azk_step` logic for `PLAY_*` actions backed by ECS updates.
- **Validation**: `tests/test_play_cards` covering slot replacement, weapon cleanup.

### M5 — Cooldown & Charge
- **Tasks**
  - Track cooldown via ECS `Cooldown` component; auto-attach on summon and clear in `StartPhaseSystem`.
  - Update attacker gating + intent validation to respect `Cooldown` or `Charge` tags.
- **Validation**: `tests/test_cooldown_charge`.

### M6 — Attack Declaration & Defender Hook
- **Tasks**
  - Validate attack inputs; store combat context in ECS (`CombatCtx` component) plus canonical struct.
  - Emit `EV_RESPONSE_REQUESTED` event + toggle defender response window via ECS tags.
- **Validation**: `tests/test_combat_targeting`.

### M7 — Damage Resolution & Terminal Checks
- **Tasks**
  - Implement `DamageSystem` that processes `Damage` components, applies carapace reduction, and emits `DamageApplied`.
  - Leader lethal detection, discard destroyed entities, and attach `DeadTag` for later cleanup.
- **Validation**: `tests/test_damage_and_win`.

### M8 — Gate Portals & GP Scaling
- **Tasks**
  - Implement `ACT_PORTAL_GATE`; set cooldown via ECS `PortalCooldown`, move zone/slot occupancy.
  - Support `scale_gp` flag in VM ops and ECS aura recalcs (damage/heal scaling).
- **Validation**: `tests/test_gate_portal`.

### M9 — Weapon Stack & Stat Aggregation
- **Tasks**
  - Manage `attached_weapons[]`, `weapon_count`, EOT discard + removal from ECS.
  - Sum weapon bonuses into `ComputedStats` via `AuraSystem`.
- **Validation**: `tests/test_weapons_multi`.

### M10 — Response Stack
- **Tasks**
  - Add stack structure for response spells/abilities.
  - Enforce defender single action before stack resolves; emit `EV_RESPONSE_RESOLVED`.
- **Validation**: `tests/test_response_stack`.

### M11 — Conditions & Keyword Tags
- **Tasks**
  - Implement `frozen`, `shocked`, and keyword-derived tags as ECS components (tied to observation + masks).
  - Ensure damage/ability prevention for frozen units and shocked untap skips.
- **Validation**: `tests/test_conditions`.

### M12 — Effect VM Core
- **Tasks**
  - Implement opcode dispatcher (costs, board moves, stats, control flow).
  - Support once-per-turn guard table.
- **Validation**: `tests/test_effect_vm` (scripted mini-programs).

### M13 — Legal Action Masks
- **Tasks**
  - Build per-head mask arrays by querying ECS (hands, slots, keywords, IKZ availability).
  - Ensure NO_OP only in response/micro prompts; export mask metadata for bindings.
- **Validation**: `tests/test_masks`, `tests/test_noop_response`, `tests/test_noop_vs_endturn`.

### M14 — Observation Vector
- **Tasks**
  - Populate observation layout (leaders, fields, IKZ, hand, flags) directly from ECS queries/iterators.
  - Provide normalization constants & documentation.
- **Validation**: `tests/test_observation`.

### M15 — Ports & Event Bus
- **Tasks**
  - Define `AzkEvent` schema + ring buffer; emit events at each system boundary (`DamageApplied`, `CardPlayed`, etc.).
  - Implement `azk_step_until_idle` that drains pending intents, processes ECS systems, and flushes events/state hashes.
  - Provide serialization helpers (`azk_serialize`, `azk_deserialize`, `azk_state_hash`) for adapters/replays.
- **Validation**: `tests/test_event_stream` (expected sequence for scripted turns) + snapshot/restore round trips.

### M16 — Puffer Binding
- **Tasks**
  - Implement `my_init`, `my_step`, `my_reset`, `my_get`, optional `my_shared`.
  - Align metadata with multi-head sizes, supply masks via infos/shared.
- **Validation**: `tests/test_puffer_binding` (ABI round trips).

### M17 — Determinism & Fuzz Harness
- **Tasks**
  - Random legal action generator, invariants checks.
  - Deterministic hash comparison for identical seeds.
- **Validation**: `tests/test_determinism_and_fuzz`.

### M18 — Performance & Sanitizers
- **Tasks**
  - Benchmark no-op & typical actions (≥1e6 steps/min target).
  - Run AddressSanitizer + UBSan builds.
- **Validation**: `tests/bench_steps` + CI sanitizer runs.

### M19 — CLI & Replay (Stretch)
- **Tasks**
  - Text-mode CLI for manual play or log playback.
  - Replay runner verifying end-state hash = logged hash.
- **Validation**: Manual smoke test + `tests/test_replay_roundtrip`.

### M20 — Raylib Harness (Desktop)
- **Tasks**
  - Implement a lightweight raylib client that consumes the core event queue, renders board/hand UI, and plays simple tweens (draw, attack, damage numbers).
  - Integrate `raygui` for menus and `rlImGui` for developer inspectors (entity/component view, mask inspector).
  - Ensure adapter stays decoupled: UI-only ECS or structs live in `clients/raylib/` and never leak back into the core.
- **Validation**: Manual smoke (desktop build) verifying draw/play/attack flows stay in sync with headless log hashes; optional screenshot diff in CI.

### M21 — WebAssembly Build
- **Tasks**
  - Add `wasm-debug`/`wasm-release` CMake presets that link against `raylib` built with `PLATFORM_WEB` and compile via `emcc` (flags from tech spec).
  - Package assets via `--preload-file assets@/assets`, enable `-sASYNCIFY`, and document `emrun --no_browser --port 8080` workflow.
  - Verify audio/input constraints (user-gesture gating) and ensure deterministic seed can be passed via JS glue.
- **Validation**: `scripts/build_web.sh` (or preset) emits `index.html/.wasm/.js`; `emrun` smoke test plus automated check ensuring observation/actions still round-trip in the browser build (mocked via headless `node --experimental-wasm-*` if possible).

## Weekly Cadence Example
1. **Week 1**: M0–M2 (data ingest + ECS skeleton).
2. **Week 2**: M3–M5 (intent bridge, plays, cooldown).
3. **Week 3**: M6–M9 (combat core, weapons).
4. **Week 4**: M10–M12 (response stack + VM).
5. **Week 5**: M13–M16 (masks, obs, event bus, binding).
6. **Week 6**: M17–M19 (determinism, perf, CLI/replay polish).
7. **Week 7**: M20–M21 (raylib desktop harness + WebAssembly pipeline).

Adjust pacing based on complexity; regression tests must pass before advancing.

## Tracking & Documentation
- Update project kanban or issue tracker per milestone.
- Record test results + notes in `docs/changelogs/M{N}.md` (optional).
- Maintain changelog of card schema updates synced with converter version.

---
**Owner**: Brandon  
**Last Updated**: _2025-10-25_  
**Related Docs**: `azuki-env-tech-spec.md`, `azuki-training-spec.md`, `azuki-product-spec.md`
