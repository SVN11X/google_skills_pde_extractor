"""Sequential Google Skills learning-path manager, with isolated exports per path.

Never shares crawl state, manifests, or exported media across paths. Reuses the
same local browser profile sequentially, never concurrently.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


def parse_path(value: str) -> tuple[str, str]:
    text = value.strip()
    if not text or text.startswith('#'):
        raise ValueError('vacío')
    if text.isdecimal():
        return text, f'https://www.skills.google/paths/{text}'
    url = urlparse(text)
    if url.scheme != 'https' or url.hostname != 'www.skills.google':
        raise ValueError('Solo admite https://www.skills.google/paths/NUMERO')
    match = re.fullmatch(r'/paths/(\d+)/?', url.path)
    if not match or url.query or url.fragment:
        raise ValueError('URL de ruta inválida; formato esperado: /paths/NUMERO')
    return match.group(1), f'https://www.skills.google/paths/{match.group(1)}'


def load_paths(source: Path) -> list[tuple[str, str]]:
    items = []
    seen = set()
    for line in source.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        path_id, url = parse_path(line)
        if path_id not in seen:
            seen.add(path_id)
            items.append((path_id, url))
    if not items:
        raise ValueError('El archivo de rutas no contiene rutas válidas')
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description='Administrar varias rutas Google Skills sin mezclar exportaciones')
    parser.add_argument('--paths-file', type=Path, default=Path('paths.txt'))
    parser.add_argument('--root', type=Path, default=Path('export_paths'))
    parser.add_argument('--profile-dir', default='.google_skills_browser')
    parser.add_argument('--mode', choices=['crawl', 'ai-only'], default='crawl')
    parser.add_argument('--legacy-dir', type=Path, default=Path('export_pde'),
                        help='Si path 16 ya existe aquí, reutilizarlo en vez de extraer nuevamente')
    parser.add_argument('--whisper-model', default='large-v3')
    args = parser.parse_args()
    try:
        paths = load_paths(args.paths_file)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    root = args.root.resolve()
    legacy_used = False
    for path_id, url in paths:
        out = root / ('path_' + path_id)
        legacy = args.legacy_dir.resolve()
        if path_id == '16' and (legacy / 'videos_manifest.json').is_file():
            print('[REUTILIZAR] Path 16: usando export_pde existente sin volver a navegar.', flush=True)
            res = subprocess.run([sys.executable, 'build_ai_corpus.py', '--out', str(legacy)], check=False)
            if res.returncode:
                return res.returncode
            legacy_used = True
            continue
        if args.mode == 'crawl':
            cmd = [sys.executable, 'extractor.py', '--path-url', url,
                   '--out', str(out), '--profile-dir', args.profile_dir,
                   '--all', '--keep-videos', '--whisper-model', args.whisper_model,
                   '--max-pages', '2000', '--delay', '2']
        else:
            cmd = [sys.executable, 'build_ai_corpus.py', '--out', str(out)]
        print(f'\n=== PATH {path_id} ({args.mode}) ===', flush=True)
        result = subprocess.run(cmd, check=False)
        if result.returncode:
            print(f'[PARCIAL] Ruta {path_id}: código {result.returncode}. No se borró el avance.', flush=True)
            return result.returncode
        if args.mode == 'crawl':
            built = subprocess.run([sys.executable, 'build_ai_corpus.py', '--out', str(out)], check=False)
            if built.returncode:
                return built.returncode
    combine_cmd = [sys.executable, 'build_ai_corpus.py', '--combine', str(root)]
    if legacy_used:
        combine_cmd.extend(['--legacy-out', str(legacy)])
    subprocess.run(combine_cmd, check=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
