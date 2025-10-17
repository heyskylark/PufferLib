
# Azuki Card Data Schema (JSON/CSV)

Author cards in **JSON** (preferred) or **CSV** (with an `abilities` JSON column).

## Fields (by type)

Common:
- `id` (string, required): unique, C-safe (e.g., `"SWIFT_SPROUT"`).
- `name` (string, required)
- `type` (Leader|Gate|Entity|Weapon|Spell|IKZ)
- `element` (Neutral|Fire|Water|Earth|Wind|Light|Dark) — Leader/Entity only
- `ikz_cost` (int) — -1 for Leader/Gate/IKZ
- `keywords` (array[string]) — any of: `charge, defender, carapace1, infiltrate, godmode`
- `abilities` (array[Ability]) — optional

Entity/Leader:
- `attack` (int), `health` (int)
- `gate_points` (int, Entity only)

Weapon:
- `weapon_attack_bonus` (int)

Spell:
- `spell_timing` (main|response) — convenience; JSON `timing` covers this

## Ability
```json
{
  "timing": "on_play | on_play_garden | on_play_alley | start_of_turn | end_of_turn | when_equipping | when_attacking | when_attacked | after_attacking | response | alley_only | garden_only",
  "once_per_turn": false,
  "program": [
    {"op":"PAY_IKZ","n":1},
    {"op":"CHOOSE_TARGET","selector":"OPP_LEADER"},
    {"op":"DEAL_DAMAGE","n":2,"to":"LAST_TARGET"}
  ]
}
```
- `selector`/`to` strings map to `TargetSel` in `include/azuki/targets.h`.
- For portal scaling by Gate Points, add `"scale_gp": true` to `DEAL_DAMAGE` op.

## CSV Columns
```
id,name,type,element,ikz_cost,attack,health,gate_points,weapon_attack_bonus,spell_timing,keywords,abilities
```
where `abilities` is a JSON string (array of Ability).
