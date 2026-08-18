"""Every `appTo(...)` call must sit inside a component that declared the hook.

A missing declaration is not a build error — `appTo` is a bare identifier, so it
compiles and throws at runtime, on a page nobody clicks until a client does.
This walks top-level component boundaries and checks each call site against the
declaration that governs it.
"""
import glob
import io
import re
import sys

DECL = re.compile(r'^\s*const appTo = useAppPath\(\);')
BOUNDARY = re.compile(r'^(export default )?function ([A-Za-z0-9_]+)\s*\(')
USE = re.compile(r'\bappTo\(')
COMMENT = re.compile(r'^\s*(//|\*|/\*)')

bad = 0
checked = 0
for path in sorted(glob.glob('frontend/src/pages/*.jsx')
                   + glob.glob('frontend/src/clientspace/*.jsx')
                   + glob.glob('frontend/src/client/**/*.jsx', recursive=True)):
    lines = io.open(path, encoding='utf-8').read().splitlines()
    if not any('useAppPath' in ln for ln in lines):
        continue
    checked += 1
    current = '<module>'
    owner = []
    for ln in lines:
        m = BOUNDARY.match(ln)
        if m:
            current = m.group(2)
        owner.append(current)
    declared = {owner[i] for i, ln in enumerate(lines) if DECL.match(ln)}
    for i, ln in enumerate(lines):
        if DECL.match(ln) or COMMENT.match(ln):
            continue
        if USE.search(ln) and owner[i] not in declared:
            print(f'  {path}:{i + 1}  appTo() in {owner[i]}() which never declared it')
            print(f'      {ln.strip()[:110]}')
            bad += 1

print(f'\n{checked} files use useAppPath; {bad} unscoped call site(s)')
sys.exit(1 if bad else 0)
