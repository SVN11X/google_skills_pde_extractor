"""Instalación local verificada de Deno para yt-dlp (Windows).

No modifica el PATH del sistema y no ejecuta scripts remotos. Solo usa un ZIP
oficial de GitHub y lo verifica contra su suma SHA256 oficial.
"""
from __future__ import annotations

import hashlib
import io
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def current_version(executable: str | Path) -> tuple[int, int, int] | None:
    try:
        result = subprocess.run([str(executable), '--version'], capture_output=True, text=True, timeout=12)
        match = re.search(r'\bdeno (\d+)\.(\d+)\.(\d+)', result.stdout + result.stderr)
        if result.returncode == 0 and match:
            return tuple(map(int, match.groups()))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def main():
    if os.name != 'nt':
        print('Deno local: solo se instala automáticamente en Windows. Usa Deno >= 2.3 en otros sistemas.')
        return 0
    target = ROOT / '.tools' / 'deno' / 'deno.exe'
    system = shutil.which('deno')
    for candidate in (target, system):
        if candidate and (current_version(candidate) or (0, 0, 0)) >= (2, 3, 0):
            print(f'Deno disponible: {candidate} ({current_version(candidate)})')
            return 0
    arch = platform.machine().lower()
    asset = 'deno-aarch64-pc-windows-msvc.zip' if arch in ('arm64', 'aarch64') else 'deno-x86_64-pc-windows-msvc.zip'
    base = f'https://github.com/denoland/deno/releases/latest/download/{asset}'
    print('Obteniendo Deno desde el repositorio oficial y verificando SHA256...')
    try:
        req = urllib.request.Request(base + '.sha256sum', headers={'User-Agent': 'pde-archiver/2.0'})
        with urllib.request.urlopen(req, timeout=45) as response:
            checksum = response.read(4096).decode('utf-8')
        match = re.search(r'\b([a-fA-F0-9]{64})\b', checksum)
        if not match: raise ValueError('checksum inválido')
        expected = match.group(1).lower()
        with urllib.request.urlopen(urllib.request.Request(base, headers={'User-Agent': 'pde-archiver/2.0'}), timeout=150) as response:
            blocks=[]
            size=0
            while True:
                chunk=response.read(1024*1024)
                if not chunk:break
                blocks.append(chunk)
                size += len(chunk)
                if size > 120*1024*1024: raise ValueError('archivo excede 120 MB')
        data=b''.join(blocks)
        actual=hashlib.sha256(data).hexdigest()
        if actual != expected:raise ValueError('La suma SHA256 no coincide. No se instalará ni ejecutará.')
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if 'deno.exe' not in zf.namelist():raise ValueError('El ZIP no contiene deno.exe')
            if zf.getinfo('deno.exe').file_size > 250*1024*1024:raise ValueError('Ejecutable demasiado grande')
            binary=zf.read('deno.exe')
        target.parent.mkdir(parents=True, exist_ok=True)
        temp=target.with_suffix('.exe.tmp')
        temp.write_bytes(binary)
        os.replace(temp, target)
        ver=current_version(target)
        if not ver or ver < (2,3,0):
            target.unlink(missing_ok=True)
            raise RuntimeError('Deno no se ejecuta o está desactualizado')
        print(f'Deno {ver} instalado localmente: {target}')
        return 0
    except Exception as exc:
        print(f'AVISO: No fue posible configurar Deno automáticamente: {type(exc).__name__}: {exc}')
        print('Puedes instalarlo manualmente desde https://docs.deno.com/runtime/getting_started/installation/')
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
