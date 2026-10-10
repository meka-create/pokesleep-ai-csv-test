#!/usr/bin/env python3
"""Locate candidate CSV import modules & tests in a pinned upstream checkout.

Inventory ONLY; importing functionality is not exercised. A missing candidate is
not filled in with a guessed importer. Safe for review artifacts, never deploy.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

PATTERNS = {
    'box_importer': re.compile(r'BoxImporter|BoxExporter',re.I),
    'csv_implementation': re.compile(r'CSV|CsvFormatter|parseCsv|parseCSV|csvTo|importCsv|importCSV'),
    'csv_header': re.compile('ニックネーム|食材1|せいかく|色違い|一緒に眠った時間'),
    'import_test': re.compile(r'\b(import|export|round.?trip)\b.*csv|csv.*\b(import|export|round.?trip)\b',re.I)
}

def inventory(repo):
    repo=Path(repo)
    matches=[]
    for parent in ('src','iv','scripts'):
        root=repo/parent
        if not root.exists(): continue
        for path in sorted(root.rglob('*')):
            if not path.is_file() or path.suffix not in ('.ts','.tsx','.js','.jsx','.mjs','.cjs'): continue
            data=path.read_text(encoding='utf-8',errors='replace')
            occurrences=[]
            for number,line in enumerate(data.splitlines(),1):
                labels=[name for name,rx in PATTERNS.items() if rx.search(line)]
                if labels:
                    occurrences.append({'line':number,'categories':labels,'preview':line.strip()[:180]})
            if occurrences:
                matches.append({'file':path.relative_to(repo).as_posix(),
                                'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                'occurrences':occurrences[:70],
                                'truncated':len(occurrences)>70})
    return {'schemaVersion':'importer-inventory-v0.4','status':'INVENTORY_ONLY',
            'actualImporterExecuted':False,'productionCsvAllowed':False,
            'candidateFiles':matches,'candidateCount':len(matches)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--upstream',required=True)
    p.add_argument('--out',default='upstream_staging/IMPORTER_SURFACE_INVENTORY.json')
    a=p.parse_args()
    result=inventory(a.upstream)
    dest=Path(a.out);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':result['status'],'candidateCount':result['candidateCount'], 'productionCsvAllowed':False}))
    return 0 if result['candidateCount'] else 2
if __name__=='__main__':raise SystemExit(main())
