#!/usr/bin/env python3
# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import build_telemetry  # noqa: E402


class BuildTelemetryTest(unittest.TestCase):
    def test_check_auth(self):
        with unittest.mock.patch("subprocess.run") as run_mock:
            auth = {"email": "bob@google.com"}

            def write_auth(cmd, **kwargs):
                self.assertIsInstance(cmd, list)
                self.assertEqual(cmd[0], build_telemetry._cipd_path())
                self.assertNotIn("shell", kwargs)
                path = cmd[cmd.index("--json-output") + 1]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(auth, f)

            run_mock.side_effect = write_auth
            self.assertEqual(build_telemetry.check_auth(), auth)

        with (
            unittest.mock.patch.object(sys, "platform", "win32"),
            unittest.mock.patch("subprocess.run") as run_mock,
        ):
            run_mock.side_effect = subprocess.CalledProcessError(
                1, cmd=["check auth"], stderr="failed"
            )
            self.assertEqual(build_telemetry.check_auth(), {})
            called_cmd = run_mock.call_args[0][0]
            self.assertEqual(
                called_cmd[0],
                os.path.join(build_telemetry._ROOT_DIR, "cipd.bat"),
            )

        with unittest.mock.patch("subprocess.run") as run_mock:

            def write_invalid(cmd, **kwargs):
                path = cmd[cmd.index("--json-output") + 1]
                with open(path, "w", encoding="utf-8") as f:
                    f.write("invalid json")

            run_mock.side_effect = write_invalid
            self.assertEqual(build_telemetry.check_auth(), {})

    def test_load_and_save_config(self):
        test_countdown = 2
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "build_telemetry.cfg")
            with unittest.mock.patch(
                "build_telemetry.check_auth"
            ) as check_auth:
                check_auth.return_value = {"email": "bob@google.com"}

                # Initial config load
                cfg = build_telemetry.load_config(cfg_path, test_countdown)
                self.assertEqual(cfg.path, cfg_path)
                self.assertTrue(cfg.is_googler)
                self.assertEqual(cfg.countdown, test_countdown)
                self.assertEqual(cfg.version, build_telemetry.VERSION)

                cfg.save()

                # 2nd config load
                cfg = build_telemetry.load_config(cfg_path, test_countdown)
                self.assertEqual(cfg.path, cfg_path)
                self.assertTrue(cfg.is_googler)
                self.assertEqual(cfg.countdown, test_countdown)
                self.assertEqual(cfg.version, build_telemetry.VERSION)

                # build_telemetry.check_auth() is an expensive call.
                # The cached result should be reused.
                check_auth.assert_called_once()

            build_telemetry.load_config(cfg_path).save()
            with open(cfg_path) as f:
                self.assertEqual(
                    json.load(f),
                    {
                        "user": "bob@google.com",
                        "status": None,
                        "countdown": test_countdown,
                        "version": build_telemetry.VERSION,
                    },
                )

            fresh_save_path = os.path.join(tmpdir, "fresh_save.cfg")
            self.assertEqual(
                build_telemetry.load_config(fresh_save_path).version,
                build_telemetry.VERSION,
            )
            build_telemetry.load_config(fresh_save_path, test_countdown).save()
            with open(fresh_save_path) as f:
                self.assertEqual(
                    json.load(f),
                    {
                        "user": "",
                        "status": None,
                        "countdown": test_countdown,
                        "version": build_telemetry.VERSION,
                    },
                )

    @unittest.mock.patch("shutil.which")
    def test_enabled(self, mock_shutil):
        test_countdown = 2
        mock_shutil.return_value = "path"

        # Googler auto opt-in.
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "build_telemetry.cfg")
            with unittest.mock.patch(
                "build_telemetry.check_auth"
            ) as check_auth:
                check_auth.return_value = {"email": "bob@google.com"}

                # Initial config load
                cfg = build_telemetry.load_config(cfg_path, test_countdown)
                cfg._show_notice = unittest.mock.MagicMock()
                self.assertEqual(cfg.countdown, test_countdown)

                # 1st enabled() call should print the notice and
                # change the countdown.
                self.assertTrue(cfg.enabled())
                self.assertEqual(cfg.countdown, test_countdown - 1)
                cfg._show_notice.assert_called_once()
                cfg._show_notice.reset_mock()

                # 2nd enabled() call shouldn't print the notice and
                # change the countdown.
                self.assertTrue(cfg.enabled())
                self.assertEqual(cfg.countdown, test_countdown - 1)
                cfg._show_notice.assert_not_called()

                cfg.save()

                # 2nd config load
                cfg = build_telemetry.load_config(cfg_path)
                cfg._show_notice = unittest.mock.MagicMock()
                self.assertTrue(cfg.enabled())
                self.assertEqual(cfg.countdown, test_countdown - 2)
                cfg._show_notice.assert_called_once()

                cfg.save()

                # 3rd config load
                cfg = build_telemetry.load_config(cfg_path)
                cfg._show_notice = unittest.mock.MagicMock()
                self.assertTrue(cfg.enabled())
                self.assertEqual(cfg.countdown, 0)
                cfg._show_notice.assert_not_called()

        # Googler opt-in/opt-out.
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "build_telemetry.cfg")
            with unittest.mock.patch(
                "build_telemetry.check_auth"
            ) as check_auth:
                check_auth.return_value = {"email": "bob@google.com"}
                # After opt-out, it should not display the notice and
                # change the countdown.
                cfg = build_telemetry.load_config(cfg_path, test_countdown)
                cfg.opt_out()

                cfg = build_telemetry.load_config(cfg_path, test_countdown)
                cfg._show_notice = unittest.mock.MagicMock()
                self.assertFalse(cfg.enabled())
                self.assertEqual(cfg.countdown, test_countdown)
                cfg._show_notice.assert_not_called()

                # After opt-in, it should not display the notice and
                # change the countdown.
                cfg = build_telemetry.load_config(cfg_path, test_countdown)
                cfg.opt_in()

                cfg = build_telemetry.load_config(cfg_path, test_countdown)
                cfg._show_notice = unittest.mock.MagicMock()
                self.assertTrue(cfg.enabled())
                self.assertEqual(cfg.countdown, test_countdown)
                cfg._show_notice.assert_not_called()

        # Non-Googler
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_shutil.return_value = None
            cfg_path = os.path.join(tmpdir, "build_telemetry.cfg")
            with unittest.mock.patch(
                "build_telemetry.check_auth"
            ) as check_auth:
                check_auth.return_value = {"email": "bob@example.com"}
                cfg = build_telemetry.load_config(cfg_path)
                self.assertFalse(cfg.enabled())

    @unittest.mock.patch("shutil.which")
    def test_disabled_by_env_var(
        self, mock_shutil: unittest.mock.MagicMock
    ) -> None:
        test_countdown = 2
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_shutil.return_value = "path"
            cfg_path = os.path.join(tmpdir, "build_telemetry.cfg")
            with (
                unittest.mock.patch("build_telemetry.check_auth") as check_auth,
                unittest.mock.patch.dict(
                    os.environ, {"DEPOT_TOOLS_BUILD_TELEMETRY": "0"}
                ),
            ):
                check_auth.return_value = {"email": "bob@google.com"}
                cfg = build_telemetry.load_config(cfg_path, test_countdown)
                cfg._show_notice = unittest.mock.MagicMock()
                self.assertFalse(cfg.enabled())
                self.assertEqual(cfg.countdown, test_countdown)
                cfg._show_notice.assert_not_called()
                check_auth.assert_not_called()

    def test_default_config_paths_are_lazy(self) -> None:
        with (
            unittest.mock.patch(
                "utils.depot_tools_config_path", autospec=True
            ) as config_path,
            unittest.mock.patch(
                "utils.depot_tools_config_read_path", autospec=True
            ) as read_path,
            unittest.mock.patch(
                "utils.prepare_depot_tools_config_write", autospec=True
            ) as write_path,
        ):
            importlib.reload(build_telemetry)
            build_telemetry.load_config()
            config_path.assert_not_called()
            read_path.assert_not_called()
            write_path.assert_not_called()

            with unittest.mock.patch.dict(
                os.environ, {"DEPOT_TOOLS_BUILD_TELEMETRY": "0"}
            ):
                self.assertFalse(build_telemetry.enabled())
            read_path.assert_not_called()
            write_path.assert_not_called()

    def test_default_config_delegates_read_and_write_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_cfg = os.path.join(tmpdir, "legacy.cfg")
            expected_cfg = os.path.join(tmpdir, "expected.cfg")
            with open(legacy_cfg, "w") as f:
                json.dump(
                    {
                        "user": "bob@google.com",
                        "status": "opt-out",
                        "countdown": 5,
                        "version": build_telemetry.VERSION,
                    },
                    f,
                )

            with (
                unittest.mock.patch(
                    "utils.depot_tools_config_path",
                    autospec=True,
                    return_value=expected_cfg,
                ),
                unittest.mock.patch(
                    "utils.depot_tools_config_read_path",
                    autospec=True,
                    return_value=legacy_cfg,
                ) as read_path,
                unittest.mock.patch(
                    "utils.prepare_depot_tools_config_write",
                    autospec=True,
                    return_value=expected_cfg,
                ) as prepare_write,
            ):
                cfg = build_telemetry.load_config()
                self.assertEqual(cfg.path, expected_cfg)
                self.assertEqual(cfg.status(), "opt-out")
                self.assertTrue(cfg.is_googler)
                self.assertEqual(cfg.countdown, 5)
                read_path.assert_called_once_with("build_telemetry.cfg")
                prepare_write.assert_not_called()

                with contextlib.redirect_stdout(io.StringIO()):
                    cfg.opt_in()
                prepare_write.assert_called_once_with("build_telemetry.cfg")
                with open(expected_cfg) as f:
                    self.assertEqual(json.load(f)["status"], "opt-in")


if __name__ == "__main__":
    unittest.main()
