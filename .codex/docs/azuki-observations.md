# Observations

## Perspective & Encoding Guidelines
- Observations are built from the viewpoint of the currently acting agent. Arrays and sets are always ordered `self` first, `opponent` second (or top-to-bottom for stacks). The policy can rely on this ordering rather than explicit owner flags.
- Hidden information stays hidden: provide full detail for the acting player’s hand, IKZ pile order, and once-per-turn trackers; only public or count-level information is exposed for the opponent.
- Numeric features should be normalized (e.g., divide counts by their `types.h` maxima) before PPO ingestion unless downstream layers perform their own scaling.
- Categorical fields are provided as stable enum indices intended for learned embeddings rather than one-hot vectors.
- When a slot in a fixed-length structure is empty, emit all zeros for that slot. This applies to hand, garden, alley, discard, weapon attachment, and stack entries.
- Unordered sets (hand, alley, garden, discard, attached weapons, stack) are consumed by a `process_set` helper: run each element through a 2-layer MLP (size NxK → NxS) and max-pool across the set to obtain a pooled embedding of size `S`. Per-element features listed below are the inputs to that helper.

## Global Scalars (single vector)
| Feature | Description | Type | Notes / Encoding |
| --- | --- | --- | --- |
| `turn_number` | Full turns elapsed | real | Normalize by turn cap (default 60). |
| `step_counter` | Engine steps since reset | real | Useful for replay/debug alignment. |
| `phase` | Micro-state enum (`PREGAME_MULLIGAN_P0`, …, `END_MATCH`) | categorical (embedding) | Enum order defined in `engine.h`. |
| `active_player_is_self` | Agent is the active player this micro-step | boolean | |
| `pending_response` | Response window currently open | boolean | |
| `response_owner_is_self` | Agent must act during the response window | boolean | |
| `starting_player_is_self` | Tracks who won the opening roll | boolean | Constant after mulligan. |
| `stack_depth` | Pending spells/abilities on stack | real | Normalize by `AZK_MAX_STACK`. |
| `last_action_type` | Resolved `ActionType` from prior step | categorical (embedding) | 13-action enum. |
| `last_action_was_self` | Prior resolved action belonged to agent | boolean | |
| `illegal_action_flag` | 1 if previous request was rejected/masked | boolean | Instrumentation for debugging. |

## Combat Context (active when `phase` is combat related)
| Feature | Description | Type | Notes |
| --- | --- | --- | --- |
| `combat_active` | Phase is `COMBAT_DECLARED`, `RESPONSE_WINDOW`, or `COMBAT_RESOLVE` | boolean | Gates the rest of the block. |
| `attacker_slot_index` | Garden slot index of attacker (0–4); leaders use sentinel 5 | categorical (embedding) | |
| `attacker_card_id` | Card definition index of attacker | categorical (embedding) | |
| `attacker_attack_cached` | Attack value cached at declaration | real | Normalize by dataset max attack. |
| `attacker_keyword_bits` | Charge/defender/carapace/infiltrate/godmode flags | boolean (5) | Derived from keyword mask. |
| `target_is_leader` | Defender is a leader (otherwise an entity slot) | boolean | |
| `target_slot_index` | Garden slot index if defender is an entity | categorical (embedding) | Use sentinel 5 for leader. |
| `target_card_id` | Defender card definition | categorical (embedding) | |
| `target_current_health` | Defender current health | real | Normalize by max health. |
| `predicted_damage_to_target` | Damage attacker will apply post-modifiers | real | Cached during declaration. |
| `defender_can_redirect` | Untapped defender keyword entity available | boolean | Summarizes redirect possibility. |

## Per-Player Summary (ordered: self, opponent)
| Feature | Description | Type | Notes |
| --- | --- | --- | --- |
| `hand_size` | Number of cards in hand | real | Normalize by `AZK_MAX_HAND`. |
| `deck_size` | Cards remaining in deck | real | |
| `discard_count` | Cards currently in discard pile | real | Normalize by 50. |
| `ikz_pile_remaining` | IKZ cards left in pile | real | Normalize by 10. |
| `ikz_untapped` | Untapped IKZ in play | real | |
| `ikz_tapped` | Tapped IKZ in play | real | |
| `ikz_token_available` | IKZ token not yet spent | boolean | |
| `gate_portal_available` | Gate ability ready this turn | boolean | Accounts for tap status + once/turn guard. |
| `start_of_turn_triggers_pending` | Number of queued start-of-turn triggers | real | Zero for opponent if hidden. |
| `garden_occupancy` | Garden entities including leader | real | Normalize by 6. |
| `alley_occupancy` | Alley entities | real | Normalize by 5. |
| `weapons_attached_total` | Weapons controlled by the player | real | |
| `response_spells_known` | Response-speed spells known to be available | real | Count full info for self; public info for opponent (0 or revealed count). |

## Self Hand Cards (`AZK_MAX_HAND` entries → process_set)
| Feature | Description | Type | Notes |
| --- | --- | --- | --- |
| `card_id` | Card definition index | categorical (embedding) | Zero for empty slot. |
| `card_type` | Enum (Entity, Weapon, Spell, IKZ) | categorical (embedding) | |
| `element` | Element enum | categorical (embedding) | |
| `ikz_cost` | IKZ cost to play | real | Zero for IKZ/leader/gate. |
| `base_attack` | Base attack (entities only) | real | |
| `base_health` | Base health (entities only) | real | |
| `gate_points` | Entity gate points | real | |
| `weapon_attack_bonus` | Weapon attack bonus | real | |
| `spell_timing` | Enum (main, response, both) | categorical (embedding) | Provide `both` for flexible spells. |
| `keyword_bits` | Charge/defender/carapace/infiltrate/godmode | boolean (5) | |
| `ability_timing_bits` | on_play/start/end/response/... timing flags | boolean (≤12) | Align with effect metadata. |
| `once_per_turn_ready_bits` | Once/turn abilities unused | boolean (≤4) | Mirrors ability order in card definition. |

## Leaders (ordered: self, opponent)
| Feature | Description | Type | Notes |
| --- | --- | --- | --- |
| `card_id` | Leader definition | categorical (embedding) | |
| `current_health` | Leader health | real | Normalize by max leader health. |
| `max_health` | Maximum leader health | real | |
| `tapped` | Leader is tapped | boolean | |
| `attack_current` | Current attack after weapons/effects | real | |
| `keyword_bits` | Charge/defender/carapace/infiltrate/godmode | boolean (5) | |
| `frozen` | Frozen condition flag | boolean | |
| `shocked` | Shocked condition flag | boolean | |
| `weapon_count` | Attached weapons | real | |
| `weapon_attack_bonus_total` | Sum of weapon bonuses | real | |
| `ability_ready_bits` | Once-per-turn readiness per leader ability | boolean (≤4) | |

## Gates (ordered: self, opponent)
| Feature | Description | Type | Notes |
| --- | --- | --- | --- |
| `card_id` | Gate definition | categorical (embedding) | |
| `tapped` | Gate tapped (portal already used) | boolean | |
| `keyword_bits` | Gate keywords | boolean (5) | |
| `frozen` | Frozen condition flag | boolean | |
| `shocked` | Shocked condition flag | boolean | |
| `portal_cooldown` | Turns until gate can portal again | real | Usually 0 or 1. |
| `portal_targets_remaining` | Remaining alley slots gate can portal this turn | real | Derived from gate rules & GP limits. |
| `ability_ready_bits` | Once-per-turn readiness per gate ability | boolean (≤4) | |

## Garden Entities (`AZK_MAX_GARDEN_SLOTS` per player → process_set)
| Feature | Description | Type | Notes |
| --- | --- | --- | --- |
| `card_id` | Entity definition | categorical (embedding) | Zero row represents empty slot. |
| `card_type` | Entity/Leader proxy if applicable | categorical (embedding) | |
| `element` | Element enum | categorical (embedding) | |
| `current_attack` | Attack including buffs | real | |
| `current_health` | Current health after damage | real | |
| `max_health` | Max health post-buffs | real | |
| `ikz_cost_base` | Base IKZ cost | real | |
| `gate_points` | Gate point stat | real | |
| `tapped` | Card tapped | boolean | |
| `cooldown_active` | Summoning sickness active | boolean | |
| `keyword_bits` | Charge/defender/carapace/infiltrate/godmode | boolean (5) | |
| `frozen` | Frozen condition flag | boolean | |
| `shocked` | Shocked condition flag | boolean | |
| `weapon_count` | Weapons attached to this entity | real | |
| `weapon_attack_bonus_total` | Sum of bonuses from attached weapons | real | |
| `ability_ready_bits` | Once-per-turn readiness per ability | boolean (≤4) | |
| `in_combat` | Slot is attacker or current target | boolean | |

## Alley Entities (`AZK_MAX_ALLEY_SLOTS` per player → process_set)
| Feature | Description | Type | Notes |
| --- | --- | --- | --- |
| `card_id` | Entity definition | categorical (embedding) | Zero row = empty. |
| `element` | Element enum | categorical (embedding) | |
| `ikz_cost_base` | Base IKZ cost | real | |
| `current_attack` | Current attack (buff-aware) | real | |
| `current_health` | Current health | real | |
| `max_health` | Max health | real | |
| `gate_points` | Gate point stat | real | |
| `tapped` | Card tapped | boolean | |
| `keyword_bits` | Charge/defender/carapace/infiltrate/godmode | boolean (5) | |
| `frozen` | Frozen condition flag | boolean | |
| `shocked` | Shocked condition flag | boolean | |
| `ability_ready_bits` | Once-per-turn readiness per alley ability | boolean (≤4) | |

## Discard Cards (`AZK_MAX_DECK_SIZE` per player → process_set)
| Feature | Description | Type | Notes |
| --- | --- | --- | --- |
| `card_id` | Card definition index in discard | categorical (embedding) | Index 0 represents top of discard pile. |
| `card_type` | Card type enum | categorical (embedding) | |
| `element` | Element enum (entities/leaders only) | categorical (embedding) | |
| `ikz_cost` | Original IKZ cost | real | |
| `keyword_bits` | Keyword flags as recorded at discard time | boolean (5) | Snapshot when card entered discard. |
| `turn_discarded` | Turn number when card was discarded | real | Normalize by turn cap; 0 for unknown opponent data. |
| `came_from_zone` | Enum (garden, alley, hand, deck, gate, weapon) | categorical (embedding) | Helpful for reconstructing history. |

## Weapon Attachments (per permanent, `AZK_MAX_WEAPONS_PER_SLOT` → process_set)
| Feature | Description | Type | Notes |
| --- | --- | --- | --- |
| `card_id` | Weapon definition | categorical (embedding) | Zero row when no weapon. |
| `weapon_attack_bonus` | Attack bonus granted | real | |
| `keyword_bits` | Keywords granted while attached | boolean (5) | |
| `tapped` | Weapon tapped (if abilities require tapping) | boolean | |
| `frozen` | Frozen condition flag (if applicable) | boolean | |
| `shocked` | Shocked condition flag | boolean | |
| `ability_ready_bits` | Once-per-turn readiness per weapon ability | boolean (≤4) | |

## Response Stack Entries (`AZK_MAX_STACK` → process_set, top-first order)
| Feature | Description | Type | Notes |
| --- | --- | --- | --- |
| `card_id` | Source card definition | categorical (embedding) | Zero row for empty slot. |
| `source_kind` | Enum (spell_from_hand, ability_on_board, gate_ability) | categorical (embedding) | |
| `ability_index` | Ability slot index for abilities (0–3) | real | Use -1 for spells. |
| `ikz_cost_paid` | IKZ cost paid to place entry on stack | real | |
| `target_kind` | Encoded tuple representing targets | categorical (embedding) | Flattened via ID mapping. |
| `resolves_to_damage` | Effect deals damage | boolean | Precomputed metadata. |
| `resolves_to_heal` | Effect heals/buffs | boolean | |
| `timestamp_step` | Step counter when item entered stack | real | Normalize by expected episode length. |

## Once-Per-Turn / Effect Guards
- Maintain a flat vector aligned with every ability slot in play indicating whether the once-per-turn guard has already fired this turn (boolean). Slots map 1:1 with the `ability_ready_bits` emitted in each per-object feature vector.
- Expose `once_per_turn_table_size` (real, normalized) to track how many guards are currently active for debugging and potential curriculum shaping.

## Derived Aggregates
| Feature | Description | Type | Notes |
| --- | --- | --- | --- |
| `self_garden_attack_sum` / `opp_garden_attack_sum` | Total attack across garden | real | Derived from `process_set` outputs. |
| `self_alley_gate_points_sum` | Sum of gate points in alley | real | |
| `self_defenders_ready` / `opp_defenders_ready` | Count of available defender keyword entities | real | |
| `self_response_spells_ready` | Total response-speed spells (hand + stack) | real | |
| `damage_to_lethal_if_unblocked` | Damage required to defeat opponent leader | real | |
| `cards_drawn_this_turn_self` / `_opp` | Cards drawn this turn (public info only for opponent) | real | |

## Normalization Reference
- `attack`, `health`, `weapon_attack_bonus`, `gate_points`, and IKZ-related counts should be divided by their maxima from the card dataset or constants in `types.h`.
- Integer indices for enums (`phase`, `card_type`, `element`, etc.) are stable across builds; document any changes in the generated metadata so embedding tables remain aligned.
- The discard turn and stack timestamp features should be normalized by the same turn or step caps used elsewhere to preserve scale consistency.

## Open Questions / Follow-ups
- Confirm `AZK_MAX_STACK`, `AZK_MAX_DECK_SIZE`, and related constants so set dimensions and normalization factors can be finalized.
- Determine how much discard metadata is retained in-engine (e.g., `keyword_bits`, `came_from_zone`); adjust features if only partial history is available.
- Validate whether gates or weapons can realistically acquire frozen/shocked; drop those bits if impossible to keep the vector tight.
- Revisit aggregate features once the observation builder is implemented to ensure no hidden information leaks and that `process_set` pooling delivers sufficient signal.
