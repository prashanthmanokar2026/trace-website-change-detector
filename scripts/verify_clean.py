"""Rehearse the README in an isolated source copy and fresh environments."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='trace-clean-') as directory:
    copy=Path(directory)/'trace'
    shutil.copytree(root,copy,ignore=shutil.ignore_patterns('.venv','.tools','node_modules','dist','data','.env','.git','__pycache__','.pytest_cache','*.tsbuildinfo'))
    def run(args):
        print('Verifying:', ' '.join(str(x) for x in args),flush=True)
        subprocess.run([str(x) for x in args],cwd=copy,check=True)
    run([sys.executable,'-m','venv',copy/'.venv'])
    python=copy/'.venv/bin/python'
    run([python,'-m','pip','install','-r','requirements.lock'])
    run(['npm','ci','--prefix','frontend'])
    run(['npm','run','build','--prefix','frontend'])
    run([python,'-m','pytest','-q'])
    print('PASS: isolated source copy, locked dependency install, frontend build and full tests.',flush=True)
