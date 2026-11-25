#!/usr/bin/env vpython3
# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

DEPOT_TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DEPOT_TOOLS_ROOT)

from testing_support import coverage_utils  # noqa: E402
import utils  # noqa: E402


class GitCacheTest(unittest.TestCase):
    def setUp(self):
        pass

    @mock.patch("subprocess.check_output", lambda x, **kwargs: b"foo")
    def testVersionWithGit(self):
        version = utils.depot_tools_version()
        self.assertEqual(version, "git-foo")

    @mock.patch("subprocess.check_output")
    @mock.patch("os.path.getmtime", lambda x: 42)
    def testVersionWithNoGit(self, mock_subprocess):
        mock_subprocess.side_effect = Exception
        version = utils.depot_tools_version()
        self.assertEqual(version, "recipes.cfg-42")

    @mock.patch("subprocess.check_output")
    @mock.patch("os.path.getmtime")
    def testVersionWithNoGit(self, mock_subprocess, mock_getmtime):  # noqa: F811
        mock_subprocess.side_effect = Exception
        mock_getmtime.side_effect = Exception
        version = utils.depot_tools_version()
        self.assertEqual(version, "unknown")


class ConfigDirTest(unittest.TestCase):
    @mock.patch("sys.platform", "win")
    def testWin(self):
        self.assertEqual(DEPOT_TOOLS_ROOT, utils.depot_tools_config_dir())

    @mock.patch("sys.platform", "darwin")
    def testMac(self):
        self.assertEqual(DEPOT_TOOLS_ROOT, utils.depot_tools_config_dir())

    @mock.patch("sys.platform", "foo")
    def testOther(self):
        self.assertEqual(DEPOT_TOOLS_ROOT, utils.depot_tools_config_dir())

    @mock.patch("sys.platform", "linux")
    @mock.patch.dict("os.environ", {})
    def testLinuxDefault(self):
        self.assertEqual(
            os.path.join(os.path.expanduser("~/.config"), "depot_tools"),
            utils.depot_tools_config_dir(),
        )

    @mock.patch("sys.platform", "linux")
    @mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": "/my/home"})
    def testLinuxCustom(self):
        self.assertEqual(
            os.path.join("/my/home", "depot_tools"),
            utils.depot_tools_config_dir(),
        )


class CacheDirTest(unittest.TestCase):
    @mock.patch("sys.platform", "win32")
    @mock.patch.dict(
        "os.environ", {"LOCALAPPDATA": "C:\\Users\\me\\Local"}, clear=True
    )
    def testWin(self):
        self.assertEqual(
            os.path.join("C:\\Users\\me\\Local", "depot_tools"),
            utils.depot_tools_cache_dir(),
        )

    @mock.patch("sys.platform", "darwin")
    @mock.patch.dict("os.environ", {}, clear=True)
    def testMac(self):
        self.assertEqual(
            os.path.join(os.path.expanduser("~/Library/Caches"), "depot_tools"),
            utils.depot_tools_cache_dir(),
        )

    @mock.patch("sys.platform", "linux")
    @mock.patch.dict("os.environ", {}, clear=True)
    def testLinuxDefault(self):
        self.assertEqual(
            os.path.join(os.path.expanduser("~/.cache"), "depot_tools"),
            utils.depot_tools_cache_dir(),
        )

    @mock.patch("sys.platform", "linux")
    @mock.patch.dict("os.environ", {"XDG_CACHE_HOME": "/my/cache"}, clear=True)
    def testLinuxCustom(self):
        self.assertEqual(
            os.path.join("/my/cache", "depot_tools"),
            utils.depot_tools_cache_dir(),
        )


class ConfigPathTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="utils_test")
        self.legacy_dir = os.path.join(self.temp_dir, "legacy")
        self.config_dir = os.path.join(self.temp_dir, "config")
        os.makedirs(self.legacy_dir)

        mock.patch("utils.DEPOT_TOOLS_ROOT", self.legacy_dir).start()
        mock.patch(
            "utils.depot_tools_config_dir", lambda: self.config_dir
        ).start()

        self.addCleanup(mock.patch.stopall)
        self.addCleanup(shutil.rmtree, self.temp_dir)

    def testConfigPathDoesNotMutate(self):
        legacy_path = os.path.join(self.legacy_dir, "metrics.cfg")
        with open(legacy_path, "w") as f:
            f.write("{}")

        self.assertEqual(
            os.path.join(self.config_dir, "metrics.cfg"),
            utils.depot_tools_config_path("metrics.cfg"),
        )
        self.assertFalse(os.path.exists(self.config_dir))
        self.assertTrue(os.path.isfile(legacy_path))

    def testReadPathFallsBackToLegacyWithoutMutating(self):
        legacy_path = os.path.join(self.legacy_dir, "metrics.cfg")
        expected_path = os.path.join(self.config_dir, "metrics.cfg")

        self.assertEqual(
            expected_path, utils.depot_tools_config_read_path("metrics.cfg")
        )
        self.assertFalse(os.path.exists(self.config_dir))

        with open(legacy_path, "w") as f:
            f.write("{}")
        self.assertEqual(
            legacy_path, utils.depot_tools_config_read_path("metrics.cfg")
        )
        self.assertFalse(os.path.exists(self.config_dir))
        self.assertTrue(os.path.isfile(legacy_path))

        os.makedirs(self.config_dir)
        with open(expected_path, "w") as f:
            f.write("{}")
        self.assertEqual(
            expected_path, utils.depot_tools_config_read_path("metrics.cfg")
        )

    def testPrepareWriteCreatesConfigDir(self):
        expected_path = os.path.join(self.config_dir, "metrics.cfg")

        self.assertEqual(
            expected_path,
            utils.prepare_depot_tools_config_write("metrics.cfg"),
        )
        self.assertTrue(os.path.isdir(self.config_dir))

    def testPrepareWriteMovesLegacy(self):
        legacy_path = os.path.join(self.legacy_dir, "metrics.cfg")
        expected_path = os.path.join(self.config_dir, "metrics.cfg")
        with open(legacy_path, "w") as f:
            f.write('{"legacy": true}')

        self.assertEqual(
            expected_path,
            utils.prepare_depot_tools_config_write("metrics.cfg"),
        )
        self.assertFalse(os.path.exists(legacy_path))
        with open(expected_path) as f:
            self.assertEqual('{"legacy": true}', f.read())

        # When expected_path already exists, a legacy file is left untouched.
        with open(legacy_path, "w") as f:
            f.write('{"stale": true}')
        self.assertEqual(
            expected_path,
            utils.prepare_depot_tools_config_write("metrics.cfg"),
        )
        self.assertTrue(os.path.isfile(legacy_path))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG if "-v" in sys.argv else logging.ERROR
    )
    sys.exit(
        coverage_utils.covered_main(
            (os.path.join(DEPOT_TOOLS_ROOT, "git_cache.py")),
            required_percentage=0,
        )
    )
