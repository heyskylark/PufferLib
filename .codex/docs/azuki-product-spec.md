# Azuki TCG RL Environment – Product Specification

## 1. Vision & Value Proposition
- **Vision**: Deliver a deterministic, high-performance Azuki TCG simulation that supports both reinforcement learning experimentation and eventual human playtesting, enabling rapid iteration on card designs, balance, and AI agents.
- **Primary Value**: Provide a faithful C implementation of Azuki’s core rules with data-driven card definitions, seamless integration into PufferLib/PettingZoo workflows, and rich tooling for debugging, analytics, and self-play league training.
- **North Star Outcomes**
  - Environment covers 100% of defined rules (gate, portal, keywords, response window, multi-weapon equips, conditions).
  - RL agents can complete full matches end-to-end without illegal actions or crashes.
  - League training infrastructure routinely produces beating-baseline policies.

## 2. Target Users & Stakeholders
- **RL Engineer / Researcher (primary)**: Needs reproducible simulations, action masks, and headroom for algorithmic experimentation.
- **Game Designer / Balance Analyst**: Requires transparent rule enforcement, replay logs, card authoring tooling, and ability to tweak cards without engine changes.
- **Future Players / QA Testers**: Need a stable environment for manual matches and for verifying gameplay feel.
- **Open-Source Contributors** (stretch): Should find clear docs, modular architecture, and test suites that lower contribution friction.

## 3. Problem Statement
Developers need a reliable Azuki TCG environment to explore RL-based agents and balance. Existing engines are either incomplete or not designed for PettingZoo/PufferLib integration. Without a data-driven, reproducible simulator, iterating on card mechanics and training setups is slow and error-prone.

## 4. Scope & Major Features
### Must-Have (MVP)
- Complete C rules engine with data-driven `CardDef` table and effect VM.
- PettingZoo AEC-compatible binding with multi-head (type + params) action interface.
- Deterministic RNG, replay logging, and invariant-preserving legal action masks.
- League-training ready policy plumbing (role masks, NO_OP semantics, opponent snapshots).
- Tooling to ingest Azuki card data from canonical JSON into generated code (`cards_autogen.c/h`).
- Comprehensive test harness and milestone checklist (M0–M18) covering all mechanics.

### Should-Have
- Response stack supporting spells/abilities with LIFO resolution.
- Condition system (frozen, shocked) and keyword bitflags (charge, defender, carapace, infiltrate, godmode).
- Gate portal mechanics with Gate Point scaling.
- Multi-weapon attachments with end-of-turn cleanup.
- Observation tensor meeting PufferLib requirements (flat float32 vector, context flags).

### Nice-to-Have / Stretch
- Effect authoring DSL and compiler, richer target selectors.
- CLI renderer & replay inspector for debugging and demos.
- Curriculum/self-play recipes, scripted opponents for evaluation.
- Performance profiling, SoA optimizations, and optional GPU-friendly packing.

### Out of Scope (for now)
- Full client UI/UX or networked multiplayer.
- Monetization, matchmaking, or live-service features.
- Non-deterministic rule variants or unofficial card sets.

## 5. Success Metrics
- **Functional**: 100% of unit tests & fuzz tests pass; legal mask coverage > 99% (no illegal actions executed by random agent).
- **Performance**: ≥1e6 simple steps/minute on target dev hardware; zero heap allocations during `azk_step`.
- **Training**: Baseline PPO agent reaches win rate >60% versus random after league curriculum, with variance <5%.
- **Data Ops**: Converter ingest completes under 1s for 50+ card definitions; authoring new cards requires no engine recompilation beyond regeneration.

## 6. Constraints & Assumptions
- **Language/Runtime**: Core engine in C11; bindings assume CPython + NumPy; no GPU dependence within engine.
- **Data Source**: Authoritative dataset maintained as JSON (`cards.azuki.json`) under `cards.schema.md`.
- **Sandbox**: Engine must run in deterministic, offline environments (network disabled during training).
- **Board Limits**: Garden/Alley capacity fixed at 5 slots each; `AZK_MAX_WEAPONS_PER_SLOT = 4`; deck size 50 + dedicated leader/gate/IKZ.
- **Legal Play**: Illegal actions must be masked, not silently corrected; NO_OP available only in response/micro decision windows.

## 7. User Experience & Flows
1. **Authoring Cards**
   - Designer edits the JSON dataset following `cards.schema.md`.
   - Run converter to emit `generated/cards_autogen.c/h`.
   - Rebuild engine; tests validate definitions (e.g., `test_autogen_smoke`).
2. **Developing Engine Features**
   - Implement milestone tasks sequentially (zones → turn loop → combat → VM → masks).
   - Run targeted tests + fuzz harness to maintain invariants.
3. **Training Loop**
   - RL researcher instantiates PettingZoo env via Python binding.
   - PufferLib multi-head policy consumes observations, masks, and league role masks.
   - League manager schedules matches, snapshots opponents, tracks ELO.
4. **Debug & Replay**
   - Engineers capture deterministic logs and replays to reproduce bugs.
   - CLI replay tool re-executes logs and validates end-state hash.

## 8. Dependencies & Existing Assets
- Documentation: `.codex/docs/game-info.md` (rules), this spec bundle.
- Data: JSON dataset (to be added), `.codex/docs/azuki-tcg-cards.csv` (reference), `cards.schema.md`, `card_examples.json`.
- Code Skeletons: `include/azuki/*.h`, `puffer/azuki_puffer.h`, `puffer/binding.c`, `pufferlib/ocean/env_binding.h`.
- Reference Training Framework: `pufferlib/ocean/tictactoe/{tictactoe.py, league.py}`.
- Tooling: `tools/azuki_cards_convert.py` (converter).

## 9. Risks & Mitigations
- **Rule Complexity Creep**: Tight scope control via milestone breakdown; maintain spec alignment before adding mechanics.
- **Data Drift**: Schema doc + automatable validation prevent runtime mismatches; enforce converter tests.
- **Performance Regression**: Include perf benchmark milestone (M17) with thresholds; integrate sanitizer builds.
- **Training Instability**: Provide tested observation layout, league manager templates, and mask coverage tests.
- **Debug Difficulty**: Deterministic RNG, replay logs, and event tracing built-in from early milestones.

## 10. Future Enhancements
- Plug-in scripting for card effects (mini DSL → bytecode) to accelerate card authoring while guaranteeing valid opcode generation.
- Visualization / web front-end for human playtests.
- Automated balance analytics (match statistics, card win rates).
- Human-vs-agent telemetry capture and replay storage to analyze learning gaps and support playtesting-driven training.
- Cross-language bindings (Rust/Python) if community demand arises.

---
**Document Owner**: Brandon (project lead)  
**Last Updated**: _2025-10-16_  
**Related Docs**: `azuki-env-tech-spec.md`, `azuki-training-spec.md`, `azuki-env-milestones.md`, `azuki-card-dataset-notes.md`
