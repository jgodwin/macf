# Config Save + Restart from Previous Session

## Summary

Save `config.json` to each session directory so conferences can be restarted with the same configuration. Add `--from-session` CLI flag to load config from a previous session.

## Session Directory After This Change

```
sessions/
  20260301-143022-a1b2c3d4/
    config.json       # NEW — topic, goal, roles
    workspace/
    transcript.md
```

## Files to Modify

- `src/macf2/transcript.py` — Add `write_config(state, roles, output_path)` function
- `src/macf2/web/app.py` — Save config on `conference_configured` and `conference_started` events
- `src/macf2/main.py` — Add `--from-session` CLI arg, load config.json from session dir
- `tests/test_transcript.py` — Tests for config save/load
- `README.md` — Document `--from-session` in CLI args table

## Task 1: Add config writing function to `transcript.py`

Add `write_config(state: ConferenceState, roles: list[RoleConfig], output_path: Path) -> bool`:
- Builds a dict with `topic`, `goal`, and `roles` (each role as `{name, description, instructions}`)
- Writes as JSON with `indent=2`
- Creates parent dirs
- Skips if topic is empty (not configured yet)
- Returns True if written, False if skipped

This produces the same format as `ConferenceConfig` / `examples/api_design_conference.json`, so it's directly loadable via `--config` as well.

## Task 2: Wire config saving into app lifecycle

In `app.py`, extend the existing `on_transcript_event` listener (or add to it):

- On `conference_configured` event: write config to current session dir
- On `conference_started` event: write config to current session dir (catches configs set at construction that skip the configure step)
- On `conference_reset` event: write config for the OLD state to the old session dir (before switching sessions)

The session dir path is computed from `sessions_base / generate_session_id(state)`.

Need access to `conference._roles` to get the role list. The conference object is already in scope in `app.py`.

## Task 3: Add `--from-session` CLI arg to `main.py`

Add `--from-session` argument that accepts a path to a session directory. On startup:
1. Read `config.json` from the session directory
2. Parse with `ConferenceConfig.model_validate_json()`
3. Use it as the starting config (same as `--config`)
4. If both `--config` and `--from-session` are provided, error out (ambiguous)

```bash
# Restart from a previous session
python -m macf2.main --from-session sessions/20260301-143022-a1b2c3d4

# Equivalent to:
python -m macf2.main --config sessions/20260301-143022-a1b2c3d4/config.json
```

## Task 4: Tests

- `test_write_config_basic` — Write config, read it back, verify topic/goal/roles
- `test_write_config_skips_empty_topic` — Empty topic returns False, no file written
- `test_write_config_matches_conference_config_format` — Verify output is loadable by `ConferenceConfig.model_validate_json()`

## Task 5: Update README

Add `--from-session` to the CLI arguments table. Add a brief note in the Session Management section about restarting from previous sessions.
