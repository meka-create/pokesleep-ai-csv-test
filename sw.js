/* Shell caching only. Security-critical kit assets always pass through native network fetch. */
const CACHE='ai-bukkomi-scan-shell-step2-reference-blue-20261010-v8-assets';
const SHELL=['./','./index.html','./manifest.webmanifest','./styles.css','./app.js','./zip-store.js','./ui-extras.js','./icons/icon-192.png','./icons/icon-maskable-192.png','./icons/icon-512.png','./icons/icon-512-maskable.png','./icons/icon-maskable-512.png','./icons/favicon-32.png','./icons/apple-touch-icon.png','./assets/ogp-card.png'];
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)).then(()=>self.skipWaiting()));});
self.addEventListener('activate',event=>{event.waitUntil(Promise.all([caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('ai-bukkomi-scan-shell-')&&k!==CACHE).map(k=>caches.delete(k)))),self.clients.claim()]));});
self.addEventListener('fetch',event=>{
  const req=event.request;
  if(req.method!=='GET')return;
  const url=new URL(req.url);
  if(url.origin!==self.location.origin)return;
  // No SW substitution of KIT_VERSION or any model/validator/audit bytes.
  if(url.pathname.includes('/kit-assets/')||url.pathname.endsWith('/update-status.json')||url.pathname.endsWith('/update-status.js'))return;
  if(req.mode==='navigate'||SHELL.some(entry=>new URL(entry,self.registration.scope).pathname===url.pathname)){
    event.respondWith(fetch(req).then(response=>{if(response.ok){const copy=response.clone();caches.open(CACHE).then(c=>c.put(req,copy)).catch(()=>{});}return response;}).catch(async()=>{const cached=await caches.match(req,{ignoreSearch:true});return cached||Response.error();}));
  }
});
