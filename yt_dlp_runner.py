"""Isolated, bounded yt-dlp CLI calls for public/authorized media.

Use the virtualenv interpreter, no inherited yt-dlp configuration/cookies,
and a supported Deno + EJS setup. YouTube availability is not guaranteed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@dataclass
class Outcome:
    ok: bool
    reason: str = ''
    stdout: str = ''
    stderr: str = ''
    code: int | None = None


def project_python() -> str:
    # Some installations include global site-packages; explicit venv launch
    # ensures the interpreter used for media is the one updated by the BAT.
    candidate = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    return str(candidate) if candidate.is_file() else sys.executable


def deno_path() -> str | None:
    candidate = ROOT / '.tools' / 'deno' / ('deno.exe' if os.name == 'nt' else 'deno')
    return str(candidate) if candidate.is_file() else shutil.which('deno')


def yt_dlp_command(extra: list[str], *, verbose: bool = False) -> list[str]:
    command = [project_python(), '-I', '-m', 'yt_dlp', '--ignore-config', '--no-playlist',
               '--no-progress', '--socket-timeout', '15', '--retries', '1',
               '--fragment-retries', '1', '--extractor-retries', '1',
               '--extractor-args', 'youtube:player_client=default,web_embedded']
    deno = deno_path()
    if deno:
        command += ['--js-runtimes', 'deno:' + deno]
    if verbose:
        command.append('--verbose')
    return command + list(extra)


def execute(extra: list[str], *, timeout: int, verbose: bool = False) -> Outcome:
    command = yt_dlp_command(extra, verbose=verbose)
    try:
        # Do not use shell=True and do not send browser cookies to yt-dlp.
        proc = subprocess.run(command, cwd=str(ROOT), capture_output=True,
                              text=True, errors='replace', timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return Outcome(False, f'Timeout: yt-dlp superó {timeout} s')
    except OSError as exc:
        return Outcome(False, f'No se pudo iniciar yt-dlp: {type(exc).__name__}: {exc}')
    stderr = (proc.stderr or '')[-16000:]
    stdout = (proc.stdout or '')[-16000:]
    if proc.returncode:
        short_error = next((ln.strip() for ln in reversed(stderr.splitlines()) if 'ERROR:' in ln), '')
        return Outcome(False, short_error or stderr[-500:] or f'Código {proc.returncode}',
                       stdout, stderr, proc.returncode)
    return Outcome(True, stdout=stdout, stderr=stderr, code=0)
