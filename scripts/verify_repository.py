"""Offline checkout verification. No credentials, native API, or empirical rerun."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FACTOR = ROOT / 'studies/literature-factor-20261009/package'
CTP = ROOT / 'projects/ctp_assignment'
SKIP = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', 'private', 'build', 'dist'}
ALLOWED_REPOSITORIES = {'vnpy/vnpy', 'vnpy/vnpy_ctp', 'vnpy/vnpy_ctastrategy',
                        'aslan9/pku_quantllm', 'celestial-toymaker/factor_pku_quantllm_demo'}
THIRD_PARTY = {'numpy','pandas','pyarrow','scipy','matplotlib','yaml','requests','baostock',
               'pytest','pybind11','factorlab','ctp_assignment'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def public_files():
    return sorted(p for p in ROOT.rglob('*') if p.is_file()
                  and not any(x in SKIP or x.endswith('.egg-info') for x in p.relative_to(ROOT).parts))


def checksums(path):
    count = 0
    for line in path.read_text().splitlines():
        expected, name = line.split('  ', 1)
        # The factor manifest is relative to the package, others to their folder.
        base = FACTOR if path == FACTOR/'release/checksums.sha256' else path.parent
        target = (base/name).resolve()
        assert target.is_relative_to(ROOT) and target.is_file(), name
        assert sha(target) == expected, 'Checksum mismatch: '+name
        count += 1
    return count


def static_checks():
    paths = public_files()
    allowed_top = {'README.md','.gitignore','DEPENDENCIES.md','docs','evidence','projects','studies','scripts'}
    assert all(p.relative_to(ROOT).parts[0] in allowed_top for p in paths), 'Unexpected root content'
    assert not (ROOT/'.gitmodules').exists(), 'Submodule dependency'
    source_count = links = 0
    for p in paths:
        if p.suffix in {'.py','.md','.json','.jsonl','.toml','.lock'}:
            text = p.read_text()
            for repo in re.findall(r'https://github\.com/([\w.-]+/[\w.-]+)', text):
                assert repo in ALLOWED_REPOSITORIES, 'Undeclared repository reference'
        if p.name in {'requirements.lock','pyproject.toml'}:
            text = p.read_text()
            assert not re.search(r'git\+|file://|^-e |/Users/|/home/',text,re.M), 'Nonportable dependency'
        if p.suffix == '.py':
            for node in ast.walk(ast.parse(p.read_text(),filename=str(p))):
                names = [n.name for n in node.names] if isinstance(node,ast.Import) else [node.module] if isinstance(node,ast.ImportFrom) and not node.level else []
                for name in names:
                    if name:
                        module = name.split('.')[0]
                        assert module in sys.stdlib_module_names | THIRD_PARTY or (p.parent/(module+'.py')).is_file(), 'Undeclared import: '+name
            source_count += 1
        if p.suffix == '.md':
            for url in re.findall(r'\]\(([^\s)]+)\)',p.read_text()):
                if url.startswith(('https://','http://','#','mailto:')): continue
                target = (p.parent/url.split('#')[0]).resolve()
                assert target.is_relative_to(ROOT) and target.exists(), (str(p),url)
                links += 1
    for name, expected in json.loads((ROOT/'evidence/lesson02/records/frozen-plan-v2.json').read_text())['source_sha256'].items():
        assert sha(ROOT/name) == expected, 'Frozen trading runtime changed'
    counted = checksums(FACTOR/'release/checksums.sha256') + checksums(ROOT/'evidence/lesson02/checksums.sha256')
    archive = FACTOR.parent/'literature-factor-20261009.zip'
    assert sha(archive) == archive.with_suffix('.zip.sha256').read_text().split()[0]
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        actual = {p.relative_to(FACTOR).as_posix() for p in paths if p.is_relative_to(FACTOR)}
        expected = {name.split('/',1)[1] for name in z.namelist()}
        assert actual == expected, 'Archive inventory mismatch'
        for name in z.namelist():
            assert z.read(name) == (FACTOR/name.split('/',1)[1]).read_bytes(), 'Archive bytes differ'
        archive_count = len(expected)
    return {'static_checks':'PASS','python_sources_checked':source_count,'local_links_checked':links,
            'checksum_entries_checked':counted,'archive_members_checked':archive_count,
            'student_repository_dependencies':0,'native_api_loaded':False,'empirical_evaluations':0}


def offline_checks(ctp_python, factor_python):
    results = []
    with tempfile.TemporaryDirectory(prefix='lesson02-offline-') as directory:
        scratch = Path(directory)
        guard = scratch/'guard';guard.mkdir()
        (guard/'sitecustomize.py').write_text(
            "import socket\n"
            "def blocked(*args, **kwargs):\n    raise RuntimeError('Network disabled for offline verification')\n"
            "socket.socket.connect = blocked\nsocket.socket.connect_ex = blocked\n"
            "socket.create_connection = blocked\n")
        for label, source, interpreter, version in [('ctp',CTP,ctp_python,'3.13.5'),('factor',FACTOR,factor_python,'3.11.11')]:
            target = scratch/'repository'/source.relative_to(ROOT)
            shutil.copytree(source,target,ignore=lambda _,names:[n for n in names if n in SKIP or n.endswith('.egg-info')])
            env = dict(os.environ,PYTHONPATH=str(guard)+os.pathsep+str(target/'src'),
                       PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
            check = subprocess.run([str(interpreter),'-c','import platform;print(platform.python_version())'],env=env,capture_output=True,text=True,check=True)
            assert check.stdout.strip()==version, 'Interpreter version mismatch: '+label
            commands = [[str(interpreter),'-m','pytest','-q']]
            if label == 'ctp':
                commands += [[str(interpreter),'-m','ctp_assignment.cli','doctor'],
                    [str(interpreter),'-m','ctp_assignment.cli','run','--state',str(scratch/'dry/state.db'),'--output',str(scratch/'dry/evidence.json')],
                    [str(interpreter),'-m','ctp_assignment.cli','verify',str(scratch/'dry/evidence.json')]]
            else:
                commands += [[str(interpreter),'-m','factorlab.cli','--root',str(target),'verify']]
            for argv in commands:
                run = subprocess.run(argv,cwd=target,env=env,capture_output=True,text=True)
                text = (run.stdout+run.stderr).replace(str(scratch),'$SCRATCH').replace(str(ROOT),'$REPO')
                results.append({'package':label,'python':version,'argv':[a.replace(str(scratch),'$SCRATCH') for a in argv],
                                'exit_code':run.returncode,'output':text})
                assert run.returncode==0, label+' offline command failed: '+text
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ctp-python',type=Path)
    parser.add_argument('--factor-python',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if bool(args.ctp_python)!=bool(args.factor_python): parser.error('Provide both interpreters or neither')
    result=static_checks()
    if args.ctp_python:
        # Preserve the venv executable path; resolving its symlink selects base Python.
        result['commands']=offline_checks(args.ctp_python.absolute(),args.factor_python.absolute())
        result['offline_checks']='PASS'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='commands'},ensure_ascii=False))


if __name__=='__main__':
    main()
