import { makeZip } from './zip-store.js?v=20261010-auditfix-r2';

const KIT_FILES = [
  'START_HERE.md', 'AI_INSTRUCTIONS.md', 'READING_RULES.md',
  'PROGRESS_PROTOCOL.md',
  'MASTER_DATA.json', 'CSV_SCHEMA.json', 'KIT_VERSION.json',
  'VALIDATOR.py', 'PROTOTYPE_EXPORT_GATE.py', 'RELEASE_EXPORT_GATE.py', 'RECORDS_TEMPLATE.json',
  'SPECIES_AUDIT_GUIDE.md', 'SPECIES_AUDIT.py', 'species_evidence_lab.py',
  'numeric_observer.py', 'SPECIES_OBSERVATIONS_TEMPLATE.json'
];
// The KIT_VERSION.json raw SHA-256 is pinned in this versioned script.
// KIT_VERSION.json pins the other 15 files; self-hashing inside JSON is impossible.
// Any old/mixed/corrupt kit must fail closed BEFORE makeZip/saveZip.
const SITE_HOTFIX_ID = 'v08c-auditfix-20261010-r2-ai-bukkomi-scan-step1-midfix1';
const EXPECTED_KIT_VERSION = '0.12.0-prototype';
const KIT_VERSION_RAW_SHA256 = 'cc515bfe68d9461d0b8fe2a08733267252107ea375411dde8af793233d88e64a';
const FILES = new Map();
let seq = 0, lastZip = null, lastName = '', busy = false, hashing = 0, hashError = false;
const $ = s => document.querySelector(s);
const fileInput = $('#choose-files'), selection = $('#selection'), list = $('#files');
const buildButton = $('#build'), status = $('#message'), ready = $('#ready');
const allowed = /\.(png|jpg|jpeg|webp)$/i;
const MAX_ARCHIVE_BYTES = 300 * 1024 * 1024; // technical browser-memory guard, NOT empirically verified AI capacity
function fmt(bytes) { return (bytes / 1024 / 1024).toFixed(1) + ' MB'; }
function announce(msg, error=false) { status.textContent=msg; status.classList.toggle('error',error); }
function setBusy(b) { busy=b; buildButton.disabled = b || hashing > 0 || hashError || !FILES.size; fileInput.disabled=b; buildButton.innerHTML=b?'ZIPを作成しています…':'<span>ZIPを作成する</span><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 3v13m-5-5 5 5 5-5M4 19h16"/></svg>'; }
function setZipProgress(p,label){const bar=$('#zip-progress'),fill=$('#zip-progress-fill');if(!bar||!fill)return;bar.hidden=false;fill.style.width=Math.round(Math.max(0,Math.min(100,p)))+'%';$('#zip-progress-label').textContent=label;}
function hideZipProgress(){const bar=$('#zip-progress');if(bar)bar.hidden=true;}
function escapeHtml(x) { return x.replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function imageMagicMatches(data, filename) {
  const head = new Uint8Array(data, 0, Math.min(data.byteLength, 64));
  const bytesAt = (offset, values) => values.every((value, i) => head[offset + i] === value);
  const suffix = filename.toLowerCase().split('.').pop();
  if (suffix === 'png') {
    if (data.byteLength < 45) return false;
    const tail = new Uint8Array(data, data.byteLength - 12, 12);
    // The Validator checks the IHDR CRC; reject corrupted headers at upload time.
    // CRC covers PNG chunk type + IHDR data (bytes 12 through 28).
    let crc = 0xffffffff;
    for (let i = 12; i < 29; i++) {
      crc = (crc ^ head[i]) >>> 0;
      for (let bit = 0; bit < 8; bit++)
        crc = ((crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0)) >>> 0;
    }
    const actualCrc = (crc ^ 0xffffffff) >>> 0;
    const dv = new DataView(data);
    return bytesAt(0, [137,80,78,71,13,10,26,10]) && bytesAt(12, [73,72,68,82])
      && dv.getUint32(8, false) === 13
      && dv.getUint32(29, false) === actualCrc
      && Array.from(tail).join(',') === '0,0,0,0,73,69,78,68,174,66,96,130';
  }
  if (suffix === 'jpg' || suffix === 'jpeg') {
    if (data.byteLength < 20) return false;
    const tail = new Uint8Array(data, data.byteLength - 2, 2);
    return bytesAt(0, [255,216,255]) && tail[0] === 255 && tail[1] === 217;
  }
  if (suffix === 'webp') {
    if (data.byteLength < 20) return false;
    return bytesAt(0, [82,73,70,70]) && bytesAt(8, [87,69,66,80])
      && (['VP8 ', 'VP8L', 'VP8X'].some(v => [...v].every((ch, i) => head[12 + i] === ch.charCodeAt(0))))
      && new DataView(data).getUint32(4, true) + 8 === data.byteLength;
  }
  return false;
}
async function digestFile(file) {
  const bytes = await file.arrayBuffer();
  if (!imageMagicMatches(bytes, file.name))
    throw new Error(`画像の拡張子と実体が不一致/破損の疑い: ${file.name}`);
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(hash)].map(v=>v.toString(16).padStart(2,'0')).join('');
}
function hexHash(bytes) {
  return [...new Uint8Array(bytes)].map(v=>v.toString(16).padStart(2,'0')).join('');
}
async function sha256(bytes) {
  return hexHash(await crypto.subtle.digest('SHA-256', bytes));
}
function requireExactNames(actual, expected, label) {
  if (actual.length !== expected.length ||
      new Set(actual).size !== expected.length ||
      expected.some(name => !actual.includes(name))) {
    throw new Error(`${label}の構成が新旧混在または欠落しています（必要: ${expected.length}件）`);
  }
}
async function verifiedKitAssets() {
  requireExactNames(KIT_FILES, [
    'START_HERE.md', 'AI_INSTRUCTIONS.md', 'READING_RULES.md',
    'PROGRESS_PROTOCOL.md', 'MASTER_DATA.json', 'CSV_SCHEMA.json',
    'KIT_VERSION.json', 'VALIDATOR.py', 'PROTOTYPE_EXPORT_GATE.py',
    'RELEASE_EXPORT_GATE.py', 'RECORDS_TEMPLATE.json',
    'SPECIES_AUDIT_GUIDE.md', 'SPECIES_AUDIT.py', 'species_evidence_lab.py',
    'numeric_observer.py', 'SPECIES_OBSERVATIONS_TEMPLATE.json'
  ], 'ZIP同梱キット');
  const kitData=[];
  for (const name of KIT_FILES) {
    const resp=await fetch(new URL('./kit-assets/'+name,import.meta.url),{
      cache:'no-store', redirect:'error'
    });
    if(!resp.ok)throw new Error(`必要ファイルの取得に失敗: ${name} (${resp.status})`);
    kitData.push({name,bytes:new Uint8Array(await resp.arrayBuffer())});
  }
  const byName = new Map(kitData.map(item=>[item.name,item.bytes]));
  requireExactNames([...byName.keys()], KIT_FILES, '取得済みキット');
  const versionBytes=byName.get('KIT_VERSION.json');
  if (await sha256(versionBytes) !== KIT_VERSION_RAW_SHA256) {
    throw new Error('KIT_VERSION.json の生バイトSHA-256が不一致です。キャッシュや資産混在を検出したためZIP作成を拒否しました。');
  }
  let version;
  try { version=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(versionBytes)); }
  catch { throw new Error('KIT_VERSION.json の解析に失敗しました'); }
  if(version.siteHotfixId!==SITE_HOTFIX_ID || version.kitVersion!==EXPECTED_KIT_VERSION ||
     version.rawAssetHashFormat!=='sha256-raw-file-bytes' ||
     version.productionCsvAllowed!==false || version.compatibilityVerified!==false ||
     !String(version.status).includes('HOLD')) {
    throw new Error('必要ファイルの整合性を確認できません。再読み込みしてください。');
  }
  const required=KIT_FILES.filter(name=>name!=='KIT_VERSION.json');
  const hashes=version.rawAssetSha256;
  if(!hashes || typeof hashes!=='object' || Array.isArray(hashes))
    throw new Error('生バイトハッシュ一覧がありません');
  requireExactNames(Object.keys(hashes),required,'SHA-256一覧');
  for (const name of required) {
    const expected=hashes[name];
    if(typeof expected!=='string'||!/^[0-9a-f]{64}$/.test(expected)||
       await sha256(byName.get(name)) !== expected) {
      throw new Error(`${name} の生バイトSHA-256が不一致です。ZIPを作成しません。`);
    }
  }
  return {kitData,version};
}
function totals() { return [...FILES.values()].reduce((s,r)=>s+r.file.size,0); }
function updateDuplicate() {
  const counts = {};
  for(const r of FILES.values()) if(r.hash) counts[r.hash] = (counts[r.hash]||0)+1;
  const duplicates = Object.values(counts).reduce((n,c)=>n+Math.max(0,c-1),0);
  $('#duplicate-area').hidden = !duplicates;
  $('#duplicate-summary').textContent = `${duplicates}枚がほかの選択画像と完全に一致しています。確認のうえ残すか除外するか選んでください。`;
}
function resetDuplicateConfirmation(){document.querySelectorAll('input[name="duplicate-mode"]').forEach(x=>x.checked=false);}
function render() {
  const rows=[...FILES.values()];
  selection.hidden = rows.length===0;
  $('#count').textContent = rows.length+'枚'; $('#size').textContent='合計 '+fmt(totals());
  list.replaceChildren();
  rows.forEach(r=>{
    const li=document.createElement('li');
    const img=document.createElement('img'); img.src=r.url; img.alt='画像プレビュー'; img.loading='lazy';
    const label=document.createElement('span'); label.className='filename';label.textContent=r.file.name; label.title=r.file.name;
    const button=document.createElement('button');button.type='button';button.textContent='×';button.setAttribute('aria-label',r.file.name+' を除外');
    button.addEventListener('click',()=>{if(busy)return; resetDuplicateConfirmation();URL.revokeObjectURL(r.url);FILES.delete(r.id);render();ready.hidden=true;lastZip=null;});
    li.append(img,label,button);list.append(li);
  });
  updateDuplicate(); setBusy(false);
}
async function add(files) {
  if (busy) return;
  const arr=[...files];
  const rejected=arr.filter(f=>!allowed.test(f.name) || !['image/png','image/jpeg','image/webp',''].includes(f.type));
  if(rejected.length) announce(`${rejected.length}件の非対応形式を追加しませんでした。PNG/JPG/WebPのみ対応です。`,true);
  const added=[];
  for(const f of arr) {
    if(rejected.includes(f)) continue;
    const id=++seq;
    const row={id,file:f,url:URL.createObjectURL(f),hash:null};
    FILES.set(id,row);added.push(row);
  }
  resetDuplicateConfirmation();
  ready.hidden=true;lastZip=null;
  hashing++;render();fileInput.value='';
  try {
    if (!crypto?.subtle) throw new Error('SHA-256の計算にはHTTPSまたはlocalhostが必要です。');
    let rejectedBinary = 0;
    for(const row of added) {
      try { row.hash = await digestFile(row.file); }
      catch (error) {
        rejectedBinary++;
        URL.revokeObjectURL(row.url);
        FILES.delete(row.id);
      }
    }
    hashError=false;
    if (rejectedBinary) announce(`${rejectedBinary}件は画像の実体形式が不正なため除外しました。`, true);
  } catch(error) {hashError=true;announce(error.message||String(error),true);}
  finally {hashing--;render();}
}
fileInput.addEventListener('change',()=>add(fileInput.files));
$('#clear-all').addEventListener('click',()=>{if(busy)return;resetDuplicateConfirmation();for(const r of FILES.values()) URL.revokeObjectURL(r.url);FILES.clear();ready.hidden=true;lastZip=null;render();announce('画像を解除しました。');});
const dz = $('#dropzone');
dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('dragover');});
dz.addEventListener('dragleave',()=>dz.classList.remove('dragover'));
dz.addEventListener('drop',e=>{e.preventDefault();dz.classList.remove('dragover');add(e.dataTransfer.files);});
dz.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();fileInput.click();}});
function saveZip(blob,name){const url=URL.createObjectURL(blob); const a=document.createElement('a');a.href=url;a.download=name; document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),45000);}
async function build() {
  if(!FILES.size || busy || hashing > 0 || hashError) return;
  if (!$('#duplicate-area').hidden && !document.querySelector('input[name="duplicate-mode"]:checked')) {announce('完全重複があります。重複画像の扱いを選んでください。',true);return;}
  if(!crypto?.subtle){announce('SHA-256計算にはHTTPSまたはlocalhostが必要です。',true);return;}
  const bytes=totals();
  if(bytes>MAX_ARCHIVE_BYTES){announce(`合計サイズは${fmt(MAX_ARCHIVE_BYTES)}までです。`,true);return;}
  setBusy(true);ready.hidden=true;lastZip=null;lastName='';setZipProgress(4,'画像を確認中…');announce('画像を検証しています…');
  try {
    if([...FILES.values()].some(row=>!row.hash)) throw new Error('画像ハッシュが未検証です');
    const chosen=[];const seen=new Set();
    const dedupe=document.querySelector('input[name="duplicate-mode"]:checked')?.value==='dedupe';
    for(const row of FILES.values()){
      if(dedupe&&seen.has(row.hash)) continue;
      seen.add(row.hash);chosen.push(row);
    }
    if(!chosen.length) throw new Error('出力する画像がありません');
    const archiveEntries=[];
    const manifest=[];
    for(let i=0;i<chosen.length;i++) {
      const row=chosen[i],ext=row.file.name.match(/\.(png|jpg|jpeg|webp)$/i)[1].toLowerCase();
      const imageId='IMG-'+String(i+1).padStart(4,'0');
      const path=`images/${imageId}.${ext}`;
      const binary=new Uint8Array(await row.file.arrayBuffer());
      if(await sha256(binary) !== row.hash || !imageMagicMatches(binary.buffer, row.file.name))
        throw new Error(`画像の再読込時に内容が変化しました: ${row.file.name}`);
      archiveEntries.push({name:path,bytes:binary});
      manifest.push({id:imageId,path,originalFilename:row.file.name,size:binary.length,sha256:row.hash});
      setZipProgress(5+Math.round((i+1)/chosen.length*65),`${i+1} / ${chosen.length}枚を確認中`);
    }
    setZipProgress(76,'同梱ファイルを確認中…');announce('ファイルを確認しています…');
    const {kitData,version}=await verifiedKitAssets();
    const doc={schemaVersion:'ai-input-manifest-v0.1',kitVersion:version.kitVersion,images:manifest,inputImageCount:chosen.length,
      sourceSelectedCount:FILES.size,duplicatePolicy:dedupe?'user-selected-remove-exact':'user-selected-keep-all'};
    archiveEntries.push(...kitData,{name:'INPUT_MANIFEST.json',bytes:new TextEncoder().encode(JSON.stringify(doc,null,2)+'\n')});
    setZipProgress(90,'ZIPを作成中…');announce('ZIPを作成しています…');
    lastZip=makeZip(archiveEntries);
    lastName='AI_Bukkomi_Scan_'+chosen.length+'images.zip';
    $('#archive-name').textContent=lastName;
    $('#archive-count').textContent=chosen.length+'枚 / '+fmt(lastZip.size);
    saveZip(lastZip,lastName);
    ready.hidden=false;ready.scrollIntoView({behavior:'smooth',block:'start'});
    setZipProgress(100,'完了');announce(`${chosen.length}枚のZIPを作成しました。`);
  } catch(err) {announce(err.message||String(err),true);console.error(err);hideZipProgress();}
  finally {setBusy(false);}
}
buildButton.addEventListener('click',build);
$('#redownload').addEventListener('click',()=>{if(lastZip)saveZip(lastZip,lastName);});
$('#copy-prompt').addEventListener('click',async()=>{
  try {await navigator.clipboard.writeText($('#prompt-text').textContent);$('#copy-feedback').textContent='コピーしました';$('#copy-prompt').setAttribute('aria-label','コピーしました');setTimeout(()=>{$('#copy-feedback').textContent='クリックでコピーできます';$('#copy-prompt').setAttribute('aria-label','依頼文をコピー');},1800);}
  catch {announce('コピーできませんでした。表示された文章を選択してコピーしてください。',true);}
});
