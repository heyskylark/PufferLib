# Azuki Card Dataset Notes

## 1. Data Sources
- **Canonical JSON (authoritative)**: `data/cards.azuki.json` (to be created)
  - Contains all cards for both starter decks:
    - Lightning/Neutral Raizan deck.
    - Water/Neutral Shao deck.
  - Sole input for the generator that emits `cards_autogen.c/h`.
- **Reference CSV**: `.codex/docs/azuki-tcg-cards.csv`
  - Human-readable aid while authoring JSON; not consumed by tooling.
- **Schema & Examples**:
  - `.codex/docs/cards.schema.md` – strict schema definition.
  - `card_examples.json` – minimal valid sample for converter smoke tests.

## 2. Legacy CSV Column Mapping (for reference only)

| Column | Meaning | Engine Mapping |
| --- | --- | --- |
| `Copies` | Deck count per list | Optional for deck builder; not in `CardDef` |
| `Card ID` | Unique identifier (e.g., `STT01-001`) | Map to `CardId` (enum or lookup table) |
| `Card Name` | Display name | `CardDef.name` |
| `Type` | Element or theme (Lightning/Neutral) | Map to `Element` enum |
| `Attributes` | Subtypes (comma-separated) | Optional metadata; may drive keywords in future |
| `Rarity` | `L`, `G`, `C`, `UC`, `R`, `SR`, `IKZ` | For analytics only |
| `Card Type` | `Leader/Gate/Entity/Weapon/Spell/IKZ` | `CardDef.type` |
| `Mana` | IKZ cost | `CardDef.ikz_cost` |
| `Attack` | Base attack (Leader/Entity) | `CardDef.base.attack` |
| `Health` | Base health (Leader/Entity) | `CardDef.base.health` |
| `Gate` | Gate Points | `CardDef.gate_points` |
| `Ability` | Freeform text | Converted to VM programs via JSON pipeline |
| `Total Points` | Balance metric | Optional; not currently used |
| `CHECKED?` | Author verification | Use to track schema compliance |

Notes:
- CSV values must be mirrored in the JSON; no automated CSV ingestion.
- IKZ and token entries have empty cost/attack/health; `CardType=IKZ`.
- `Ability` prose must be converted into structured programs (see §4).

## 3. Enum & Keyword Mapping
### Elements (`Element` enum)
`Neutral`, `Lightning`, `Water`, `Fire`, `Earth`.
Current decks use `Lightning`, `Water`, and `Neutral`.

### Keywords (`KeywordFlags` bitmask)
| CSV Token | Flag | Effect |
| --- | --- | --- |
| `Charge (Can attack the same turn it enters the Garden)` | `KW_CHARGE` | Sets cooldown bypass |
| `Defender` | `KW_DEFENDER` | Allows `DECLARE_DEFENDER` |
| `Carapace N` | `KW_CARAPACE_N` | Reduces damage by N |
| `Infiltrate` | `KW_INFILTRATE` | Skips defender retarget |
| `Godmode` | `KW_GODMODE` | Prevents leaving field from damage/effects |

Keywords embedded in `Ability` text should be captured explicitly in structured data (preferred) rather than inferred from prose.

### Conditions (`ConditionFlags`)
- `frozen`, `shocked` – present in rules doc; no occurrences yet in CSV.

## 4. Ability Authoring Workflow
1. **Canonical JSON Blob**: Author abilities directly in JSON:
   ```json
   {
     "abilities": [
       {
         "timing": "on_play",
         "program": [
           {"op": "PAY_IKZ", "n": 1},
           {"op": "CHOOSE_TARGET", "selector": "ALLY_ENTITY_GARDEN"},
           {"op": "ADD_KEYWORD", "keyword": "charge"}
         ]
       }
     ]
   }
   ```
2. **Structured Portal Examples**
   - *Raizan Gate*: Portal entity, then attach a weapon from discard whose cost ≤ Gate Points.
     ```json
     {
       "timing": "on_portal",
       "program": [
         {"op": "PORTAL", "from": "alley_slot", "to": "garden_slot"},
         {"op": "CHOOSE_TARGET", "selector": "SELF_WEAPON_DISCARD_LEQ_GP"},
         {"op": "MOVE_ZONE", "destination": "WEAPON_ATTACH_LAST_TARGET"},
         {"op": "PAY_IKZ", "n": 0, "cap_by_gp": true}
       ]
     }
     ```
   - *Shao Gate*: Portal entity, then untap IKZ up to Gate Points.
     ```json
     {
       "timing": "on_portal",
       "program": [
         {"op": "PORTAL", "from": "alley_slot", "to": "garden_slot"},
         {"op": "CHOOSE_TARGET", "selector": "ALLY_IKZ_AREA_TAPPED"},
         {"op": "UNTAP", "max_by_gp": true}
       ]
     }
     ```
     Selectors like `SELF_WEAPON_DISCARD_LEQ_GP` are provided in `targets.h`; flags `cap_by_gp`/`max_by_gp` tell the engine to bound effects using the portaled entity’s Gate Points.
3. **Converter Invocation (JSON-only)**:
   ```bash
   python tools/azuki_cards_convert.py \
       --in data/cards.azuki.json \
       --out_dir generated \
       --format json
   ```
   - Converter enforces schema; CSV input is unsupported.
4. **Validation**:
   - Run `tests/test_autogen_smoke`.
   - Add targeted unit tests for new keywords/opcodes.

## 5. Deck Composition Guidelines
- Starter decks: 50-card main deck + 1 Leader + 1 Gate + 10 IKZ + 1 IKZ token.
- Example (Lightning deck):
  - Leader: `Raizan (STT01-001)`.
  - Gate: `Surge (STT01-002)`.
  - Entities: mix of cost 1–6 (e.g., `Crate Rat Kurobo`, `Indra`).
  - Weapons: `Lightning Shuriken`, `Black Jade Dagger`, `Raizan's Zanbato`.
  - Spells: `Lightning Orb`.
- Example (Water deck):
  - Leader: `Shao`.
  - Gate: Water portal with IKZ untap clause.
  - Entities emphasize resource control and support.
- Deck builder should ensure Gate Points curve to support portal strategies (1–4).

## 6. Suggested Data Enhancements
- Provide JSON helpers/macros for recurring ability templates (e.g., draw/discard).
- Maintain version field (`"version": "0.1.0"`) to track dataset revisions.
- Include test fixtures (JSON snippets) to validate parser.

## 7. Quality Checks
- **Converter Assertions**:
  - All `Card Type` values map to known `CardType` enum.
  - IKZ cost defaults to `-1` for Leader/Gate/IKZ.
  - Weapon attack bonuses derived from `Mana` or explicit `WeaponAttackBonus` column.
- **Manual Review**:
  - Confirm `CHECKED?` flagged `YES` before release.
  - Check ability text for ambiguous wording (document conversions in changelog).

## 8. Roadmap
- Build scripting helpers to migrate legacy CSV into JSON schema.
- Expand dataset with additional factions beyond Raizan/Shao.
- Integrate schema validation into CI (e.g., `jsonschema` based test).
- Version card data; embed semantic version in generated headers for compatibility.

---
**Curator**: Brandon  
**Last Updated**: _2025-10-16_  
**Related Docs**: `azuki-env-tech-spec.md`, `cards.schema.md`, `.codex/docs/game-info.md`
