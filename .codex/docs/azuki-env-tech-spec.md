# Azuki TCG C Environment – Technical Specification

## 1. Architectural Overview
- **Language**: C11, compiled as static/shared lib consumed by Python bindings and a thin Raylib client.
- **Core Modules**
  1. `types.h`: enums, constants, sizes (zones, limits, keywords, conditions).
  2. `cards.h`: `CardDef` (static card data) & `CardInstance` (runtime state).
  3. `effects.h` / `targets.h`: effect VM opcodes, selectors, condition predicates.
  4. `engine.h/.c`: game state container, turn loop, action execution, RNG.
  5. `actions.h`: `ActionType` enum + paramized action struct (multi-head interface).
  6. `ecs/components.h`, `ecs/systems_*.c`: Flecs-friendly ECS definitions for statuses, query filters, damage/death, aura recalcs, mask staging, and event emission.
  7. `puffer/azuki_puffer.h` & `puffer/binding.c`: PettingZoo/PufferLib bridge plus C ABI used by future Python+Raylib clients.
  8. `generated/cards_autogen.c/h`: generated card definitions (converter output).
  9. `tools/azuki_cards_convert.py`: JSON → `CardDef[]` transpiler (CSV unsupported in pipeline).
 10. `clients/raylib/` (planned): event-driven renderer built on raylib/raygui consuming the core’s event queue; compiled for desktop and WebAssembly.
- **Design Goals**
  - Pure data-driven card set (no per-card hard-coding).
  - Deterministic RNG (PCG/xorshift) and zero dynamic allocations in hot path.
  - Explicit micro-state machine to support AEC (response windows, defender actions).
  - ECS-based composition for mechanics (taunt, lifesteal, auras, freezes) so new keywords map to components/systems, not ad-hoc conditionals.
  - Core emits semantic events that downstream adapters (RL bindings, raylib renderer, network server) consume at their own cadence.
  - Comprehensive invariant checking (internal debug asserts + fuzz tests).

### 1.1 Build Targets & Toolchain
- **Build system**: CMake + Presets (`native-debug`, `native-release`, `wasm-debug`, `wasm-release`). Presets toggle sanitizer flags, Flecs build options, and Raylib linkage.
- **Dependencies**:
  - `raylib` (graphics/input/audio) compiled twice: `PLATFORM_DESKTOP` for native harness and `PLATFORM_WEB` (via `emsdk`) for browser builds.
  - `flecs` (ECS runtime), vendored or pulled via CMake `FetchContent`.
  - `cJSON` (card data ingestion), `uthash` (registries/lookups).
  - `raygui` (ship-ready UI widgets) and `rlImGui` (dev overlay) for the raylib harness.
  - Asset helpers (external tooling): `rGuiLayout`, `rTexPacker`, `rFXGen`, `msdf-atlas-gen` for UI layout, atlases, sfx, and crisp fonts.
  - `Emscripten SDK` for Web builds (`emcc`, `emrun`, `file packager`).
- **WASM flow**:
  1. Install/activate `emsdk` (`./emsdk install/activate latest && source emsdk_env.sh`).
  2. Build raylib for web: `cd raylib/src && make -e PLATFORM=PLATFORM_WEB -B` (set `EMSDK_PATH` if needed).
  3. Compile client/core bundle:
     ```sh
     emcc -o index.html \
       src/main.c src/raylib_client.c \
       -Iraylib/src -Lraylib/src -lraylib \
       -DPLATFORM_WEB -sUSE_GLFW=3 -sASYNCIFY \
       -sMIN_WEBGL_VERSION=2 -sMAX_WEBGL_VERSION=2 \
       -sALLOW_MEMORY_GROWTH=1 \
       --preload-file assets@/assets
     ```
  4. Run locally with `emrun --no_browser --port 8080 index.html` (or any HTTP server).
  - Notes: preload assets referenced by `Load*()`; browsers require HTTPS/HTTP (no `file://`); audio + blocking file I/O must respect Emscripten constraints.

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

### 2.5 ECS Component Model
- **Runtime ECS**: `flecs` (or equivalent) mirrors the canonical arrays so combat/status logic stays composable. Each `CardInstance` owns an ECS entity id; zone arrays store entity refs instead of fat structs when possible.
- **Core components**:
  - `Stats{base_atk, base_hp, gate_points}`, `ComputedStats{atk, hp, max_hp}` recalculated post-auras.
  - `Keywords{mask}`, `Conditions{mask}`, `Cooldown{ticks}`, `Tapped{bool}`.
  - `Damage{amount, source}`, `Heal{amount, source}`, `DeadTag{}` as transient markers.
  - `AuraEmitter{atk_delta, hp_delta, filter}`, `AuraTarget{}` plus `AuraCache` storing resolved buffs.
  - `Lifesteal{}` / `Poisonous{}` / `Defender{}` / `Infiltrate{}` as tag components, mapping 1:1 to keyword flags.
  - `Targetable{mask}` + `ResponseWindow{owner}` to drive defender choices.
  - `EventBuffer` singleton storing last emitted `Event` array; `Intent` records pending player action (translates multi-head action into ECS components).
- **Systems (ordered schedule)**:
  1. `DrawSystem` / `IKZSystem` (start-of-turn economy updates).
  2. `TargetingSystem` toggling `Targetable` and `DefenderEligible` tags (taunt/stealth/infiltrate logic).
  3. `PlaySystem` (entities/weapons/spells) writing high-level `Action` results into ECS.
  4. `AuraSystem` recomputing `ComputedStats` whenever `AuraEmitter` or zone membership changes.
  5. `DamageSystem` consumes `Damage` component → applies HP deltas, emits `DamageApplied` events.
  6. `DeathSystem` processes `DeadTag`, moves entities to discard, runs deathrattles via VM.
  7. `CleanupSystem` clears transient components (`Damage`, `Heal`, `Intent`, once-per-turn guards).
  8. `MaskSystem` & `ObservationSystem` read ECS state to build action masks/observations without branching on raw arrays.
  9. `EventEmitSystem` flushes semantic events to the adapter queue.
- **Advantages**:
  - Adding a mechanic = new component + localized system (e.g., `FreezeSystem`, `PortalCooldownSystem`).
  - Systems are testable in isolation; RL headless sim spins them without any render dependencies.
  - The same ECS data feeds the raylib client for hover/highlight logic without duplicating state.

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

## 11.5 Ports, Event Bus & Adapters
- **Core API**: strict trio of functions for simulators/UI/server: `reset(seed)`, `apply_intent(Intent*)`, `step_until_idle()` (process actions until queue empty). Each call returns:
  - `Event events[MAX_EVENTS_PER_STEP]`
  - `size_t event_count`
  - `uint64_t rng_state_before/after`
  - `uint64_t state_hash` (for validation/replays).
- **Event schema** (subset):
  | Type | Payload |
  | --- | --- |
  | `EV_CARD_DRAWN` | `{player, instance_id, deck_position}` |
  | `EV_CARD_PLAYED` | `{player, zone, slot, card_id}` |
  | `EV_DAMAGE_APPLIED` | `{source, target, amount, lethal}` |
  | `EV_STATUS_APPLIED` | `{target, status_mask}` |
  | `EV_ENTITY_DIED` | `{instance_id, zone}` |
  | `EV_TURN_STARTED/ENDED` | `{player, turn_number}` |
  | `EV_RESPONSE_REQUESTED` | `{attacker, defender_owner, window_id}` |
- **Adapters**:
  - **RL/PufferLib**: consumes observations immediately; optional event feed saved for dataset generation and debugging.
  - **Raylib client (desktop + web)**: drives tweens/particle timelines from events while the core keeps sim time separate from render time. UI state (hover, drag, selection) lives entirely client-side and never feeds back into the core except via validated intents.
  - **Server / Online play**: authoritative loop re-runs the same core, only transmitting intents and authoritative events/state hashes to clients (lockstep or turn-based RPC).
- **Snapshot & restore**: `cg_serialize`/`cg_deserialize` operate on the ECS world + canonical arrays for RL vectorization and multiplayer rollback.
- **Threading model**: core remains single-threaded/deterministic; adapters may multi-thread but must serialize intents before calling into the core.

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
- **CMake Presets**:
  - `native-debug`: Address/Undefined sanitizers, asserts on.
  - `native-release`: `-O3 -march=native`, headless benchmarks.
  - `wasm-debug` / `wasm-release`: cross-compiles raylib client + core through Emscripten; injects `-DPLATFORM_WEB`, `-sUSE_GLFW=3`, `-sASYNCIFY`, `-sMIN_WEBGL_VERSION=2`, `-sMAX_WEBGL_VERSION=2`, `-sALLOW_MEMORY_GROWTH=1`.
- **Artifacts**:
  - `libazuki_core.a/.so`: consumed by Python bindings and potential servers.
  - `libazuki_core_wasm.a` + `index.{html,wasm,js}`: raylib harness for browsers.
  - Python wheel bundles shared lib + bindings + generated `CardDef` table + schema docs.
- **Raylib desktop build**: link against vendored `raylib-5.5_linux_amd64` archives for CLI smoke tests; keep out of RL wheels.
- **Raylib web build**:
  1. `git clone https://github.com/emscripten-core/emsdk && ./emsdk install/activate latest && source emsdk_env.sh`.
  2. `cd raylib/src && make -e PLATFORM=PLATFORM_WEB -B` (set `EMSDK_PATH`, optionally `PYTHON_PATH`).
  3. `cmake --preset wasm-release && cmake --build --preset wasm-release` (wraps the `emcc` command shown in §1.1).
  4. `emrun --no_browser --port 8080 build/wasm-release/index.html` or serve via any static HTTP server (mandatory—`file://` won’t load due to browser sandboxing).
  5. Package `assets/` via `--preload-file assets@/assets` (or `--embed-file` for tiny payloads). Large packs should be chunked to keep startup times reasonable.
  6. Expect audio quirks: browsers require user interaction before playback; asynchronous file APIs necessitate `-sASYNCIFY` for blocking code.
- **Tooling distribution**: ship `tools/azuki_cards_convert.py`, `cards.schema.md`, and documented `cmake --preset` flows; keep optional UI tooling references (rGuiLayout, rTexPacker, rFXGen) in docs rather than the wheel.
- **Integration**: provide `pkg-config` or CMake `find_package(AzukiCore)` once API stabilizes; document WebSocket/intent format for future net-play adapters.

## 17. Open Questions / TODOs
- Finalize observation tensor size & normalization constants (document in binding + tests).
- Decide on card ability DSL timeline vs. manual JSON specification.
- Assess whether future rule updates require alternating response windows beyond current single defender action.
- Plan state serialization API for future save/load support.
- Choose final ECS implementation strategy (vanilla Flecs vs. custom SoA reducer) and document how it coexists with array-based snapshotting.
- Lock down event payload schema (IDs, batching, text for tooltips) so raylib, network, and RL logging adapters never diverge.
- Define how Web builds fetch/preload large art assets (single pack vs. segmented, compression strategy).
- Validate whether UI-only ECS (render/FX) should live inside the same repo or downstream consumer to keep this package lightweight.

---
**Maintainers**: Brandon, Codex Agent  
**Last Updated**: _2025-10-25_  
**Related Docs**: `azuki-product-spec.md`, `azuki-training-spec.md`, `azuki-env-milestones.md`, `cards.schema.md`
