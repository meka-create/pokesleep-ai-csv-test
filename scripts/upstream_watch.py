#!/usr/bin/env python3
"""Non-destructive upstream change watcher, not an auto-updater.
A source change must not promote unverified data or silently replace the master.
"""
import json
import pathlib
import sys
import urllib.request

root=pathlib.Path(__file__).resolve().parents[1]
version_path = next((p for p in (
    root/'site/kit-assets/KIT_VERSION.json',
    root/'kit-assets/KIT_VERSION.json') if p.is_file()), None)
if version_path is None:
    print('HOLD: KIT_VERSION.json not found; no action permitted', file=sys.stderr)
    sys.exit(2)
version=json.loads(version_path.read_text(encoding='utf-8'))
url='https://api.github.com/repos/nitoyon/pokesleep-tool/commits/main'
req=urllib.request.Request(url,headers={'User-Agent':'PokeSleep-AI-Kit-Update-Watch/0.1','Accept':'application/vnd.github+json'})
try:
    with urllib.request.urlopen(req,timeout=25) as response:
        commit=json.load(response)['sha']
except Exception as error:
    print('ERROR: upstream could not be checked:',error,file=sys.stderr)
    sys.exit(2)
print('Current upstream commit:',commit)
print('Pinned and independently importer-verified:',version.get('sourceCommit') or '(NOT PINNED)')
if not version.get('sourceCommit') or commit!=version['sourceCommit']:
    print('ACTION REQUIRED: new/unpinned source. Do NOT automatically update master or enable production CSV.')
    sys.exit(1)
print('UPSTREAM UNCHANGED: repository HEAD matches pinned source. Separate deployed-app validation is still required.')
