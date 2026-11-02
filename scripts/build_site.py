"""Build only the public static website and its locally pinned runtime assets."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from preconditions import preconditions

ROOT = Path(__file__).resolve().parents[1]
PAGES = ('index.html', 'history.html', 'about.html', 'privacy.html', 'terms.html', '404.html')
PUBLIC = ('site.webmanifest', 'favicon.svg', 'favicon.ico', 'apple-touch-icon.png',
          'og-image.png', 'ig-image.png', 'inventing-fire-mark.png', 'app-icon-1024.png', 'robots.txt', 'sitemap.xml', 'llms.txt', 'humans.txt',
          'sw.js', 'staticwebapp.config.json', 'news.json')
DATA = ('current.json', 'models.json', 'data/model_catalog.json', 'data/core_benchmarks.json',
        'data/site_summary.json', 'data/scoring_revision.json',
        'data/historical_benchmark_gaps.json', 'data/publication.json')


@preconditions(root='path')
def build_assets(root=ROOT):
    root = Path(root).resolve()
    executable = root / 'node_modules/.bin/tailwindcss'
    if not executable.is_file():
        raise ValueError('Missing pinned frontend packages; run npm ci')
    assets = root / 'assets'
    assets.mkdir(exist_ok=True)
    subprocess.run([str(executable), '-c', str(root / 'tailwind.config.cjs'),
                    '-i', str(root / 'css/site.css'), '-o', str(assets / 'site.css'), '--minify'],
                   cwd=root, check=True, capture_output=True, text=True)
    vendor = assets / 'vendor'
    vendor.mkdir(exist_ok=True)
    for source, name in (('chart.js/dist/chart.umd.js', 'chart.umd.min.js'),
                         ('lucide/dist/umd/lucide.min.js', 'lucide.min.js'),
                         ('chart.js/LICENSE.md', 'chart.LICENSE.txt'),
                         ('lucide/LICENSE', 'lucide.LICENSE.txt')):
        path = root / 'node_modules' / source
        if not path.is_file():
            raise ValueError('Missing pinned vendor asset: ' + source)
        shutil.copyfile(path, vendor / name)


@preconditions(root='path', relative='nonempty')
def public_file(root, relative):
    root = Path(root).resolve()
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Unsafe public path: ' + relative)
    target = root / path
    if any((root / Path(*path.parts[:i])).is_symlink() for i in range(1, len(path.parts) + 1)):
        raise ValueError('Public asset must not be a symlink: ' + relative)
    if not target.is_file():
        raise ValueError('Missing required public asset: ' + relative)
    return target


@preconditions(root='path', output='path', verify='bool')
def build_site(root=ROOT, output=ROOT / 'dist', *, verify=True):
    root = Path(root).resolve()
    if Path(output).is_symlink():
        raise ValueError('Build output must not be a symlink')
    output = Path(output).resolve()
    if output == root or root.is_relative_to(output):
        raise ValueError('Build output must not contain or replace the checkout')
    if output.is_relative_to(root) and output != root / 'dist':
        raise ValueError('Only dist may be replaced inside the checkout')
    if (root / '.publication-pending.json').exists() or (root / '.model-store-pending.json').exists():
        raise ValueError('Recover the pending publication before building')
    if verify:
        from prepare_publication import verify_installed
        verify_installed(root)
    manifest = json.loads(public_file(root, 'data/publication.json').read_text())
    names = set(PAGES + PUBLIC + DATA)
    for pattern in ('favicon-*.png', 'web-app-manifest-*.png', 'maskable-*.png'):
        names.update(p.name for p in root.glob(pattern) if p.is_file())
    names.update(p.relative_to(root).as_posix() for p in (root / 'js').glob('*.js'))
    names.update(p.relative_to(root).as_posix() for p in (root / 'assets').rglob('*') if p.is_file())
    plan = json.loads(public_file(root, 'social/plan.json').read_text())
    names.add('social/plan.json')
    for name in plan.get('slides', []):
        if Path(name).name != name or not name.endswith('.png'):
            raise ValueError('Unsafe social slide path')
        names.add('social/' + name)
    # Keep already published slide URLs available while changing the current plan.
    names.update(p.relative_to(root).as_posix() for p in (root / 'social').glob('*.png'))
    files = {name: public_file(root, name) for name in sorted(names)}
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            raise ValueError('Unsafe build output')
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for name, source in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    shell = {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
             for name in sorted(names)
             if name in PAGES or name.startswith(('assets/', 'js/'))
             or name in ('site.webmanifest', 'favicon.svg', 'favicon.ico',
                         'apple-touch-icon.png', 'inventing-fire-mark.png', 'app-icon-1024.png', 'data/site_summary.json')
             or name.startswith(('web-app-manifest-', 'maskable-', 'favicon-'))}
    manifest['shellArtifacts'] = shell
    manifest['shellRevision'] = hashlib.sha256(json.dumps(shell, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    (output / 'data/publication.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    return {'files': len(files), 'generationId': manifest['generationId'],
            'shellRevision': manifest['shellRevision']}


@preconditions()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    build_assets()
    if not args.assets_only:
        print(json.dumps(build_site(output=args.output)))


if __name__ == '__main__':
    main()
