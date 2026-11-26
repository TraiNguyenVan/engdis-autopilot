import os
import unittest
from unittest.mock import patch

import bootstrap_browser
import config


class ModeDefaultTests(unittest.TestCase):
    """The merged code has to work in both run modes.

    Docker: profile on the /data volume, cache under ED_SCRATCH=/data/cache
    (exported by docker/entrypoint.sh). Bare metal: nothing may be created at a
    root-level path that a normal user cannot write.
    """

    def test_default_profile_prefers_the_container_volume(self):
        with patch.dict(os.environ, {"ED_PROFILE": ""}, clear=False), \
             patch.object(bootstrap_browser.os.path, "isdir", return_value=True):
            self.assertEqual(bootstrap_browser._default_profile(), "/data/profile")

    def test_default_profile_falls_back_to_the_checkout(self):
        with patch.dict(os.environ, {"ED_PROFILE": ""}, clear=False), \
             patch.object(bootstrap_browser.os.path, "isdir", return_value=False):
            profile = bootstrap_browser._default_profile()
        repo_root = os.path.dirname(os.path.abspath(bootstrap_browser.__file__))
        self.assertEqual(profile, os.path.join(repo_root, "data", "profile"))

    def test_explicit_profile_env_wins(self):
        with patch.dict(os.environ, {"ED_PROFILE": "/tmp/ed-profile"}, clear=False):
            self.assertEqual(bootstrap_browser._default_profile(), "/tmp/ed-profile")

    def test_scratch_default_is_absolute(self):
        self.assertTrue(os.path.isabs(config.SCRATCH))
        if os.path.isdir("/opt/data"):
            self.assertEqual(config.SCRATCH, "/opt/data/cache/scratch/ed22u1")


if __name__ == "__main__":
    unittest.main()
