#!/usr/bin/env python3
"""Classify GitHub Pages propagation versus provably mixed new page assets.

Never label stale CDN HTML a broken deployment. Return 2 only when the NEW
index is actually served but its pinned kit/app assets are missing/mismatched.
"""
import argparse, hashlib, json, time, urllib.request
from pathlib import Path

CHECK=('index.html','app.js','kit-assets/KIT_VERSION.json','kit-assets/MASTER_DATA.json')
def sha(b):return hashlib.sha256(b).hexdigest()
def get(url):
    req=urllib.request.Request(url,headers={'Cache-Control':'no-cache','Pragma':'no-cache','User-Agent':'PokeSleep-AutoWatch-Probe/1.0'})
    with urllib.request.urlopen(req,timeout=15) as f:
        if f.status!=200:raise OSError('HTTP '+str(f.status))
        return f.read()
def classify(site,url,token):
    site=Path(site);base=url.rstrip('/')+'/'
    try:index=get(base+'index.html?audit='+token)
    except Exception as e:return 'NETWORK_UNKNOWN', {'error':str(e)}
    expected_index=(site/'index.html').read_bytes()
    if index!=expected_index:
        return 'STALE_HTML_OR_PENDING_DEPLOYMENT', {'servedIndexSha256':sha(index),'expectedIndexSha256':sha(expected_index)}
    differences={}
    for file in CHECK[1:]:
        try:bytes_=get(base+file+'?audit='+token)
        except Exception as e:
            differences[file]='HTTP_ERROR:'+str(e);continue
        expected=(site/file).read_bytes()
        if bytes_!=expected:differences[file]={'expectedSha256':sha(expected),'servedSha256':sha(bytes_)}
    return ('MIXED_ASSETS_CONFIRMED' if differences else 'ALL_EXPECTED_ASSETS_LIVE'),differences

def main():
    p=argparse.ArgumentParser();p.add_argument('--site',required=True);p.add_argument('--url',required=True)
    p.add_argument('--commit',required=True);p.add_argument('--attempts',type=int,default=8);p.add_argument('--delay',type=int,default=40)
    p.add_argument('--out',required=True);a=p.parse_args()
    attempts=[]
    for n in range(max(1,a.attempts)):
        status,detail=classify(a.site,a.url,a.commit[:12]+f'-{n}')
        attempts.append({'result':status,'details':detail})
        if status=='ALL_EXPECTED_ASSETS_LIVE':break
        if n+1<a.attempts:time.sleep(a.delay)
    last=attempts[-1]['result']
    # CDN transitions can be briefly mixed; require three consecutive observations.
    if last=='MIXED_ASSETS_CONFIRMED' and (len(attempts)<3 or any(x['result']!='MIXED_ASSETS_CONFIRMED' for x in attempts[-3:])):
        last='MIXED_ASSETS_NOT_STABLE'
    result={'schema':'pokesleep-pages-health-v1','result':last,'checks':attempts,'productionCsvAllowed':False}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
    print(last)
    # 2 is a hard mismatch ONLY after new HTML was served; 3 is stale/pending;
    # 4 is network unverified (do not roll back on mere temporary outages).
    return {'ALL_EXPECTED_ASSETS_LIVE':0,'MIXED_ASSETS_CONFIRMED':2,
            'STALE_HTML_OR_PENDING_DEPLOYMENT':3,'MIXED_ASSETS_NOT_STABLE':3,'NETWORK_UNKNOWN':4}[last]
if __name__=='__main__':raise SystemExit(main())
