"""The one place this tool's version number is written.

Before v1.5.0 neither tool had a version: no `__version__`, no
`CHANGELOG.md`, no git tag. A strategic briefing therefore named its run and
its client but not the build that produced it, so a figure whose meaning
changed in the 2026-11-04 review could not be told apart from the same figure
measured earlier under the old rules.

The number is written HERE and nowhere else. The briefing's header reads it
through `briefing_messages.json`'s `headings.tool_version`, and a standing
test (`tests/test_version_is_stamped.py`) fails the build when
`CHANGELOG.md`'s newest entry names a different version.

The two repos carry the same number deliberately: Tool 1 hands Tool 2 a
`competitor_handoff_*.json` and the review that produced v1.5.0 changed both
sides of that contract. A reader holding a market report and a briefing should
be able to see at a glance whether they came from the same review.
"""

__version__ = "1.5.0"
