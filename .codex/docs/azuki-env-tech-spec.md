# Azuki TCG C Environment – Technical Specification

## 1. Architectural Overview
- **Language**: C11, compiled as static/shared lib consumed by Python bindings.
- **Core Modules**
  1. `types.h`: enums, constants, sizes (zones, limits, keywords, conditions).
  2. `cards.h`: `CardDef` (static card data) & `CardInstance` (runtime state).
  3. `effects.h` / `targets.h`: effect VM opcodes, selectors, condition predicates.
  4. `engine.h/.c`: game state container, turn loop, action execution, RNG.
  5. `actions.h`: `ActionType` enum + paramized action struct (multi-head interface).
  6. `puffer/azuki_puffer.h` & `puffer/binding.c`: PettingZoo/PufferLib bridge.
  7. `generated/cards_autogen.c/h`: generated card definitions (converter output).
  8. `tools/azuki_cards_convert.py`: JSON → `CardDef[]` transpiler (CSV unsupported in pipeline).
- **Design Goals**
  - Pure data-driven card set (no per-card hard-coding).
  - Deterministic RNG (PCG/xorshift) and zero dynamic allocations in hot path.
  - Explicit micro-state machine to support AEC (response windows, defender actions).
  - Comprehensive invariant checking (internal debug asserts + fuzz tests).

## 2. Game State Representation
### 2.1 Constants & IDs (from `types.h`)
| Constant | Value | Notes |
| --- | --- | --- |
| `AZK_MAX_PLAYERS` | 2 | Fixed two-player game |
| `AZK_MAX_GARDEN_SLOTS` / `AZK_MAX_ALLEY_SLOTS` | 5 | Board rows |
| `AZK_MAX_HAND` | 30 (tunable) | Generous upper bound; matches observation/action head sizing |
| `AZK_MAX_WEAPONS_PER_SLOT` | 4 | Multi-weapon attachments |
| `AZK_MAX_ABILITIES_PER_CARD` | e.g. 4 | per-card ability hooks |
| `AZK_MAX_EFFECT_PROG_LEN` | e.g. 16 | bytes per ability |
| `AZK_ID_NONE` | -1 | sentinel |

IDs use contiguous arrays; `InstanceId` indexes into `engine->instances` pool.

### 2.2 Static Card Definition (`CardDef`)
```c
typedef struct {
    CardType type;              // Leader|Gate|Entity|Weapon|Spell|IKZ
    const char* name;
    Element element;
    int8_t ikz_cost;            // -1 for leader/gate/IKZ
    int8_t gate_points;         // entities (set to -1 for cards without GP)
    struct { int8_t attack, health; } base;
    int8_t weapon_attack_bonus; // weapons
    uint32_t keyword_flags;     // charge|defender|carapace|infiltrate|godmode
    Ability abilities[AZK_MAX_ABILITIES_PER_CARD];
} CardDef;
```
`cards_autogen` populates these from JSON, mapping strings to enums/flags.

### 2.3 Runtime Instance (`CardInstance`)
```c
typedef struct {
    CardId def_id;
    InstanceId id;
    PlayerId owner;
    Zone zone;                  // deck|hand|garden|alley|ikz_area|ikz_pile|discard|stack
    int8_t slot_index;          // 0-4 for garden/alley, -1 otherwise
    uint8_t tapped;
    uint8_t cooldown;           // 1 = can’t tap this turn
    int8_t current_attack;
    int8_t current_health;
    uint32_t keyword_flags;     // dynamic (buffs)
    uint32_t conditions;        // frozen|shocked bitmask
    uint8_t weapon_count;
    InstanceId attached_weapons[AZK_MAX_WEAPONS_PER_SLOT];
} CardInstance;
```
- Attack/health recomputed from base + weapons + buffs each action.
- Attached weapon slots cleared and moved to discard during End phase.

### 2.4 Engine Container (`AzukiEngine`)
Key fields:
- Player-state arrays (per player):
  - `deck[50]`, `hand[AZK_MAX_HAND]`, `garden[5]`, `alley[5]`,
  - `ikz_pile[10]`, `ikz_area[10]`, `discard[51]`, `stack`.
- `leader_id`, `gate_id`, `ikz_token_played`.
- `phase`, `active_player`, `pending_response`, `response_owner`.
- `starting_player` cached after mulligan randomization for logging and resets.
- `combat_ctx` struct (attacker id, target kind/slot, damage cache).
- `stack` array maintains pending response spells/abilities (LIFO) during defender windows.
- RNG state (`uint64_t rng_state`).
- `Action last_action`, event log buffer (optional).
- `uint32_t turn_number`, `uint32_t step_counter` (for logs, determinism).
- Discard pile capacity (`discard[51]`) covers maximum 50-deck cards plus optional IKZ token once spent.

## 3. Turn & Micro-State Machine
```
PREGAME_MULLIGAN_P0
  -> A starting player is chosen randomly (dice-roll equivalent); treat them as player 0 for mulligan flow
  -> Active player selects MULLIGAN_KEEP or MULLIGAN_SHUFFLE
  -> Shuffle resolution if needed, draw 7
  -> Advance to PREGAME_MULLIGAN_P1

PREGAME_MULLIGAN_P1
  -> Opponent selects keep/shuffle
  -> Apply choice, draw 7
  -> Transition to START_OF_TURN with randomly selected starting player active

START_OF_TURN
  -> UNTAP all, clear shocked where timer expired
  -> Run start_of_turn abilities (VM)
  -> Draw 1 (deck-out check)
  -> Gain IKZ (add to IKZ area, apply P2 token on first turn)
  -> MAIN

MAIN (active player acts repeatedly)
  -> Accept actions: PLAY_*, PORTAL_GATE, ACTIVATE_ABILITY, ATTACK, END_TURN
  -> ATTACK transitions to COMBAT_DECLARED

COMBAT_DECLARED
  -> Validate attacker target
  -> Switch agent to defender, set `pending_response=1`
  -> RESPONSE_WINDOW

RESPONSE_WINDOW (defender acts once)
  -> Legal actions: NO_OP, PLAY_SPELL_RESPONSE, ACTIVATE_ABILITY(response timing), DECLARE_DEFENDER
  -> After action, resolve stack then go to COMBAT_RESOLVE

COMBAT_RESOLVE
  -> Execute combat damage (simultaneous), apply carapace, conditions
  -> Handle destroy/discard; check leader lethal (terminal)
  -> Run when_attacked / after_attacking hooks
  -> Response stack resolves LIFO once; no alternating priority beyond defender window
  -> Switch back to MAIN; if terminal -> END_MATCH

END_TURN
  -> Run end_of_turn abilities
  -> Reset entity damage to current max health
  -> Clear until-EOT flags, discard all weapons
  -> Switch active player, go to START_OF_TURN
```

## 4. Actions & Parameter Heads
`Action` struct:
```c
typedef struct {
    ActionType type;
    int32_t params[4]; // (p0, p1, p2, p3 placeholder)
} Action;
```
`ActionType` order (head 0):
```
0 NO_OP
1 PLAY_ENTITY_TO_GARDEN
2 PLAY_ENTITY_TO_ALLEY
3 PLAY_WEAPON
4 PLAY_SPELL_MAIN
5 PLAY_SPELL_RESPONSE
6 ATTACK
7 DECLARE_DEFENDER
8 PORTAL_GATE
9 ACTIVATE_ABILITY
10 END_TURN
11 MULLIGAN_KEEP
12 MULLIGAN_SHUFFLE
```
Head sizes are defined via macros (`AZK_HEAD0_SIZE`, `AZK_HEAD1_SIZE`, etc.) so adjusting limits (e.g., hand capacity) only requires tweaking constants in `types.h`.
Parameter semantics:
- `PLAY_ENTITY_TO_*`: `{hand_idx, slot_idx, replace_flag, _}`
- `PLAY_WEAPON`: `{hand_idx, target_kind(leader=0/entity=1), target_slot, _}`
- `PLAY_SPELL_MAIN/RESPONSE`: `{hand_idx, aux_idx (target slot/selector), _ , _}`
- `ATTACK`: `{attacker_slot, target_kind(0 leader/1 entity), target_slot, _}`
- `DECLARE_DEFENDER`: `{defender_slot, _ , _ , _}`
- `PORTAL_GATE`: `{alley_slot, target_garden_slot, _ , _}`
- `ACTIVATE_ABILITY`: `{instance_slot_or_id, ability_index, aux_target, _}`
- `NO_OP`, `END_TURN`, `MULLIGAN_*`: params ignored (set 0).

Legal masks per head must reflect current micro-state, resource availability, cooldown, keywords (e.g., infiltrate disables `DECLARE_DEFENDER`).

## 5. Effect Virtual Machine
### 5.1 Opcode Inventory
| Group | Opcodes (examples) |
| --- | --- |
| Costs | `OP_PAY_IKZ`, `OP_PAY_TAP_SELF`, `OP_PAY_SACRIFICE_SELF`, `OP_PAY_DISCARD` |
| Flow | `OP_CHOOSE_TARGET`, `OP_IF`, `OP_ENDIF`, `OP_ONCE_PER_TURN_GUARD` |
| Board Manip | `OP_TAP`, `OP_UNTAP`, `OP_MOVE_ZONE`, `OP_PORTAL`, `OP_DESTROY`, `OP_SACRIFICE`, `OP_BOTTOM_DECK` |
| Stats | `OP_DEAL_DAMAGE`, `OP_HEAL`, `OP_MOD_ATTACK`, `OP_ADD_KEYWORD`, `OP_REMOVE_KEYWORD`, `OP_ADD_CONDITION`, `OP_REMOVE_CONDITION`, `OP_SET_COOLDOWN` |
| Draw/Search | `OP_DRAW`, `OP_DISCARD`, `OP_SEARCH_DECK`, `OP_SHUFFLE` |
| Special | `OP_PAY_IKZ` with `p1` flag for gate-point scaling, etc. |

Programs are evaluated sequentially; illegal cost or missing target aborts ability without partial application.

### 5.2 Targeting & Conditions
- `targets.h` defines selectors (e.g., `ALLY_ENTITY_GARDEN`, `OPP_LEADER`, `LAST_TARGET`, `WEAPON_RECIPIENT`).
- Conditional flags (for `OP_IF`): `TARGET_IS_TAPPED`, `FIELD_GARDEN_FULL`, `SELF_HAS_CHARGE`, etc.
- Portal scaling: `OP_DEAL_DAMAGE` with `scale_gp` flag uses target entity’s Gate Points.
- Portal programs must cover:
  - Raizan Gate: after `OP_PORTAL`, search discard for weapons with cost ≤ Gate Points and auto-attach to portaled entity (using selectors and `MOVE_ZONE` to `WEAPON_ATTACH`).
  - Shao Gate: after `OP_PORTAL`, untap up to `gate_points` IKZ cards (`OP_UNTAP` with `max_by_gp` flag).

### 5.3 Once-Per-Turn Tracking
- `OP_ONCE_PER_TURN_GUARD` caches `(instance_id, ability_index)` in per-turn hash table; cleared during `START_OF_TURN`.

## 6. Resource & Keyword Rules
- **IKZ Economy**: IKZ area holds face-up cards; tapping pays costs; untapped each Start of Turn; IKZ token for second player once.
  - IKZ pile size fixed at 10 cards per deck; token is single-use and moves to discard (slot reserved) after spent.
- **Cooldown**: Entities entering Garden set `cooldown=1` unless they have `charge`; removed at next untap.
- **Keywords**:
  - `charge`: bypass cooldown.
  - `defender`: eligible for `DECLARE_DEFENDER`.
  - `carapace N`: subtract N from damage (min 0).
  - `infiltrate`: defender cannot retarget.
  - `godmode`: ignore leave-field from damage/effects.
- **Conditions**:
  - `frozen`: cannot attack, cannot be damaged, abilities disabled.
  - `shocked`: mark “skip next untap”.

## 7. Data Pipeline & Card Authoring
1. **Schema**: See `cards.schema.md` for fields and enum mappings.
2. **Source Format**: JSON dataset only (`cards.azuki.json`) with structured abilities.
3. **Converter** (`tools/azuki_cards_convert.py`):
   - Parses JSON, validates enums/keywords.
   - Serializes to `generated/cards_autogen.c/h` with `CardDef[]`.
   - Optionally outputs summary JSON for sanity checks.
4. **Integration**:
   - Include generated `.c` in CMake target.
   - `azk_create_engine` receives pointer to `CardDef` table + length.

## 8. Engine API Surface (`engine.h`)
```c
AzukiEngine* azk_create_engine(const AzkConfig* cfg,
                               const CardDef* defs,
                               size_t num_defs);
void azk_destroy_engine(AzukiEngine*);
void azk_reset(AzukiEngine*, const DeckList* p0, const DeckList* p1,
               CardId leader0, CardId leader1, CardId gate0, CardId gate1,
               uint64_t seed);
int azk_step(AzukiEngine*, const Action* action);      // returns status code
void azk_observe(const AzukiEngine*, PlayerId pid, float* out_obs);
void azk_legal_action_mask(const AzukiEngine*, PlayerId pid,
                           uint8_t* head0_mask, uint8_t* head1_mask,
                           uint8_t* head2_mask, uint8_t* head3_mask);
PlayerId azk_active_player(const AzukiEngine*);
Phase azk_phase(const AzukiEngine*);
int azk_is_terminal(const AzukiEngine*, PlayerId* winner);
```
- `DeckList` encodes 50-card main deck + IKZ mapping (e.g., card ids array).
- `azk_step` handles micro-state transitions internally (attack → response).
- Additional helpers: `azk_get_last_event`, `azk_export_log`, `azk_hash_state` (for testing).

## 9. Observations
- Flat float32 vector sized `AZK_OBS_LEN`.
- Layout (example):
  1. `phase_one_hot[4]`, `is_response_window`, `actor_is_defender`.
  2. Self leader features (atk, hp, max_hp, tapped, keywords mask, conditions mask).
  3. Opponent leader features (same layout but public only).
  4. Gate features (per player: tapped flag, counters, portal cooldown).
  5. Garden slots (self then opponent): for each of 5
     - `present`, one-hot element (7), attack, current HP, max HP, gate points,
       `tapped`, `cooldown`, `keywords_mask`, `conditions_mask`, `weapon_count`.
  6. Alley slots (same structure but no direct attack).
  7. Weapon summaries (optionally aggregated + max weapon bonus).
  8. IKZ features: self total, tapped count, pile remaining; opponent total (public), tapped (public).
  9. Hand encoding (private): top-K slots containing `[card_id_onehot or bucket, type, cost]`. Non-present entries masked with zero flag.
  10. Stack summary: size, top opcode category, attacker slot, defender slot.
- Observations normalized to [-1,1] or [0,1] consistent with spec; use macros for scaling to keep Python binding simple.

## 10. Legal Action Masks
- Implemented per head (head 0 is the main action type mask, heads 1–3 are auxiliary parameter masks):
  - **Head 0**: `uint8_t[13]`.
  - **Head 1**: sized to max parameter (e.g., 16 for hand slots).
  - **Head 2**: 8 (target kind/slot combos).
  - **Head 3**: 8 (spare/advanced usage).
- During response window:
  - Always set `mask0[ACT_NOOP] = 1`.
  - `ACT_DECLARE_DEFENDER` only if attacker lacks `infiltrate` and defender has keyword + untapped.
  - `ACT_PLAY_SPELL_RESPONSE` set if hand contains legal response spells with resources.
- During main phase, `ACT_NOOP` should be 0 to discourage stalling; `ACT_END_TURN` toggled 1.
- Masks zeroed out for inactive agent (non-turn player) via binding (see §11).

## 11. Binding & Integration (PufferLib / PettingZoo)
- **Buffers**:
  - Observations: `float32[AZK_OBS_LEN]`.
  - Actions: `int32[4]` (`type`, `p0`, `p1`, `p2`).
  - Rewards: `float32[1]`, Terminals: `bool[1]`, Truncations: `bool[1]`.
- **Binding Methods** (`puffer/binding.c`):
  - `env_init(obs, actions, rewards, terminals, truncations, seed, **kwargs)`.
  - `env_step(handle)` reads `actions` head, builds `Action`, calls `azk_step`, writes `rewards`, `terminals`, updates observation buffer.
  - `env_reset(handle, seed)` resets engine & buffers.
  - `env_get` returns dict with metadata: `obs_len`, `action_heads=4`, `action_head_sizes=[13,16,8,8]`, `mask_len=0` (until shared masks exported), `num_agents=2`, `is_response_window`, `actor_is_defender`, etc.
  - Optional `env_shared` to publish flattened masks if policy needs CPU-side mask ingestion.
- **PettingZoo Wrapper**:
  - Mirror TicTacToe template: manage agent ordering, apply flip-perspective if desired, and propagate legal masks in `infos`.
  - During defender response window, set `env.agent_selection` to defender; after `ACT_NOOP` or response, resume attacker flow.

## 12. Determinism & Logging
- RNG: single `uint64_t state`; functions `azk_rand_u32`, `azk_shuffle`.
- Seed via `AzkConfig.seed` or `env_reset`; starting player randomized (dice-roll equivalent) using RNG.
- Event Log Structure:
  ```
  struct AzkEvent {
      uint32_t step;
      PlayerId actor;
      Action action;
      uint32_t rng_before;
      uint32_t rng_after;
      uint32_t state_hash;
  };
  ```
- Logs used for reproducible replays and debugging (tie into `tests/test_determinism_and_fuzz`).

## 13. Testing Strategy
- **Unit Tests** (`tests/`):
  - `test_autogen_smoke`: include generated card table sanity checks.
  - `test_zones_init`, `test_turn_pipeline`, `test_costs`, … `test_weapons_multi`, `test_response_stack`, `test_conditions`, `test_effect_vm`, `test_masks`, `test_observation`, `test_noop_response`, `test_noop_vs_endturn`.
- **Fuzz Tests**:
  - Random legal action sampler verifying invariants (no duplicate occupancy, capacity, weapon limits, IKZ taps).
- **Determinism Regression**:
  - Hash end state after long random runs; ensure identical for same seed.
- **Performance Benchmark**:
  - `bench_steps`: 1e6 steps/time; assert below threshold.
- **Sanitizers**:
  - Address & Undefined sanitizers in CI; compile with `-O2 -g`.

## 14. Performance Considerations
- Preallocate arrays; maintain freelist for instances.
- Cache pointer to attacker/defender instances during combat to minimize lookups.
- Use bitfields/bitmasks for keywords/conditions for constant-time checks.
- Optionally maintain SoA for critical loops (attack resolution, mask building) post-MVP.
- Avoid branching by using lookup tables for mask assembly and keyword gating.

## 15. Error Handling & Debugging
- `azk_step` returns enum for `AZK_STEP_OK`, `AZK_STEP_ILLEGAL`, `AZK_STEP_TERMINAL`.
- In debug builds, `assert` invariants and print descriptive errors with state snapshot on failure.
- Provide `azk_dump_state(FILE*)` for diagnostics.
- Replay loader re-applies logged events to reproduce bugs.

## 16. Deployment & Packaging
- Build via CMake (existing skeleton).
- Produce shared library `.so` consumed by Python package (wheel).
- Install card data converter & schema docs alongside package.
- Provide `pkg-config` or CMake config for third-party integration once stabilized.

## 17. Open Questions / TODOs
- Finalize observation tensor size & normalization constants (document in binding + tests).
- Decide on card ability DSL timeline vs. manual JSON specification.
- Assess whether future rule updates require alternating response windows beyond current single defender action.
- Plan state serialization API for future save/load support.

---
**Maintainers**: Brandon, Codex Agent  
**Last Updated**: _2025-10-16_  
**Related Docs**: `azuki-product-spec.md`, `azuki-training-spec.md`, `azuki-env-milestones.md`, `cards.schema.md`
