#!/usr/bin/env python3
"""Read-only daily post-publish watchdog; never promote, revert, or toggle HOLD."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
import hashlib,json,os,re,subprocess,sys,time
from pathlib import Path
from urllib.request import Request,urlopen
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_pages_live import classify,get

REPO='meka-create/pokesleep-ai-csv-test'
RUNS_URL=f'https://api.github.com/repos/{REPO}/actions/runs?per_page=100'
PUBLIC_URL='https://meka-create.github.io/pokesleep-ai-csv-test/'
JST=ZoneInfo('Asia/Tokyo')
SCHEDULED_WATCH_HOUR_JST=4
DELAY_CODES=frozenset(('SCHEDULED_JST_DAY_STATUS_MISSING',
                        'SCHEDULED_JST_DAY_RUN_MISSING',
                        'SCHEDULED_JST_DAY_RUN_IN_PROGRESS'))

def scheduled_jst_day(now):
    """Select the last due 04:00 JST cycle, even across UTC/date boundaries."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now must be timezone-aware')
    local=now.astimezone(JST)
    return local.date() if local.hour >= SCHEDULED_WATCH_HOUR_JST else local.date()-timedelta(days=1)

def parsed_time(value):
    if not isinstance(value,str):raise ValueError('timestamp is not a string')
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None or dt.utcoffset() is None:raise ValueError('timestamp lacks timezone')
    return dt

ALLOWED=frozenset(('app.js','index.html','update-status.json',
                   'kit-assets/MASTER_DATA.json','kit-assets/KIT_VERSION.json'))
SUCCESS_REASONS=frozenset(('NO_CHANGE','AUTO_PROMOTION_COMMITTED_PENDING_PUSH',
                           'AUTO_PROMOTION_PUBLISHED','AUTO_PROMOTION_PUBLISHED_VERIFIED'))

def sha(data):return hashlib.sha256(data).hexdigest()
def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def canonical(obj):
    return sha(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
def require(ok,code,problems):
    if not ok:problems.append(code)
    return bool(ok)

def github_json(url,token=None):
    headers={'Accept':'application/vnd.github+json','User-Agent':'PokeSleep-Postpublish-Watch/1.0',
             'X-GitHub-Api-Version':'2022-11-28'}
    if token:headers['Authorization']='Bearer '+token
    with urlopen(Request(url,headers=headers),timeout=20) as r:return json.load(r)

def check_local(site,now,problems,*,max_age_hours=34):
    root=site/'kit-assets'
    v=load(root/'KIT_VERSION.json')
    master=load(root/'MASTER_DATA.json')
    status=load(site/'update-status.json')
    require(v.get('productionCsvAllowed') is False and
            v.get('compatibilityVerified') is False and 'HOLD' in str(v.get('status','')),
            'CSV_HOLD_BROKEN',problems)
    require(status.get('schemaVersion')=='pokesleep-upstream-status-v1' and
            status.get('productionCsvAllowed') is False,'STATUS_SCHEMA_OR_HOLD',problems)
    require(status.get('state')=='healthy' and
            status.get('reasonCode') in SUCCESS_REASONS,'UPSTREAM_WATCH_REQUIRES_ATTENTION',problems)
    try:
        checked=parsed_time(status['checkedAt'])
        age=(now-checked).total_seconds()/3600
        require(-.25<=age<=max_age_hours,'UPSTREAM_WATCH_STALE_OR_FUTURE',problems)
        require(checked.astimezone(JST).date()==scheduled_jst_day(now),
                'SCHEDULED_JST_DAY_STATUS_MISSING',problems)
    except (ValueError,KeyError,TypeError,AttributeError):
        age=None
        require(False,'UPSTREAM_WATCH_TIMESTAMP_INVALID',problems)
    hashes=v.get('rawAssetSha256')
    require(isinstance(hashes,dict) and len(hashes)>=15,'KIT_ASSET_MANIFEST_INVALID',problems)
    if isinstance(hashes,dict):
        for name,digest in hashes.items():
            if not isinstance(name,str) or '/' in name or '\\' in name or name.startswith('.'):
                require(False,'KIT_ASSET_PATH_INVALID',problems)
                continue
            p=root/name
            require(p.is_file() and isinstance(digest,str) and
                    bool(re.fullmatch('[0-9a-f]{64}',digest)) and sha(p.read_bytes())==digest,
                    'KIT_ASSET_HASH_MISMATCH:'+name,problems)
    for name in ('MASTER_DATA.json','CSV_SCHEMA.json'):
        if (root/name).is_file():
            require(v.get('assetSha256',{}).get(name)==canonical(load(root/name)),
                    'KIT_CANONICAL_HASH_MISMATCH:'+name,problems)
    app=(site/'app.js').read_text(encoding='utf-8')
    version_sha=sha((root/'KIT_VERSION.json').read_bytes())
    require(bool(re.search(r"(?m)^const KIT_VERSION_RAW_SHA256 = '"+version_sha+r"';$",app)),
            'APP_VERSION_RAW_PIN_MISMATCH',problems)
    require(isinstance(v.get('siteHotfixId'),str) and v['siteHotfixId'] in app,
            'APP_SITE_HOTFIX_PIN_MISMATCH',problems)
    pokemon=master.get('pokemon')
    if require(isinstance(pokemon,list) and len(pokemon)>=249,
               'MASTER_SPECIES_COUNT_REGRESSED',problems):
        names=[p.get('name_en') for p in pokemon if isinstance(p,dict)]
        require(len(names)==len(pokemon) and len(set(names))==len(names),
                'MASTER_SPECIES_DUPLICATE',problems)
        require({'Foongus','Amoonguss'} <= set(names),'MASTER_KNOWN_SPECIES_MISSING',problems)
    source=v.get('sourceCommit')
    if source is not None:
        require(isinstance(source,str) and bool(re.fullmatch('[0-9a-f]{40}',source)),
                'ACTIVE_SOURCE_COMMIT_INVALID',problems)
        require(master.get('provenance',{}).get('sourceCommit')==source,
                'ACTIVE_SOURCE_MASTER_MISMATCH',problems)
    if status.get('reasonCode')!='NO_CHANGE':
        require(source is not None and status.get('activeSourceCommit')==source,
                'PROMOTED_SOURCE_STATUS_MISMATCH',problems)
    elif status.get('activeSourceCommit') not in (None,source):
        require(False,'NO_CHANGE_ACTIVE_SOURCE_MISMATCH',problems)
    return {'speciesCount':len(pokemon) if isinstance(pokemon,list) else None,
            'masterSha256':sha((root/'MASTER_DATA.json').read_bytes()),
            'statusSha256':sha((site/'update-status.json').read_bytes()),
            'sourceCommit':source,'watchReason':status.get('reasonCode'),
            'checkedAgeHours':age}

def check_github_run(data,status,problems,*,now):
    if not isinstance(data,dict) or not isinstance(data.get('workflow_runs'),list):
        require(False,'GITHUB_WATCH_RUN_LIST_INVALID',problems)
        return {}
    candidates=[r for r in data['workflow_runs'] if isinstance(r,dict)
                and r.get('event') in ('schedule','workflow_dispatch') and
                (r.get('path')=='.github/workflows/upstream-watch.yml' or
                 r.get('name')=='Pokemon Sleep automated verified upstream master (PROTOTYPE HOLD)')]
    if not require(bool(candidates),'GITHUB_WATCH_RUN_NOT_FOUND',problems):return {}
    # The GitHub API is normally newest-first, but do not silently depend on it.
    candidates.sort(key=lambda r:str(r.get('created_at') or ''),reverse=True)
    due=scheduled_jst_day(now)
    latest=candidates[0]
    require(latest.get('head_branch')=='main','GITHUB_WATCH_NOT_ON_MAIN',problems)
    try:
        created=parsed_time(latest.get('created_at'))
        run_day=created.astimezone(JST).date()
        require(run_day==due,'SCHEDULED_JST_DAY_RUN_MISSING',problems)
    except (ValueError,TypeError,OverflowError):
        run_day=None
        require(False,'GITHUB_WATCH_CREATED_AT_INVALID',problems)
    if run_day==due:
        if latest.get('status')!='completed':
            require(False,'SCHEDULED_JST_DAY_RUN_IN_PROGRESS',problems)
        elif latest.get('conclusion')!='success':
            require(False,'GITHUB_WATCH_LATEST_NOT_SUCCESS',problems)
        else:
            expected=f'https://github.com/{REPO}/actions/runs/{latest.get("id")}'
            require(status.get('runUrl')==expected,'STATUS_LATEST_RUN_NOT_MATCHED',problems)
    return {'id':latest.get('id'),'conclusion':latest.get('conclusion'),
            'status':latest.get('status'),'event':latest.get('event'),
            'runJstDate':run_day.isoformat() if run_day else None,
            'requiredJstDate':due.isoformat()}

def check_git_history(site,problems,limit=30):
    try:
        history=subprocess.check_output(['git','-C',str(site),'log',f'-{limit}',
                '--format=%H%x09%s'],text=True,stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError,OSError):
        require(False,'RECENT_HISTORY_UNAVAILABLE',problems)
        return []
    records=[]
    for entry in history.splitlines():
        commit,sep,subject=entry.partition('\t')
        if not sep or not subject.startswith(('auto: ','rollback: ','monitor: ')):continue
        try:
            files=subprocess.check_output(['git','-C',str(site),'diff-tree',
                  '--no-commit-id','--name-only','-r',commit],text=True).splitlines()
        except (subprocess.CalledProcessError,OSError):
            require(False,'AUTO_COMMIT_DIFF_UNAVAILABLE',problems)
            continue
        require(bool(files) and set(files)<=ALLOWED,
                'AUTO_COMMIT_CHANGED_FORBIDDEN_FILES:'+commit[:12],problems)
        records.append({'sha':commit,'paths':files,'message':subject})
    return records

def check_public(site,problems,*,url=PUBLIC_URL,attempts=3,delay=12,
                 classifier=classify,fetcher=get):
    observations=[]
    for i in range(max(1,attempts)):
        token='daily-'+str(int(time.time()))+'-'+str(i)
        try:state,detail=classifier(site,url,token)
        except Exception as e:state,detail='NETWORK_UNKNOWN',{'type':type(e).__name__}
        item={'state':state,'details':detail}
        try:
            public=fetcher(url.rstrip('/')+'/update-status.json?watchdog='+token)
            item['statusHashMatched']=sha(public)==sha((site/'update-status.json').read_bytes())
        except Exception as e:
            item['statusHashMatched']=False
            item['fetchError']=type(e).__name__
        observations.append(item)
        if state=='ALL_EXPECTED_ASSETS_LIVE' and item['statusHashMatched']:break
        if i+1<attempts:time.sleep(max(0,delay))
    if not (observations[-1]['state']=='ALL_EXPECTED_ASSETS_LIVE'
            and observations[-1]['statusHashMatched']):
        require(False,'PUBLIC_PAGES_OR_STATUS_NOT_CONFIRMED',problems)
    return observations

def execute(site,*,now=None,runs=None,check_public_files=True,max_age_hours=34,
            public_attempts=3,public_delay=12,token=None,
            public_classifier=classify,public_fetcher=get):
    site=Path(site);now=now or datetime.now(timezone.utc)
    problems=[]
    report={'schemaVersion':'pokesleep-postpublish-audit-v1',
            'checkedAt':now.isoformat(),'requiredJstDate':scheduled_jst_day(now).isoformat(),
            'readOnly':True,
            'productionCsvAllowed':False,'problems':problems}
    try:
        report['local']=check_local(site,now,problems,max_age_hours=max_age_hours)
        status=load(site/'update-status.json')
    except (OSError,ValueError,KeyError,TypeError) as e:
        require(False,'LOCAL_AUDIT_EXCEPTION:'+type(e).__name__,problems)
        status={}
    report['history']=check_git_history(site,problems)
    try:
        data=runs if runs is not None else github_json(RUNS_URL,token)
        report['latestWatchRun']=check_github_run(data,status,problems,now=now)
    except (OSError,ValueError,KeyError,TypeError) as e:
        require(False,'GITHUB_ACTIONS_QUERY_FAILED:'+type(e).__name__,problems)
    if check_public_files:
        try:
            report['publicObservations']=check_public(site,problems,attempts=public_attempts,
                delay=public_delay,classifier=public_classifier,fetcher=public_fetcher)
        except (OSError,ValueError,KeyError,TypeError) as e:
            require(False,'PUBLIC_AUDIT_EXCEPTION:'+type(e).__name__,problems)
    report['state']='PASS' if not problems else ('DELAYED' if set(problems)<=DELAY_CODES else 'ATTENTION')
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--site',default='.')
    p.add_argument('--report',required=True)
    p.add_argument('--max-age-hours',type=float,default=34)
    p.add_argument('--public-attempts',type=int,default=3)
    p.add_argument('--public-delay',type=int,default=12)
    a=p.parse_args()
    r=execute(a.site,max_age_hours=a.max_age_hours,
              public_attempts=a.public_attempts,public_delay=a.public_delay,
              token=os.getenv('GITHUB_TOKEN'))
    dest=Path(a.report);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(r,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'state':r['state'],'problems':r['problems'],
                      'latestWatchRun':r.get('latestWatchRun'),
                      'requiredJstDate':r['requiredJstDate']},ensure_ascii=False))
    return {'PASS':0,'DELAYED':3,'ATTENTION':2}[r['state']]

if __name__=='__main__':raise SystemExit(main())
