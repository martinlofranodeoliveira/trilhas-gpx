#!/usr/bin/env python3
"""Build a wheel, install it in a venv and test it inside an offline namespace."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

EXCLUDED = {".git", ".venv", "__pycache__", "build", "dist", ".pytest_cache"}


def inventory(root: Path, *, include_bytecode: bool = False) -> dict[str, str]:
    result = {}
    excluded = EXCLUDED - {"__pycache__"} if include_bytecode else EXCLUDED
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = sorted(n for n in names if n not in excluded and not n.endswith(".egg-info"))
        for name in names + files:
            if (Path(directory) / name).is_symlink():
                raise RuntimeError("Check inputs must not contain symlinks")
        for name in sorted(files):
            if name.endswith(".pyc") and not include_bytecode:
                continue
            path = Path(directory) / name
            if not path.is_file():
                raise RuntimeError("Check inputs must be regular files")
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def tooling_inventory() -> dict[str, str]:
    """Hash only the explicit interpreter and public build packages we execute."""
    executable = Path(sys.executable).resolve()
    allowed = (Path('/usr'), Path('/opt'))
    def system_path(path):
        return any(path.is_relative_to(root) for root in allowed)
    if not executable.is_file() or not system_path(executable):
        raise RuntimeError('Interpreter must be a system/toolcache file')
    result = {'interpreter': hashlib.sha256(executable.read_bytes()).hexdigest()}
    for package in ('pip', 'setuptools', 'wheel'):
        spec = importlib.util.find_spec(package)
        if spec is None or not spec.submodule_search_locations:
            raise RuntimeError('Required public build package is missing')
        locations = list(spec.submodule_search_locations)
        if len(locations) != 1:
            raise RuntimeError('Ambiguous build package location')
        root = Path(locations[0]).resolve()
        if not system_path(root):
            raise RuntimeError('Build packages must reside in system/toolcache paths')
        for name, digest in inventory(root, include_bytecode=True).items():
            result[package + '/' + name] = digest
    return result


TEST_RUNNER = r'''
import json, sys, unittest
suite = unittest.defaultTestLoader.discover(sys.argv[1], pattern='test*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
print('TRILHAS_TEST_RESULT=' + json.dumps({'suite':sys.argv[1], 'run':result.testsRun,
    'failures':len(result.failures), 'errors':len(result.errors), 'skipped':len(result.skipped)}), flush=True)
if result.testsRun == 0 or result.skipped or not result.wasSuccessful():
    raise SystemExit(1)
'''

INNER = r'''
import hashlib, json, os, pathlib, shutil, socket, subprocess, sys, zipfile
status = pathlib.Path('/proc/self/status').read_text()
assert int(next(x.split()[1] for x in status.splitlines() if x.startswith('CapEff:')),16)==0
assert next(x.split()[1] for x in status.splitlines() if x.startswith('NoNewPrivs:'))=='1'
assert not pathlib.Path('/home/martin').exists()
try:
    with socket.create_connection(('1.1.1.1',443),timeout=0.1):
        raise AssertionError('Network unexpectedly available')
except OSError:
    pass
for path in ['/source', *(['/acceptance'] if pathlib.Path('/acceptance').exists() else [])]:
    try:
        pathlib.Path(path,'write-probe').write_text('must fail')
    except OSError:
        pass
    else:
        raise AssertionError('Test inputs are writable')
shutil.copytree('/source','/tmp/build-source')
os.chdir('/tmp/build-source')
from setuptools.build_meta import build_wheel, build_sdist
sdist_name=build_sdist('/tmp/sdist')
import tarfile
with tarfile.open('/tmp/sdist/'+sdist_name,'r:gz') as archive:
    members=archive.getmembers()
    assert all(m.isfile() or m.isdir() for m in members)
    assert all(not pathlib.PurePosixPath(m.name).is_absolute() and '..' not in pathlib.PurePosixPath(m.name).parts for m in members)
    archive.extractall('/tmp/sdist-source',filter='data')
sdist_root=next(pathlib.Path('/tmp/sdist-source').iterdir())
os.chdir(sdist_root)
wheel_name=build_wheel('/tmp/wheels')
wheel_path=pathlib.Path('/tmp/wheels',wheel_name)
with zipfile.ZipFile(wheel_path) as package:
    names=package.namelist()
    assert any(n.endswith('/licenses/LICENSE') or n.endswith('.dist-info/LICENSE') for n in names)
    entry=next(n for n in names if n.endswith('.dist-info/entry_points.txt'))
    assert 'trilhas-gpx = trilhas_gpx.cli:main' in package.read(entry).decode()
    metadata=package.read(next(n for n in names if n.endswith('.dist-info/METADATA'))).decode()
    assert not any(line.startswith('Requires-Dist:') for line in metadata.splitlines())
os.chdir('/tmp')
subprocess.run([sys.executable,'-B','-s','-m','venv','--without-pip','/tmp/venv'],check=True)
python='/tmp/venv/bin/python'
subprocess.run([sys.executable,'-B','-s','-m','pip','--python',python,'install','--no-index',
    '--no-deps','--disable-pip-version-check',str(wheel_path)],check=True)
env=dict(os.environ,TRILHAS_GPX_CLI='/tmp/venv/bin/trilhas-gpx')
subprocess.run([python,'-I','-B','/source/scripts/check.py','--inner-tests','/source/tests'],env=env,check=True)
if pathlib.Path('/acceptance').exists():
    subprocess.run([python,'-I','-B','/source/scripts/check.py','--inner-tests','/acceptance'],env=env,check=True)
subprocess.run(['/tmp/venv/bin/trilhas-gpx','--help'],env=env,check=True,stdout=subprocess.DEVNULL)
subprocess.run([python,'-I','-B','-m','trilhas_gpx','--help'],env=env,check=True,stdout=subprocess.DEVNULL)
print('TRILHAS_BUILD_RESULT='+json.dumps({'wheel':wheel_name,'wheel_sha256':hashlib.sha256(wheel_path.read_bytes()).hexdigest(),
    'sdist':sdist_name,'built_wheel_from_sdist':True,
    'venv_installed':True,'source_read_only':True,'offline':True,'cap_eff':0,'no_new_privs':True,'python':sys.version.split()[0]}),flush=True)
'''


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--inner-tests":
        sys.argv = [sys.argv[0], sys.argv[2]]
        exec(compile(TEST_RUNNER, "<fixed-test-runner>", "exec"), {"__name__": "__main__"})
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    before = inventory(root)
    tools_before = tooling_inventory()
    acceptance = args.acceptance.resolve() if args.acceptance else None
    frozen = inventory(acceptance) if acceptance else None
    if not shutil.which("bwrap") or not shutil.which("setpriv"):
        parser.error("Linux, bubblewrap and util-linux/setpriv are required")
    with tempfile.TemporaryDirectory(prefix="trilhas-gpx-check-") as temporary:
        stage = Path(temporary) / "source"
        stage.mkdir()
        for name in before:
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, target)
        assert inventory(stage) == before
        command = ["bwrap", "--unshare-all", "--unshare-user", "--disable-userns", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv"]
        for directory in ("/usr", "/bin", "/lib", "/lib64", "/opt"):
            if Path(directory).exists():
                command += ["--ro-bind", directory, directory]
        # Distro pip may import requests against the public system CA bundle
        # even with --no-index. Mount only that public file, never all of /etc.
        ca_bundle = Path("/etc/ssl/certs/ca-certificates.crt")
        if ca_bundle.is_file():
            command += ["--dir", "/etc/ssl/certs", "--ro-bind", str(ca_bundle), str(ca_bundle)]
        command += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/home", "--dir", "/empty-home"]
        command += ["--ro-bind", str(stage), "/source", "--chdir", "/tmp"]
        if acceptance:
            command += ["--ro-bind", str(acceptance), "/acceptance"]
        for key, value in {"HOME":"/empty-home", "PATH":"/usr/bin:/bin", "LC_ALL":"C.UTF-8", "PYTHONDONTWRITEBYTECODE":"1", "PIP_NO_INDEX":"1", "PIP_DISABLE_PIP_VERSION_CHECK":"1"}.items():
            command += ["--setenv", key, value]
        command += ["/usr/bin/setpriv", "--no-new-privs", sys.executable, "-B", "-s", "-c", INNER]
        completed = subprocess.run(command, check=False, timeout=180)
        assert inventory(stage) == before, "Staged source changed"
    assert inventory(root) == before, "Original source changed"
    assert tooling_inventory() == tools_before, "Build dependencies changed"
    if acceptance:
        assert inventory(acceptance) == frozen, "Independent tests changed"
    proof = {"returncode":completed.returncode,
             "source_sha256":hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),
             "dependencies_sha256":hashlib.sha256(json.dumps(tools_before,sort_keys=True).encode()).hexdigest(),
             "acceptance_sha256":hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest() if frozen else None}
    if args.receipt:
        args.receipt.write_text(json.dumps(proof,indent=2)+"\n")
    print(json.dumps(proof))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
