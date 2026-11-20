# Serp-Compete — Claude Code instructions

Competitive SEO intelligence tool (Tool 2) for Living Systems Counselling. Analyzes
competitor rankings and identifies strategic content gaps using Bowen Family Systems framing.
Companion to `serp-discover` (Tool 1).

## Version number

`Serp-compete/src/_version.py` holds `__version__` and is the only place the
number is written. The briefing's header renders it through
`briefing_messages.json`'s `headings.tool_version`. Bumping it means three
things in one commit: edit `_version.py`, add the matching `## [x.y.z]`
section to `CHANGELOG.md`, and tag `vx.y.z` in BOTH repos — Tool 1 carries
the same number on purpose, because the two exchange a
`competitor_handoff_*.json` and a review that changes one side of that
contract changes both. `tests/test_version_is_stamped.py` fails the build
when the changelog's newest entry and `_version.py` disagree.

## Global standards

Read the relevant file from `~/.claude/standards/` before starting work:

| Standard | When |
|---|---|
| `security.md` | CRITICAL — OAuth client secret JSON files are present in the repo root; confirm they are gitignored before any `git add` |
| `learnings.md` | Any data-path, scoring, or report code — P1–P10 checklist |
| `external-api.md` | Any call to SERP APIs, Google APIs, or other HTTP endpoints |
| `llm-integration.md` | Any prompt building or LLM output handling |
| `file-maintainability.md` | Any new module or significant refactor |

## Key rules

- `client_secret_*.json` files in the repo root contain OAuth credentials — verify they are in `.gitignore` before every commit.
- Editorial content (keyword rules, domain overrides, vocabulary) belongs in YAML/JSON config, not Python source.
- See `serp-discover/CLAUDE.md` for patterns shared between the two tools.
