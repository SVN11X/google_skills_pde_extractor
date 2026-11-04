"""No network: unit tests for isolated yt-dlp runner."""
import subprocess
import unittest
from unittest.mock import patch
import yt_dlp_runner


class TestYtdlpRunner(unittest.TestCase):
    def test_command_does_not_inherit_user_config(self):
        with patch.object(yt_dlp_runner, 'deno_path', return_value='C:/deno/deno.exe'):
            cmd = yt_dlp_runner.yt_dlp_command(['--skip-download', 'https://youtube.com/watch?v=stj830n-1uE'])
        self.assertEqual(cmd[1:4], ['-I', '-m', 'yt_dlp'])
        self.assertIn('--ignore-config', cmd)
        self.assertIn('youtube:player_client=default,web_embedded', cmd)
        self.assertIn('deno:C:/deno/deno.exe', cmd)

    def test_timeout_is_reported_not_propagated(self):
        with patch.object(yt_dlp_runner.subprocess, 'run', side_effect=subprocess.TimeoutExpired('yt-dlp', 120)):
            result = yt_dlp_runner.execute(['--skip-download'], timeout=120)
        self.assertFalse(result.ok)
        self.assertIn('Timeout', result.reason)

    def test_error_without_false_success(self):
        process = subprocess.CompletedProcess(['python'], 1, '', 'ERROR: [youtube] The page needs to be reloaded.')
        with patch.object(yt_dlp_runner.subprocess, 'run', return_value=process):
            result = yt_dlp_runner.execute(['--skip-download'], timeout=120)
        self.assertFalse(result.ok)
        self.assertIn('The page needs to be reloaded', result.reason)

    def test_success(self):
        process = subprocess.CompletedProcess(['python'], 0, 'video title', '')
        with patch.object(yt_dlp_runner.subprocess, 'run', return_value=process):
            result = yt_dlp_runner.execute(['--skip-download'], timeout=120)
        self.assertTrue(result.ok)


if __name__ == '__main__':
    unittest.main()
