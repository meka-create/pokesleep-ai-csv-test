(()=>{'use strict';
const $=id=>document.getElementById(id);
const tips=$('tipsDialog'), sources=$('sourcesDialog'),more=$('moreMenu'), moreBtn=$('moreBtn');
function openDialog(d){if(!d)return;if(typeof d.showModal==='function'&&!d.open)d.showModal();else d.setAttribute('open','');}
function closeDialog(d){if(!d)return;if(typeof d.close==='function'&&d.open)d.close();else d.removeAttribute('open');}
// The sample is shared with the frozen reference app; show a clean fallback offline.
const tipsExample=$('tips-example-img'),tipsUnavailable=$('tips-example-unavailable');
tipsExample.addEventListener('error',()=>{tipsExample.hidden=true;tipsUnavailable.hidden=false;});
$('tipsBtn').addEventListener('click',()=>openDialog(tips));
$('tipsClose').addEventListener('click',()=>closeDialog(tips));
tips.addEventListener('click',e=>{if(e.target===tips)closeDialog(tips);});
function toggleMenu(open){more.hidden=!open;moreBtn.setAttribute('aria-expanded',String(open));}
moreBtn.addEventListener('click',e=>{e.stopPropagation();toggleMenu(more.hidden);});
$('sourcesMenuItem').addEventListener('click',()=>{toggleMenu(false);openDialog(sources);});
$('sourcesDialog').querySelector('[data-close-dialog]').addEventListener('click',()=>closeDialog(sources));
sources.addEventListener('click',e=>{if(e.target===sources)closeDialog(sources);});
document.addEventListener('click',e=>{if(!more.hidden&&!e.target.closest('.more-wrap'))toggleMenu(false);});
document.addEventListener('keydown',e=>{if(e.key==='Escape')toggleMenu(false);});
// Device-local first-launch key; never shared with the frozen OCR application.
const key='ai_bukkomi_scan_tips_seen_v1';
let seen=false;try{seen=localStorage.getItem(key)==='1';}catch{}
if(!seen){requestAnimationFrame(()=>{openDialog(tips);try{localStorage.setItem(key,'1');}catch{}});}
// The message is a copyable prompt: support clicking the text as well as the icon.
const area=$('prompt-text'), copy=$('copy-prompt');
area.setAttribute('tabindex','0');area.setAttribute('role','button');area.setAttribute('aria-label','AIへの依頼文をコピー');
area.addEventListener('click',()=>copy.click());
area.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();copy.click();}});
if('serviceWorker' in navigator && location.protocol==='https:' || ('serviceWorker' in navigator&&location.hostname==='localhost')){
  window.addEventListener('load',()=>navigator.serviceWorker.register('./sw.js',{scope:'./'}).catch(e=>console.warn('PWA',e)));
}
})();
