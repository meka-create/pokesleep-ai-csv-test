/* Upstream update indicator. Independent of ZIP assets: a broken status feed
   must never silently look healthy. All external content uses textContent. */
const WATCH_URL = new URL('./update-status.json', import.meta.url);
const WATCH_STALE_MS = 50 * 3600 * 1000; // GitHub scheduled workflows can be delayed
const $watch = selector => document.querySelector(selector);
const watchBadge = $watch('#update-watch-button');
const watchModal = $watch('#update-watch-dialog');
const watchState = $watch('#update-watch-state');
const validStates = new Set(['healthy', 'attention', 'pending']);
const pendingUpdateCodes = new Set([
  'UPDATE_REQUIRES_VALIDATION', 'IMPORTER_E2E_NOT_VERIFIED',
  'AUTOMATIC_RELEASE_NOT_VERIFIED', 'AUTOPROMOTION_REJECTED',
  'UPSTREAM_PREFLIGHT_FAILED'
]);
function invalidWatch(message) {
  return {state:'attention',message:'更新状態を確認できません',details:message,
          checkedAt:null,runUrl:null,reasonCode:'STATUS_UNAVAILABLE'};
}
function readWatch(data, now = Date.now()) {
  if(!data || data.schemaVersion !== 'pokesleep-upstream-status-v1' ||
     !validStates.has(data.state) || data.productionCsvAllowed !== false ||
     (data.checkedAt !== null && typeof data.checkedAt !== 'string') ||
     typeof data.message !== 'string' || typeof data.details !== 'string' ||
     data.message.length > 250 || data.details.length > 1000)
    return invalidWatch('監視情報の形式が不正です。公開データの確認が必要です。');
  if(data.state === 'pending') {
    const createdAt=Date.parse(data.createdAt || '');
    if(!Number.isFinite(createdAt) || createdAt > now + 10*60*1000 || now-createdAt > WATCH_STALE_MS)
      return invalidWatch('監視が有効になっていないか、初回チェックが遅延しています。GitHub Actionsのスケジュールと権限を確認してください。');
    return data;
  }
  const time = Date.parse(data.checkedAt || '');
  if(!Number.isFinite(time) || time > now + 10*60*1000 || now-time > WATCH_STALE_MS)
    return invalidWatch('定期確認の結果が古いか日時が不正です。GitHub Actionsの実行履歴を確認してください。');
  return data;
}
function renderWatch(data) {
  // Normal and initial-check states are completely silent.
  watchBadge.dataset.state = data.state;
  watchBadge.hidden = data.state !== 'attention';
  if (watchBadge.hidden && watchModal.open) watchModal.close?.();
  // Never surface upstream diagnostics or repository URLs to end users.
  watchBadge.textContent = '⚠️';
  watchBadge.setAttribute('aria-label', 'データ更新のお知らせを表示');
  watchState.textContent = pendingUpdateCodes.has(data.reasonCode)
    ? '最新データの更新について確認が必要です。'
    : 'データの更新状況を確認できませんでした。';
}
async function refreshWatch() {
  try {
    const response = await fetch(new URL(WATCH_URL.href+'?t='+Date.now()),
      {cache:'no-store',redirect:'error',signal:AbortSignal.timeout(10000)});
    if(!response.ok) throw new Error('HTTP '+response.status);
    const data = await response.json();
    renderWatch(readWatch(data));
  } catch (err) {renderWatch(invalidWatch('監視情報を取得できませんでした。インターネット接続と公開サイトの更新状況を確認してください。'));}
}
watchBadge.addEventListener('click',()=>{
  if(typeof watchModal.showModal === 'function')watchModal.showModal();
  else watchModal.setAttribute('open','');
});
$watch('#update-watch-close').addEventListener('click',()=>watchModal.close?.());
watchModal.addEventListener('click',event=>{ if(event.target===watchModal)watchModal.close?.(); });
$watch('#update-watch-close-bottom').addEventListener('click',()=>watchModal.close?.());
refreshWatch();
window.addEventListener('focus',refreshWatch);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshWatch();});
