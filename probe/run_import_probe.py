#!/usr/bin/env python3
"""Evidence-first REAL browser import/export probe for pokesleep-tool.

It DOES NOT promote any master, change the Pages site or release production CSV.
Only a genuine import with matching CSV re-export gives UI_IMPORT_EXPORT_MATCH; otherwise HOLD.
This probe does not claim deployed build equals source git checkout.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

HEADER = ('ニックネーム','ポケモン','レベル','スキルレベル','食材1','食材2','食材3',
          'メインスキル','せいかく','Lv10','Lv25','Lv50','Lv70','Lv80','一緒に眠った時間','色違い')
# Developer-only synthetic fixture, not a claim about screenshot contents/defaults.
EXAMPLE_ROW = ('CSV接続テスト','カメックス','60','3','モーモーミルク','リラックスカカオ',
               'モーモーミルク','食材ゲットS','きまぐれ','食材確率アップM',
               '最大所持数アップL','おてつだいスピードM','スキルレベルアップS',
               '最大所持数アップM','0','0')

def write_fixture(path):
    with Path(path).open('w', newline='', encoding='utf-8') as fp:
        w=csv.writer(fp, lineterminator='\n')
        w.writerow(HEADER)
        w.writerow(EXAMPLE_ROW)

def parse_csv_file(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as fp:
        return list(csv.reader(fp,strict=True))

def compare_roundtrip(input_path, exported_path):
    """Strict 16-column, 1-row, exact value comparison; no unchecked coercion."""
    expected=parse_csv_file(input_path)
    actual=parse_csv_file(exported_path)
    return (actual == expected,
            {'expectedRows':len(expected)-1, 'actualRows':len(actual)-1,
             'expectedHeader':expected[0] if expected else None,
             'actualHeader':actual[0] if actual else None,
             'expectedRow':expected[1] if len(expected)>1 else None,
             'actualRow':actual[1] if len(actual)>1 else None})

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def safe_snapshot(page, path):
    try: page.screenshot(path=str(path),full_page=True,timeout=12000)
    except Exception: pass

def button_inventory(page):
    try:
        return page.evaluate('''() => Array.from(document.querySelectorAll('button,a,[role="button"],[role="tab"],[role="menuitem"],input[type="file"]'))
          .slice(0,300).map(e => ({tag:e.tagName, role:e.getAttribute('role'),
          text:(e.innerText||e.value||e.getAttribute('aria-label')||'').trim().slice(0,130),
          accept:e.getAttribute('accept'), type:e.getAttribute('type'),
          hidden:!((e.getBoundingClientRect().width||e.getBoundingClientRect().height))}))''')
    except Exception: return []

def click_named(page, words, attempts=10):
    """Best-effort UI discovery; don't claim success simply for clicking."""
    pat=re.compile('|'.join(map(re.escape, words)), re.I)
    for selector in ('[role="menuitem"]','[role="option"]','button','[role="button"]','[role="tab"]','a'):
        loc=page.locator(selector)
        for i in range(min(loc.count(), attempts)):
            node=loc.nth(i)
            try:
                name=(node.inner_text(timeout=1000) or node.get_attribute('aria-label') or '').strip()
                if pat.search(name) and node.is_visible(timeout=1000):
                    node.click(timeout=3000)
                    page.wait_for_timeout(600)
                    return f'{selector} {name[:70]}'
            except Exception:
                continue
    return None

def box_action_menu_candidates(page):
    """Collect visibly located controls beside the lower Box tab, NEVER the global ⋮.

    This is a cautious location heuristic for the current published app. A single
    candidate is mandatory; uncertain layouts cause HOLD instead of blind clicks.
    """
    return page.evaluate(r'''() => {
      const boxTabs = Array.from(document.querySelectorAll('[role="tab"]'))
        .filter(e => (e.innerText || '').trim() === 'ボックス');
      if (boxTabs.length !== 1) return {reason:'BOX_TAB_NOT_UNIQUE', candidates:[]};
      const tab = boxTabs[0].getBoundingClientRect();
      const vw = innerWidth;
      const candidates = Array.from(document.querySelectorAll('button')).map((el, index) => {
        const r = el.getBoundingClientRect();
        return {index, x:r.left+r.width/2, y:r.top+r.height/2,
          width:r.width, height:r.height, text:(el.innerText||'').trim().slice(0,90),
          aria:el.getAttribute('aria-label'), haspopup:el.getAttribute('aria-haspopup'),
          testids:Array.from(el.querySelectorAll('[data-testid]')).map(e=>e.getAttribute('data-testid')).slice(0,4)};
      }).filter(e => e.width>0 && e.height>0 && e.x>vw*.75 &&
          e.y>tab.top-65 && e.y<tab.bottom+55);
      return {reason: candidates.length===1 ? 'SINGLE_NEAR_BOX' : 'AMBIGUOUS_NEAR_BOX',
        boxTab:{x:tab.x,y:tab.y,width:tab.width,height:tab.height}, candidates};
    }''')

def open_box_action_menu(page, report, stage):
    """Click uniquely situated lower-Box ⋮, only if location is unambiguous."""
    data=box_action_menu_candidates(page)
    report.setdefault('menuInvestigations',[]).append({'stage':stage, **data})
    choices=data['candidates']
    if data['reason']!='SINGLE_NEAR_BOX': return False
    choice=choices[0]
    # Safety: the element must look like an icon-only actions menu, not data entry.
    if choice['text'] and choice['text'].lower() not in ('actions','more_vert','⋮','︙'):
        return False
    page.locator('button').nth(choice['index']).click(timeout=3000)
    page.wait_for_timeout(700)
    report['steps'].append('BOX_ACTION_MENU_OPENED:'+stage)
    return True

def find_csv_upload(page):
    loc=page.locator('input[type="file"]')
    valid=[]
    for i in range(min(loc.count(),20)):
        node=loc.nth(i)
        accept=(node.get_attribute('accept') or '').lower()
        if 'csv' in accept or 'text/' in accept or not accept:
            valid.append((i,accept))
    # An untyped input is ambiguous when several exist: never upload blindly.
    if len(valid)==1: return loc.nth(valid[0][0]),valid[0][1]
    csv_only=[x for x in valid if 'csv' in x[1]]
    if len(csv_only)==1: return loc.nth(csv_only[0][0]),csv_only[0][1]
    return None,None

def browser_probe(url,out,headless=True,chromium_path=None, *, mock_html=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    fixture=out/'probe_input.csv';write_fixture(fixture)
    report={'schema':'pokesleep-real-import-probe-v0.7',
            'checkedAt':datetime.now(timezone.utc).isoformat(),
            'targetUrl':url,'status':'HOLD', 'productionCsvAllowed':False,
            'fixtureSha256':sha256(fixture), 'upstreamImporterExecuted':False,
            'importRoundTripExact':False, 'deployedAppChecked':False,
            'reason':'NOT_EXECUTED', 'steps':[], 'uiInventory':[], 'errors':[],
            'mockOnly':bool(mock_html), 'menuInvestigations':[]}
    try:
        with sync_playwright() as p:
            opts={'headless':headless}
            if chromium_path: opts['executable_path']=chromium_path
            browser=p.chromium.launch(**opts)
            context=browser.new_context(accept_downloads=True,locale='ja-JP',viewport={'width':1280,'height':800})
            page=context.new_page()
            try:
                if mock_html is None:
                    response=page.goto(url,wait_until='domcontentloaded',timeout=30000)
                    page.wait_for_timeout(2500)
                    report['httpStatus']=response.status if response else None
                else:
                    page.set_content(mock_html,wait_until='domcontentloaded')
                    report['httpStatus']=200
                report['pageTitle']=page.title()
                report['steps'].append('PAGE_LOADED')
                safe_snapshot(page,out/'01_before.png')
                report['initialInventory']=button_inventory(page)
                if report['httpStatus']!=200:
                    report['reason']='HTTP_STATUS_NOT_200'
                else:
                    nav=click_named(page,['ボックス','Box'])
                    if nav: report['steps'].append('BOX_NAV:'+nav)
                    # Try visible import actions first; the live UI hides them under
                    # the lower Box-tab ⋮, not the global header's ⋮.
                    action=click_named(page,['インポート','読み込み','読込','Import'])
                    if not action and nav:
                        if open_box_action_menu(page,report,'IMPORT'):
                            safe_snapshot(page,out/'02_box_menu_open.png')
                            report['menuInventory']=button_inventory(page)
                            action=click_named(page,['インポート','読み込み','読込','Import'])
                    if action: report['steps'].append('IMPORT_UI:'+action)
                    # Never upload to an undisclosed hidden file input: require
                    # a visible import UI action was positively identified.
                    file_node,accept=find_csv_upload(page) if action else (None,None)
                    report['uiInventory']=button_inventory(page)
                    safe_snapshot(page,out/'02_import_ui.png')
                    if file_node is None:
                        report['reason']='CSV_FILE_INPUT_NOT_DISCOVERED'
                    else:
                        file_node.set_input_files(str(fixture),timeout=12000)
                        report['steps'].append('CSV_SUBMITTED_TO_FILE_INPUT:'+str(accept))
                        page.wait_for_timeout(1200)
                        confirm=click_named(page,['インポート実行','インポートする','取り込む','確定','追加','Import'])
                        if confirm: report['steps'].append('IMPORT_CONFIRM_CLICKED:'+confirm)
                        page.wait_for_timeout(2000)
                        safe_snapshot(page,out/'03_after_file_upload.png')
                        # Do NOT call this proof of import. Re-export must match every cell.
                        downloads=[]
                        page.on('download',lambda d:downloads.append(d))
                        export=click_named(page,['エクスポート','書き出し','Export'])
                        if not export and nav:
                            if open_box_action_menu(page,report,'EXPORT'):
                                safe_snapshot(page,out/'04_export_menu_open.png')
                                export=click_named(page,['エクスポート','書き出し','Export'])
                        if export: report['steps'].append('EXPORT_UI:'+export)
                        safe_snapshot(page,out/'04_export_ui.png')
                        page.wait_for_timeout(800)
                        dl=downloads[-1] if downloads else None
                        if dl is not None:
                            report['steps'].append('DOWNLOAD:direct-export')
                        if not dl:
                            for phrase in ('CSV','ダウンロード','保存'):
                                try:
                                    with page.expect_download(timeout=3500) as info:
                                        action=click_named(page,[phrase])
                                        if not action: raise RuntimeError('not found')
                                    dl=info.value
                                    report['steps'].append('DOWNLOAD:'+phrase)
                                    break
                                except (PlaywrightTimeoutError, RuntimeError):
                                    continue
                        if dl:
                            dest=out/'roundtrip_export.csv'
                            dl.save_as(str(dest))
                            report['exportSha256']=sha256(dest)
                            try:
                                match,comparison=compare_roundtrip(fixture,dest)
                                report['comparison']=comparison
                                if match:
                                    report['importRoundTripExact']=True
                                    if mock_html is None:
                                        report['upstreamImporterExecuted']=True
                                        report['status']='UI_IMPORT_EXPORT_MATCH'
                                        report['reason']='STRICT_CSV_ROUNDTRIP_MATCH'
                                    else:
                                        report['status']='MOCK_ROUNDTRIP_MATCH'
                                        report['reason']='MOCK_ONLY_NEVER_UPSTREAM_PROOF'
                                else: report['reason']='CSV_ROUNDTRIP_NOT_EXACT'
                            except Exception as exc: report['reason']='ROUNDTRIP_CSV_PARSE_ERROR:'+str(exc)
                        else:
                            report['reason']='CSV_REEXPORT_NOT_OBSERVED'
                report['finalInventory']=button_inventory(page)
            finally:
                context.close();browser.close()
    except Exception as exc:
        report['reason']='PROBE_FAILED'
        report['errors'].append(str(exc))
        report['errors'].append(traceback.format_exc()[-2000:])
    # UI equality is NOT proof that current upstream git checkout matches deployed site.
    report['deployedAppChecked']=False
    (out/'PROBE_RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'reason':report['reason'],
                      'productionCsvAllowed':False,'report':str(out/'PROBE_RESULT.json')},ensure_ascii=False))
    return 0 if report['status'] in ('UI_IMPORT_EXPORT_MATCH','MOCK_ROUNDTRIP_MATCH') else 2

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--site',default='https://nitoyon.github.io/pokesleep-tool/iv/index.ja.html')
    parser.add_argument('--out',default='probe_evidence')
    parser.add_argument('--chromium-path',default=None)
    a=parser.parse_args()
    return browser_probe(a.site,a.out,chromium_path=a.chromium_path)
if __name__=='__main__': sys.exit(main())

