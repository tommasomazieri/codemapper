# codemapper API — Sessions

> **Status: stub — not yet documented.**

## Planned endpoints

- `POST /session/new` — Create a new progressive-disclosure session; returns a `session_id`
- `POST /session/{id}/expand` — Expand a file path to the requested level within a session; returns only the delta (information not yet disclosed in this session)

Sessions allow an LLM agent to track which files have been seen at which detail level, so subsequent calls return only newly-revealed information rather than repeating already-disclosed content.

Full documentation coming in the next iteration.
