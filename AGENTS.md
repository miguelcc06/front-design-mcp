# AGENTS.md

## Cursor Cloud specific instructions

### What this repo is
This repo (`front-design-mcp`) is a Cursor **agent skills** repository. Its only substantive
content is the `mcp-builder` skill under `.agents/skills/mcp-builder/`, which guides agents to
build and evaluate MCP (Model Context Protocol) servers. There is no long-running app, frontend,
backend, or database here.

The one runnable component that ships in-tree is the Python **evaluation harness**:
`.agents/skills/mcp-builder/scripts/evaluation.py` (with `connections.py`). It launches/connects to
an MCP server and scores it against an XML QA file using Claude.

### Dependencies / environment
- Python 3.12 and Node.js 22 are preinstalled. `pip install` targets the user site (`~/.local`), so
  no venv is needed; the startup update script installs the harness deps.
- Harness deps come from `.agents/skills/mcp-builder/scripts/requirements.txt` (`anthropic`, `mcp`).
- IMPORTANT (non-obvious): `requirements.txt` pins `mcp>=1.1.0`, but `mcp` 2.0.0 renamed
  `streamablehttp_client` -> `streamable_http_client`, which breaks `connections.py` on import.
  The environment therefore pins `mcp<2` (currently resolves to 1.29.x). Do not "upgrade" `mcp` to
  2.x unless `connections.py` is updated to the new API.

### Running the evaluation harness (the shipped runnable)
- Requires `ANTHROPIC_API_KEY` in the environment to actually call Claude. Without it, the harness
  still connects to the MCP server and lists tools, then fails at the first Claude call with a 401.
- `evaluation.py`'s `-a/--args` uses `nargs='+'` and greedily consumes trailing tokens, so put the
  positional `eval_file` BEFORE `-a`, e.g.:
  `python3 evaluation.py my_eval.xml -t stdio -c python3 -a my_server.py`
- For `stdio` transport the harness launches the server itself; for `sse`/`http` you must start the
  server separately first. See `.agents/skills/mcp-builder/reference/evaluation.md` for full usage.

### Quick end-to-end sanity check (no API key needed)
Build a minimal FastMCP server and connect to it via the repo's own `connections.py` over stdio to
verify the toolchain (server build + client transport + tool calls). This exercises the same
machinery the harness uses without needing `ANTHROPIC_API_KEY`.
