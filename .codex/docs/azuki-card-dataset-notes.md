# Azuki Card Dataset Notes

## 1. Data Sources
- **Primary CSV**: `.codex/docs/azuki-tcg-cards.csv`
  - Contains 41 gameplay cards + IKZ resources (as of 2025-10-16).
  - Columns support starter deck “Raizan” lineup (Lightning focus).
- **Supplementary JSON/Schema**:
  - `.codex/docs/cards.schema.md` – canonical field names, enum values, keyword strings.
  - `.codex/docs/azuki_cards_from_csv.json` – reference entries used by converter.

## 2. CSV Column Mapping

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
- IKZ and token entries have empty cost/attack/health; `CardType=IKZ`.
- `Ability` free text should be transformed into structured JSON (see §4).

## 3. Enum & Keyword Mapping
### Elements (`Element` enum)
`Neutral`, `Lightning`, `Water`, `Fire`, `Earth`.

CSV currently uses `Lightning`, `Neutral`; converter defaults to `Neutral` when blank.

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
1. **Canonical JSON Blob**: For each card, create structured ability specification:
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
2. **Embedding in CSV**:
   - Add new column `AbilityJSON` (or reuse `Ability` column with JSON string).
   - Converter prioritizes JSON; falls back to heuristics if absent.
3. **Converter Process**:
   ```bash
   python tools/azuki_cards_convert.py \
       --in .codex/docs/azuki-tcg-cards.csv \
       --out_dir generated \
       --format csv
   ```
   Options: `--schema cards.schema.md`, `--summary out/cards_summary.json`.
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
- Deck builder should ensure Gate Points curve to support portal strategies (1–4).

## 6. Suggested Data Enhancements
- Add explicit columns for `Keywords` (pipe-separated) and `Conditions`.
- Break abilities into multiple rows or JSON array for readability.
- Include `Timing` column to capture effect windows (on_play, when_equipping, response, etc.).
- Track card art/asset references for future UI integration (out of scope now).

## 7. Quality Checks
- **Converter Assertions**:
  - All `Card Type` values map to known `CardType` enum.
  - IKZ cost defaults to `-1` for Leader/Gate/IKZ.
  - Weapon attack bonuses derived from `Mana` or explicit `WeaponAttackBonus` column.
- **Manual Review**:
  - Confirm `CHECKED?` flagged `YES` before release.
  - Check ability text for ambiguous wording (document conversions in changelog).

## 8. Roadmap
- Automate CSV → JSON transformation using templates.
- Build lint script to detect missing keywords/elements.
- Expand dataset with additional starter decks (Water, Fire, etc.).
- Version card data; embed semantic version in generated headers for compatibility.

---
**Curator**: Brandon  
**Last Updated**: _2025-10-16_  
**Related Docs**: `azuki-env-tech-spec.md`, `cards.schema.md`, `.codex/docs/game-info.md`
