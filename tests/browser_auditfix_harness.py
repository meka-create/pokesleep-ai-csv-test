"""Controlled Chromium DOM test of actual index/app.js/zip-store.js, NOT a live HTTP/GitHub Pages E2E.
Browser navigation to localhost and HTTPS is blocked by the environment administrator.
The only shims replace external asset fetch and unavailable about:blank crypto.subtle.
"""
import argparse,base64,hashlib,io,json,pathlib,struct,zlib,copy,unittest,os,re
from playwright.sync_api import sync_playwright,expect
BASE=pathlib.Path(__file__).parents[1]
SITE=pathlib.Path(os.environ.get('HOTFIX_SITE_DIR', BASE/'hotfix_site'))
EVIDENCE=BASE/'evidence/auditfix-browser'
EVIDENCE.mkdir(exist_ok=True)

def png(i):
    # 1x1 RGB PNG; unique RGB and hence unique SHA-256 for 172 entries.
    rgb=bytes([(i>>8)&255,i&255, (i*7)%256]); raw=b'\0'+rgb
    def chunk(tp,data): return struct.pack('>I',len(data))+tp+data+struct.pack('>I',zlib.crc32(tp+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')

RAW={p.name:p.read_bytes() for p in (SITE/'kit-assets').iterdir() if p.is_file()}
assert len(RAW)==16
APP=(SITE/'app.js').read_text()
ZIP=(SITE/'zip-store.js').read_text().replace('export function makeZip','function makeZip')
APP=re.sub(r"import \{ makeZip \} from '\./zip-store\.js\?v=[^']+';", '', APP)
APP=APP.replace('import.meta.url',"'https://test.invalid/app.js?v=20261010-auditfix-r2'")
assert 'import.meta' not in APP
SOURCE=ZIP+'\n'+APP

class BrowserTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
    cls.p=sync_playwright().start()
    cls.browser=cls.p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
 @classmethod
 def tearDownClass(cls):
    cls.browser.close(); cls.p.stop()
 def new_page(self,assets):
    pg=self.browser.new_page(accept_downloads=True)
    pg.goto('about:blank')
    pg.set_content((SITE/'index.html').read_text(),wait_until='domcontentloaded')
    pg.expose_function('sha256Bridge',lambda bs: list(hashlib.sha256(bytes(bs)).digest()))
    pg.evaluate('''() => {
      const bridge=(name,arr)=>window.sha256Bridge(Array.from(new Uint8Array(arr)));
      Object.defineProperty(window,'crypto',{configurable:true,value:{subtle:{digest:async (name,arr)=>new Uint8Array(await bridge(name,arr)).buffer}}});
      window.__fetchCalls=[];
      window.__assetPayloads={};
      window.fetch=async (uri,options={})=>{
        const u=new URL(String(uri));
        const key=u.pathname.split('/').pop();
        window.__fetchCalls.push({key, cache:options.cache, redirect:options.redirect});
        const b64=window.__assetPayloads[key];
        if(b64===undefined) return new Response('missing', {status:404});
        const bin=atob(b64); const bytes=Uint8Array.from(bin,ch=>ch.charCodeAt(0));
        return new Response(bytes,{status:200});
      };
      window.__downloads=[];
    }''')
    pg.evaluate('(assets)=> {window.__assetPayloads=assets;}',{k:base64.b64encode(v).decode('ascii') for k,v in assets.items()})
    pg.add_script_tag(content=SOURCE)
    return pg
 def attach(self,pg,count=2):
    pg.locator('#choose-files').set_input_files([{'name':f'IMG_{n:04}.png','mimeType':'image/png','buffer':png(n)} for n in range(1,count+1)])
    expect(pg.locator('#build')).to_be_enabled(timeout=30000)
    expect(pg.locator('#count')).to_have_text(f'{count}枚',timeout=30000)
 def build_zip(self,pg,count,label):
    self.attach(pg,count)
    with pg.expect_download(timeout=40000) as info:
        pg.locator('#build').click()
    d=info.value
    out=EVIDENCE/f'{label}.zip'
    d.save_as(out)
    self.assertIn('完了：',pg.locator('#message').inner_text())
    with __import__('zipfile').ZipFile(out) as z:
        self.assertIsNone(z.testzip())
        names=z.namelist(); self.assertEqual(len(names),count+17)
        self.assertEqual(len(set(names)),count+17)
        self.assertEqual(sum(n.startswith('kit-assets/') for n in names),0) # historical flat kit layout
        m=json.loads(z.read('INPUT_MANIFEST.json'))
        self.assertEqual(len(m['images']),count)
        for n in range(1,count+1):
            item=m['images'][n-1]; b=z.read(item['path']); self.assertEqual(b,png(n))
            self.assertEqual(item['sha256'],hashlib.sha256(b).hexdigest())
            self.assertEqual(item['originalFilename'],f'IMG_{n:04}.png')
        for filename,b in RAW.items():self.assertEqual(z.read(filename),b)
        ver=json.loads(z.read('KIT_VERSION.json'))
        self.assertEqual(ver['kitVersion'],'0.12.0-prototype')
        self.assertIs(ver['productionCsvAllowed'],False)
        self.assertIs(ver['compatibilityVerified'],False)
    calls=pg.evaluate('window.__fetchCalls')
    self.assertEqual(len(calls),16)
    self.assertTrue(all(c['cache']=='no-store' and c['redirect']=='error' for c in calls))
    pg.close()
    return out
 def assert_rejected(self,assets,count,label,errmsg):
    pg=self.new_page(assets)
    downloads=[]; pg.on('download',lambda d: downloads.append(d))
    self.attach(pg,count)
    pg.locator('#build').click()
    expect(pg.locator('#message')).to_contain_text(errmsg,timeout=6000)
    self.assertEqual(downloads,[],label)
    self.assertTrue(pg.locator('#ready').is_hidden())
    self.assertFalse(pg.locator('#message').inner_text().startswith('完了'))
    self.assertEqual(pg.locator('#redownload').get_attribute('disabled'),None) # hidden in ready
    pg.close()
 def test_01_happy_10(self):
    self.build_zip(self.new_page(RAW),10,'HAPPY_10')
 def test_02_happy_172(self):
    self.build_zip(self.new_page(RAW),172,'HAPPY_172_SYNTHETIC')
 def test_03_mutated_master(self):
    a=dict(RAW);a['MASTER_DATA.json']=a['MASTER_DATA.json']+b'\n'
    self.assert_rejected(a,2,'master','MASTER_DATA.json の生バイト')
 def test_04_mutated_schema(self):
    a=dict(RAW);a['CSV_SCHEMA.json']=a['CSV_SCHEMA.json']+b' '
    self.assert_rejected(a,2,'schema','CSV_SCHEMA.json の生バイト')
 def test_05_mutated_validator(self):
    a=dict(RAW);a['VALIDATOR.py']=a['VALIDATOR.py']+b'# tampered\n'
    self.assert_rejected(a,2,'validator','VALIDATOR.py の生バイト')
 def test_06_mutated_kit_version(self):
    a=dict(RAW);a['KIT_VERSION.json']=a['KIT_VERSION.json']+b' '
    self.assert_rejected(a,2,'version','KIT_VERSION.json の生バイト')
 def test_07_old_kit_version(self):
    old=json.loads(RAW['KIT_VERSION.json']);old.pop('rawAssetSha256');old.pop('rawAssetHashFormat');old.pop('siteHotfixId');
    a=dict(RAW);a['KIT_VERSION.json']=json.dumps(old,ensure_ascii=False).encode()
    self.assert_rejected(a,2,'oldversion','KIT_VERSION.json の生バイト')
 def test_08_missing_file(self):
    a=dict(RAW);del a['SPECIES_AUDIT.py']
    self.assert_rejected(a,2,'missing','必要ファイルの取得に失敗')
 def test_09_old_eight_assets(self):
    a={key:RAW[key] for key in ['START_HERE.md','AI_INSTRUCTIONS.md','READING_RULES.md','MASTER_DATA.json','CSV_SCHEMA.json','KIT_VERSION.json','VALIDATOR.py','RECORDS_TEMPLATE.json']}
    self.assert_rejected(a,2,'eight','必要ファイルの取得に失敗')
 def test_10_modified_progress(self):
    a=dict(RAW);a['PROGRESS_PROTOCOL.md']=a['PROGRESS_PROTOCOL.md']+b'\n'
    self.assert_rejected(a,2,'progress','PROGRESS_PROTOCOL.md の生バイト')
 def test_11_modified_non_validator_script(self):
    a=dict(RAW);a['species_evidence_lab.py']=a['species_evidence_lab.py']+b'\n'
    self.assert_rejected(a,2,'script','species_evidence_lab.py の生バイト')
 def test_12_modified_instructions(self):
    a=dict(RAW);a['START_HERE.md']=a['START_HERE.md']+b'\n'
    self.assert_rejected(a,2,'instr','START_HERE.md の生バイト')
 def test_13_modified_binding_template(self):
    a=dict(RAW);a['RECORDS_TEMPLATE.json']=a['RECORDS_TEMPLATE.json']+b'\n'
    self.assert_rejected(a,2,'template','RECORDS_TEMPLATE.json の生バイト')
 def test_14_changed_production_flag(self):
    a=dict(RAW);v=json.loads(a['KIT_VERSION.json']);v['productionCsvAllowed']=True
    a['KIT_VERSION.json']=json.dumps(v).encode()
    self.assert_rejected(a,2,'production','KIT_VERSION.json の生バイト')
 def test_15_modified_all_15_in_turn(self):
    for n in ['species_evidence_lab.py']:
        with self.subTest(name=n):
            print('SUBTEST', n,flush=True)
            a=dict(RAW);a[n]=a[n]+b'X'
            self.assert_rejected(a,1,'all16:'+n,n+' の生バイト')
 def test_16_index_cache_urls(self):
    html=(SITE/'index.html').read_text()
    self.assertRegex(html,r'app\.js\?v=[0-9A-Za-z-]+')
    self.assertRegex(html,r'styles\.css\?v=[0-9A-Za-z-]+')
    self.assertRegex((SITE/'app.js').read_text(),r'zip-store\.js\?v=[0-9A-Za-z-]+')

if __name__=='__main__':
 unittest.main(verbosity=2)
