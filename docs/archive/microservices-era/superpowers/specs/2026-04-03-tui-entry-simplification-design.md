# TUI Entry Simplification Design

Date: 2026-04-03
Scope: `services-preview/tui-service` entry commands and related script/doc exposure

## Context

The current TUI surface is heavier than the simplified 3.28 baseline.

Today the repo exposes multiple overlapping TUI commands:

- Root script: `run`, `run-dev`, `run-equity`
- Root compatibility aliases: `run-single`, `tui`, `tui-single`, `tui-dev`, `tui-equity`
- TUI service script: `run`, `run-dev`, `run-equity`, `run-news`, `start`, `stop`, `status`, `restart`

This creates three problems:

1. Too many entry names for the same behavior
2. TUI looks like a background service although it is an interactive foreground app
3. Advanced orchestration modes (`run-news`, `run-equity`) are too close to the main happy path

## Goal

Reduce the TUI command surface so users only need to remember one main entry and one development entry, while keeping advanced collector-linked flows available without presenting them as the default path.

## Non-Goals

- No large refactor of `src/tui.py`
- No redesign of TUI pages or keyboard navigation
- No removal of collector or signal auto-start behavior in this phase
- No change to core active service topology: `collector-service + trading-service + signal-service + tui-service`

## Current Inventory

### Primary root-level commands

- `./scripts/start.sh run`
- `./scripts/start.sh run-dev`
- `./scripts/start.sh run-equity`

### Root compatibility aliases

- `./scripts/start.sh run-single`
- `./scripts/start.sh tui`
- `./scripts/start.sh tui-single`
- `./scripts/start.sh tui-dev`
- `./scripts/start.sh tui-equity`

### TUI service script commands

- `./scripts/start.sh run`
- `./scripts/start.sh run-dev`
- `./scripts/start.sh run-equity`
- `./scripts/start.sh run-news`
- `./scripts/start.sh start`
- `./scripts/start.sh stop`
- `./scripts/start.sh status`
- `./scripts/start.sh restart`

## Recommended Target

### Public primary commands

- `./scripts/start.sh run`
- `./scripts/start.sh run-dev`

### Advanced commands kept but downgraded in visibility

- `cd services-preview/tui-service && ./scripts/start.sh run-news`
- `cd services-preview/tui-service && ./scripts/start.sh run-equity`

These remain supported because they provide useful combined collection + viewing workflows, but they should move out of the main quickstart and main help path.

### Commands to deprecate and hide

- Root aliases: `run-single`, `tui`, `tui-single`, `tui-dev`, `tui-equity`
- TUI pseudo-service commands: `start`, `stop`, `status`, `restart`

Rationale:

- The root aliases are duplicates with no unique semantics.
- The TUI script `start/stop/status/restart` names imply daemon semantics, but the TUI is a foreground curses process.

## Command Model After Simplification

### Normal user path

- Start TUI: `./scripts/start.sh run`

### Developer path

- Start TUI with hot reload: `./scripts/start.sh run-dev`
- Direct low-level launch: `cd services-preview/tui-service && .venv/bin/python -m src ...`

### Advanced operator path

- Run TUI with background news collection: `cd services-preview/tui-service && ./scripts/start.sh run-news`
- Run TUI with background equity collection: `cd services-preview/tui-service && ./scripts/start.sh run-equity`

## Script Changes

### Root script

- Keep `run` and `run-dev`
- Option A: keep `run-equity` temporarily but mark it as advanced and deprecated in help text
- Remove or hide compatibility aliases from the help output

Recommended for this phase:

- Keep alias handlers for compatibility
- Remove them from the advertised help block
- Emit a deprecation warning when used

### TUI service script

- Keep `run`, `run-dev`, `run-news`, `run-equity`
- Remove `start`, `stop`, `status`, `restart` from help output
- Optionally keep handlers temporarily for compatibility, but they should no longer be documented as first-class commands

Recommended for this phase:

- `start` may remain as a temporary alias to `run`
- `stop`, `status`, `restart` should be treated as compatibility-only, not normal usage

## Documentation Changes

Update the following docs so they all present the same TUI story:

- `README.md`
- `README_EN.md`
- `AGENTS.md`

New doc posture:

- Main entry: `./scripts/start.sh run`
- Dev entry: `./scripts/start.sh run-dev`
- Advanced examples: `run-news`, `run-equity`
- Remove `run-single` from recommended usage
- Remove pseudo-service wording for TUI where possible

## Verification

After implementation, verify at minimum:

- `bash -n scripts/start.sh`
- `bash -n services-preview/tui-service/scripts/start.sh`
- `python3 -m unittest tests.test_start_script tests.test_init_script tests.test_script_alignment -v`
- Help output no longer presents deprecated aliases as primary commands
- README / README_EN / AGENTS examples all match the new public command set

## Open Decision

This design assumes:

- `run-news` and `run-equity` stay available as advanced commands for now
- only the public surface is simplified in this phase

If later we want a stricter minimal surface, the next step would be to move `run-news` and `run-equity` out of the TUI script entirely and expose them only via collector-specific commands.
