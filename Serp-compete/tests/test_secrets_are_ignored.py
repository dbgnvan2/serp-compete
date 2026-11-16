"""The credential files must stay un-committable.

`CLAUDE.md` makes this the repo's one CRITICAL rule:

    `client_secret_*.json` files in the repo root contain OAuth credentials —
    verify they are in `.gitignore` before every commit.

That instruction is addressed to whoever is working, which means it is enforced
by attention. This enforces it by test, because the failure is unrecoverable:
a secret pushed to a remote is a secret to rotate, not a commit to amend, and
the repo is pushed to `main` on every chunk.

It also covers the files `CLAUDE.md` does not name but the code creates:
`gsc_performance.TOKEN_PATH` writes an OAuth **refresh token** to
`token.json` in the repo root the first time anyone authenticates, and `.env`
holds the DataForSEO, Moz and OpenAI keys.
"""
from __future__ import annotations

import os
import subprocess
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

#: Each entry is (a path git would be asked about, why it must never be added).
MUST_BE_IGNORED = (
    ("client_secret_123456789-abcdef.apps.googleusercontent.com.json",
     "OAuth client secret — CLAUDE.md's CRITICAL rule names this pattern"),
    ("token.json",
     "the OAuth REFRESH token gsc_performance.TOKEN_PATH writes on first auth"),
    (".env",
     "DATAFORSEO_LOGIN/PASSWORD, MOZ_TOKEN, OPENAI_API_KEY, YOUTUBE_API_KEY"),
    ("google-secrets.txt", "named in .gitignore since before this review"),
    ("living_systems_intel.db",
     "the audit database: competitor URLs and scores, and *.db is ignored"),
)


def _git_check_ignore(path):
    """True when git would refuse to add *path*.

    `git check-ignore -q` exits 0 when the path IS ignored, 1 when it is not.
    It does not require the file to exist, which is the point: the patterns
    must hold for a secret that has not been created yet.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path],
        cwd=ROOT, capture_output=True)
    return result.returncode == 0


class TestCredentialFilesCannotBeCommitted(unittest.TestCase):

    def test_every_credential_path_is_ignored(self):
        not_ignored = [(path, why) for path, why in MUST_BE_IGNORED
                       if not _git_check_ignore(path)]
        detail = "\n".join(f"  {path} — {why}" for path, why in not_ignored)
        self.assertEqual(not_ignored, [], (
            "These are NOT ignored by .gitignore, so `git add` would stage them "
            f"and a push would publish a live credential:\n{detail}"))

    def test_the_guard_can_actually_fail(self):
        """A path that must NOT be ignored, so this test is not vacuous."""
        self.assertFalse(_git_check_ignore("Serp-compete/src/main.py"))
        self.assertFalse(_git_check_ignore("shared_config.json"))

    def test_no_credential_file_is_currently_tracked(self):
        """Ignoring a pattern does nothing for a file already in the index —
        `.gitignore` is not consulted for tracked paths."""
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
        names = set(tracked.split())
        offenders = [name for name in names
                     if name.startswith("client_secret_")
                     or name in {"token.json", ".env", "google-secrets.txt"}
                     or name.endswith(".db")]
        self.assertEqual(offenders, [], (
            f"These credential or database files are TRACKED, so .gitignore "
            f"does not protect them: {offenders}"))

    def test_shared_config_carries_no_credential_values(self):
        """`shared_config.json` IS committed, and it sits beside the files that
        are not. A key pasted into it ships."""
        import json
        import re

        with open(os.path.join(ROOT, "shared_config.json"), encoding="utf-8") as f:
            raw = f.read()
        json.loads(raw)          # it must still be valid JSON

        # Values that look like credentials rather than configuration. The
        # `api_key_env` keys name an ENVIRONMENT VARIABLE and are expected.
        suspicious = re.findall(
            r'"(?!_)([a-z_]*(?:secret|password|token|api_key|credential)[a-z_]*)"'
            r'\s*:\s*"([^"]+)"', raw, flags=re.IGNORECASE)
        leaks = [(key, value) for key, value in suspicious
                 if not key.endswith("_env")
                 and not value.isupper()          # an env var NAME, not a value
                 and value.strip() != ""]
        self.assertEqual(leaks, [], (
            f"These look like credential VALUES in a committed file. Keys "
            f"belong in .env or the environment: {[k for k, _ in leaks]}"))


if __name__ == "__main__":
    unittest.main()


class TestTheClientSecretPathIsNotPinnedToOneMachine(unittest.TestCase):
    """`auth.gsc_client_secrets` held an absolute path on one developer's
    machine, in a file that is committed and pushed.

    No secret VALUE was exposed — the secret file itself is gitignored — but
    the line published that developer's username and the OAuth client ID, and
    it broke GSC auth everywhere else: a configured-but-missing path is truthy,
    so `_authenticate`'s discovery fallback was skipped and it raised "GSC
    Client Secrets file not found." with a usable `client_secret_*.json`
    sitting in the repo root.
    """

    def _configured(self):
        import json

        with open(os.path.join(ROOT, "shared_config.json"), encoding="utf-8") as f:
            return json.load(f).get("auth", {}).get("gsc_client_secrets", "")

    def test_it_is_not_an_absolute_path(self):
        value = self._configured()
        self.assertFalse(os.path.isabs(value), (
            "An absolute path here is machine-specific and ships in a committed "
            "file. Leave it empty — `_authenticate` finds `gsc_auth.json` or "
            "`client_secret_*.json` in the repo root by itself."))

    def test_it_does_not_name_a_user_home_directory(self):
        value = self._configured().lower()
        for marker in ("/users/", "/home/", "c:\\users", "documents and settings"):
            self.assertNotIn(marker, value,
                             "this publishes a developer's local username")

    def test_it_does_not_embed_an_oauth_client_id(self):
        self.assertNotIn("apps.googleusercontent.com", self._configured())

    def test_discovery_finds_a_secret_in_the_repo_root_when_the_key_is_empty(self):
        """The behaviour the empty value relies on."""
        import glob
        import tempfile
        from unittest.mock import patch

        from src import gsc_performance

        with tempfile.TemporaryDirectory() as tmp:
            planted = os.path.join(tmp, "client_secret_1-abc.apps.googleusercontent.com.json")
            with open(planted, "w") as f:
                f.write("{}")
            with patch.object(gsc_performance, "PROJECT_ROOT", tmp):
                found = sorted(glob.glob(
                    os.path.join(gsc_performance.PROJECT_ROOT,
                                 "client_secret_*.json")))
        self.assertEqual(found, [planted])

    def test_a_configured_but_missing_path_no_longer_wins(self):
        """The bug: a non-empty string is truthy, so the stale path was kept and
        the fallbacks never ran. Behavioural, on the extracted discovery — the
        OAuth flow itself belongs to Google's library and is not tested here."""
        import tempfile
        from unittest.mock import patch

        from src.gsc_performance import find_client_secrets

        with tempfile.TemporaryDirectory() as tmp:
            planted = os.path.join(tmp, "client_secret_1-x.apps.googleusercontent.com.json")
            with open(planted, "w") as f:
                f.write("{}")
            config = {"auth": {"gsc_client_secrets":
                               "/Users/someone-else/serp-compete/client_secret_gone.json"}}
            with patch("src.gsc_performance.PROJECT_ROOT", tmp):
                found = find_client_secrets(config)
        self.assertEqual(found, planted,
                         "a configured path that does not exist must fall "
                         "through to discovery, not be returned")

    def test_a_configured_path_that_exists_still_wins(self):
        import tempfile

        from src.gsc_performance import find_client_secrets

        with tempfile.TemporaryDirectory() as tmp:
            chosen = os.path.join(tmp, "my-secret.json")
            with open(chosen, "w") as f:
                f.write("{}")
            found = find_client_secrets(
                {"auth": {"gsc_client_secrets": chosen}})
        self.assertEqual(found, chosen)

    def test_nothing_anywhere_returns_none_rather_than_a_bad_path(self):
        import tempfile
        from unittest.mock import patch

        from src.gsc_performance import find_client_secrets

        with tempfile.TemporaryDirectory() as tmp:
            start = os.getcwd()
            os.chdir(tmp)
            try:
                with patch("src.gsc_performance.PROJECT_ROOT", tmp):
                    self.assertIsNone(find_client_secrets({}))
            finally:
                os.chdir(start)
