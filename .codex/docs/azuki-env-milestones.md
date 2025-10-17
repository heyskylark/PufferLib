# Azuki Environment Milestones & Work Breakdown

This roadmap turns the GPT-generated build plan (M0–M18) into actionable chunks. Each milestone lists scope, key subtasks, deliverables, and validation steps. Execute sequentially unless otherwise noted.

| ID | Title | Core Outcome | Depends On |
| --- | --- | --- | --- |
| M0 | Data Autogen Wiring | Card converter integrated, card table loads into engine | None |
| M1 | Zone Layout & Instance Pool | All zones/containers + freelist structure | M0 |
| M2 | Turn Pipeline Skeleton | Start/Main/End phases without actions | M1 |
| M3 | Cost & Resource Handling | IKZ/tap/sacrifice cost enforcement | M2 |
| M4 | Card Play Mechanics | Entities/weapons/spells placement & cleanup | M3 |
| M5 | Cooldown & Charge | Tap gating for new entities | M4 |
| M6 | Attack Declaration | Basic combat targeting & defender hook | M5 |
| M7 | Damage & Win Logic | Damage resolution, carapace, terminal state | M6 |
| M8 | Gate & Portal System | Alley→Garden portal w/ GP scaling | M7 |
| M9 | Weapon Stack | Multi-weapon equip, stats, cleanup | M8 |
| M10 | Response Stack | LIFO stack for response spells/abilities | M9 |
| M11 | Negative Conditions | Frozen/shocked mechanics | M10 |
| M12 | Effect VM Core | Opcode execution across abilities | M11 |
| M13 | Legal Masks | Multi-head action masks per state | M12 |
| M14 | Observation Builder | Populate flat obs vector | M13 |
| M15 | Puffer Binding | env_binding compliance & metadata | M14 |
| M16 | Determinism & Fuzz | Random rollouts + invariant checks | M15 |
| M17 | Performance Benchmark | Step throughput & sanitizer runs | M16 |
| M18 | CLI & Replay (Stretch) | Replay runner + optional CLI | M17 |

## Milestone Details

### M0 — Data & Autogen Wiring
- **Tasks**
  - Run `tools/azuki_cards_convert.py` on `.codex/docs/azuki-tcg-cards.csv`.
  - Integrate generated `cards_autogen.c/h` into build system.
  - Implement `DeckList` loader referencing `CardId`.
- **Deliverables**: Compiled engine referencing card table, `tests/test_autogen_smoke.c`.
- **Validation**: Assert card count (e.g., 41 entries), spot-check Raizan/Surge definitions.

### M1 — Core State Layout
- **Tasks**
  - Define `AzukiEngine` struct, zones arrays, freelist for `CardInstance`.
  - Implement `azk_reset` skeleton (leaders/gates placed, decks shuffled).
- **Deliverables**: Engine creation/reset without actions.
- **Validation**: `tests/test_zones_init` (leaders in garden, unique occupancy).

### M2 — Turn Loop Skeleton
- **Tasks**
  - Implement phase enum, start/main/end transitions.
  - Hook start-of-turn actions: untap, draw, IKZ gain, IKZ token.
- **Deliverables**: Engine stepping `ACT_END_TURN` only.
- **Validation**: `tests/test_turn_pipeline` verifying draw counts, IKZ token rule.

### M3 — Costs & Payments
- **Tasks**
  - Implement IKZ tapping, sacrifice, discard, tap costs in VM + action helpers.
  - Illegal actions return error or are masked (later).
- **Deliverables**: Cost enforcement functions.
- **Validation**: `tests/test_costs` for insufficient IKZ/tap gating.

### M4 — Card Play Mechanics
- **Tasks**
  - Place entities into Garden/Alley with replacement logic.
  - Equip weapons, enforce slot limit, immediate ability triggers.
  - Play spells (resolve + discard).
- **Deliverables**: `azk_step` logic for `PLAY_*` actions.
- **Validation**: `tests/test_play_cards` covering slot replacement, weapon cleanup.

### M5 — Cooldown & Charge
- **Tasks**
  - Track cooldown bit; bypass when keyword `charge` present.
  - Update attacker gating to reference cooldown.
- **Validation**: `tests/test_cooldown_charge`.

### M6 — Attack Declaration & Defender Hook
- **Tasks**
  - Validate attack inputs; store combat context.
  - Expose response micro-state (defender turn).
- **Validation**: `tests/test_combat_targeting`.

### M7 — Damage Resolution & Terminal Checks
- **Tasks**
  - Simultaneous damage with carapace reduction.
  - Leader lethal detection, discard destroyed entities.
- **Validation**: `tests/test_damage_and_win`.

### M8 — Gate Portals & GP Scaling
- **Tasks**
  - Implement `ACT_PORTAL_GATE`; set cooldown, move zone.
  - Support `scale_gp` flag in VM ops (damage, heal, etc.).
- **Validation**: `tests/test_gate_portal`.

### M9 — Weapon Stack & Stat Aggregation
- **Tasks**
  - Manage `attached_weapons[]`, `weapon_count`, EOT discard.
  - Sum weapon bonuses into `current_attack`.
- **Validation**: `tests/test_weapons_multi`.

### M10 — Response Stack
- **Tasks**
  - Add stack structure for response spells/abilities.
  - Enforce defender single action before stack resolves.
- **Validation**: `tests/test_response_stack`.

### M11 — Conditions System
- **Tasks**
  - Implement `frozen`, `shocked` semantics (ability suppression, untap skip).
  - Ensure damage prevention for frozen units.
- **Validation**: `tests/test_conditions`.

### M12 — Effect VM Core
- **Tasks**
  - Implement opcode dispatcher (costs, board moves, stats, control flow).
  - Support once-per-turn guard table.
- **Validation**: `tests/test_effect_vm` (scripted mini-programs).

### M13 — Legal Action Masks
- **Tasks**
  - Build per-head mask arrays across micro-states.
  - Ensure NO_OP only in response/micro prompts.
- **Validation**: `tests/test_masks`, `tests/test_noop_response`, `tests/test_noop_vs_endturn`.

### M14 — Observation Vector
- **Tasks**
  - Populate observation layout (leaders, fields, IKZ, hand, flags).
  - Provide normalization constants & documentation.
- **Validation**: `tests/test_observation`.

### M15 — Puffer Binding
- **Tasks**
  - Implement `my_init`, `my_step`, `my_reset`, `my_get`, optional `my_shared`.
  - Align metadata with multi-head sizes, supply masks via infos/shared.
- **Validation**: `tests/test_puffer_binding` (ABI round trips).

### M16 — Determinism & Fuzz Harness
- **Tasks**
  - Random legal action generator, invariants checks.
  - Deterministic hash comparison for identical seeds.
- **Validation**: `tests/test_determinism_and_fuzz`.

### M17 — Performance & Sanitizers
- **Tasks**
  - Benchmark no-op & typical actions (≥1e6 steps/min target).
  - Run AddressSanitizer + UBSan builds.
- **Validation**: `tests/bench_steps` + CI sanitizer runs.

### M18 — CLI & Replay (Stretch)
- **Tasks**
  - Text-mode CLI for manual play or log playback.
  - Replay runner verifying end-state hash = logged hash.
- **Validation**: Manual smoke test + `tests/test_replay_roundtrip`.

## Weekly Cadence Example
1. **Week 1**: M0–M2 (data + skeleton).
2. **Week 2**: M3–M5 (costs, plays, cooldown).
3. **Week 3**: M6–M9 (combat core, weapons).
4. **Week 4**: M10–M12 (response + VM).
5. **Week 5**: M13–M16 (masks, obs, binding, fuzz).
6. **Week 6**: M17–M18 (performance, replay, polish).

Adjust pacing based on complexity; regression tests must pass before advancing.

## Tracking & Documentation
- Update project kanban or issue tracker per milestone.
- Record test results + notes in `docs/changelogs/M{N}.md` (optional).
- Maintain changelog of card schema updates synced with converter version.

---
**Owner**: Brandon  
**Last Updated**: _2025-10-16_  
**Related Docs**: `azuki-env-tech-spec.md`, `azuki-training-spec.md`, `azuki-product-spec.md`
