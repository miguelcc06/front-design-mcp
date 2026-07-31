# GitHub repository metadata (suggested)

Repo: https://github.com/miguelcc06/front-design-mcp (public)

Cloud agents may hit **HTTP 403 Resource not accessible by integration** on `gh repo edit` (description/topics). The owner should apply metadata manually using the steps below.

## Manual steps (owner)

### Option A — GitHub UI

1. Open https://github.com/miguelcc06/front-design-mcp
2. Click the gear icon next to **About** (right sidebar)
3. Paste the **Description** below
4. Add each **Topic** below (one per tag)
5. Optionally set **Website** to the homepage URL
6. Save changes

### Option B — `gh` CLI (with a token that has `repo` write)

```bash
gh repo edit miguelcc06/front-design-mcp \
  --description "Local-first FastMCP server for frontend UI/UX intelligence — discover, compare, and recommend components, animations, and patterns with citations." \
  --add-topic mcp \
  --add-topic fastmcp \
  --add-topic frontend \
  --add-topic ui \
  --add-topic ux \
  --add-topic design-systems \
  --add-topic rag \
  --add-topic bm25 \
  --add-topic sqlite \
  --add-topic python \
  --add-topic cursor \
  --add-topic shadcn \
  --add-topic motion \
  --add-topic radix \
  --homepage "https://github.com/miguelcc06/front-design-mcp"
```

## Description

```
Local-first FastMCP server for frontend UI/UX intelligence — discover, compare, and recommend components, animations, and patterns with citations.
```

## Topics

```
mcp
fastmcp
frontend
ui
ux
design-systems
rag
bm25
sqlite
python
cursor
shadcn
motion
radix
```

## Homepage (optional)

```
https://github.com/miguelcc06/front-design-mcp
```

## Visibility / features

- Enable Issues if you want community adapter requests.
- Keep Actions enabled for `.github/workflows/ci.yml`.
- Do not commit secrets; `.env` is gitignored — use `.env.example` as the template.
