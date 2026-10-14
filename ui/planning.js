/* Independent module: no evaluation setting or dataset mutations. */
document.getElementById('page-management').parentElement.appendChild(
  document.getElementById('planning-page-template').content.cloneNode(true));
let planningViews = [];
let planningTimer = null;
let planningPollBusy = false;
let planningStarted = 0;

function planningPayload() {
  return {base_url: document.getElementById('planning-url').value.trim(),
    organization: document.getElementById('planning-org').value.trim(),
    api_version: document.getElementById('planning-api').value.trim(),
    username: document.getElementById('planning-username').value.trim(),
    password: document.getElementById('planning-password').value};
}

async function loadPlanningSettings() {
  try {
    const saved = await api().get_planning_settings();
    await loadCachedInventory('case-planning');
    document.getElementById('planning-url').value = saved.base_url;
    document.getElementById('planning-org').value = saved.organization;
    document.getElementById('planning-api').value = saved.api_version;
    const select = document.getElementById('planning-view');
    if (saved.view_id) {
      planningViews = [{id: saved.view_id, kind: saved.view_kind, name: saved.view_name}];
      select.replaceChildren(new Option(saved.view_name + ' — ذخیره‌شده', '0'));
    } else { planningViews = []; select.replaceChildren(new Option('هنوز View انتخاب نشده', '')); }
    document.getElementById('planning-saved').textContent = `پیش‌فرض ذخیره‌شده: ${saved.view_name || 'انتخاب نشده'}`;
    document.getElementById('planning-last-update').textContent = `آخرین دریافت: ${saved.last_updated ? new Date(saved.last_updated).toLocaleString('fa-IR') : 'هنوز انجام نشده'} — یادداشت: ${Number(saved.counts.notes).toLocaleString('fa-IR')} — فعالیت: ${Number(saved.counts.tasks).toLocaleString('fa-IR')}`;
    const status = await api().get_planning_sync_status();
    if (status.running) beginPlanningPolling();
  } catch (error) { toast(error.message || String(error), 'error'); }
}

async function loadPlanningViews() {
  const button = document.getElementById('planning-list');
  button.disabled = true;
  document.getElementById('planning-progress').textContent = 'در حال دریافت Viewهای قابل دسترسی…';
  try {
    const response = await api().get_planning_views(planningPayload());
    if (!response.ok) throw new Error(response.error);
    const saved = await api().get_planning_settings();
    planningViews = response.views;
    const select = document.getElementById('planning-view');
    select.replaceChildren(new Option('View را انتخاب کنید', ''));
    planningViews.forEach((view, index) => select.add(new Option(`${view.name} — ${view.scope || ''}`, String(index))));
    const selected = planningViews.findIndex(view => view.id === saved.view_id && view.kind === saved.view_kind);
    select.value = selected < 0 ? '' : String(selected);
    document.getElementById('planning-progress').textContent = `${planningViews.length.toLocaleString('fa-IR')} View دریافت شد؛ پیش‌فرض ذخیره‌شده تغییر نکرد.`;
  } catch (error) { toast(error.message, 'error'); }
  finally { button.disabled = false; }
}

async function savePlanningSettings() {
  const value = document.getElementById('planning-view').value;
  const view = value === '' ? null : planningViews[Number(value)];
  if (!view) { toast('یک View از فهرست انتخاب کنید.', 'error'); return; }
  try {
    const response = await api().save_planning_settings({...planningPayload(), view_id: view.id, view_kind: view.kind, view_name: view.name});
    if (!response.ok) throw new Error(response.error);
    toast(response.message, 'success');
    await loadPlanningSettings();
  } catch (error) { toast(error.message, 'error'); }
}

async function syncPlanningView() {
  const button = document.getElementById('planning-sync');
  button.disabled = true;
  try {
    const response = await api().sync_planning_view(planningPayload());
    if (!response.ok) throw new Error(response.error);
    planningStarted = Date.now();
    beginPlanningPolling();
  } catch (error) { button.disabled = false; toast(error.message, 'error'); }
}

function beginPlanningPolling() {
  if (planningTimer) return;
  planningTimer = setInterval(pollPlanningSync, 1000);
  pollPlanningSync();
}

async function pollPlanningSync() {
  if (planningPollBusy) return;
  planningPollBusy = true;
  try {
    const status = await api().get_planning_sync_status();
    const seconds = status.elapsed_seconds ?? Math.floor((Date.now()-planningStarted)/1000);
    document.getElementById('planning-progress').textContent = `${status.stage} — ${seconds.toLocaleString('fa-IR')} ثانیه${status.detail ? ' — ' + status.detail : ''}${status.total ? ` — ${status.completed}/${status.total}` : ''}${status.changed ? ` — جدید/تغییرکرده: ${status.changed.notes} یادداشت و ${status.changed.tasks} فعالیت` : ''}${status.error ? ' — ' + status.error : ''}`;
    if (!status.running) {
      clearInterval(planningTimer); planningTimer = null;
      document.getElementById('planning-sync').disabled = false;
      if (status.done) await loadPlanningSettings();
    }
  } catch (error) {
    clearInterval(planningTimer); planningTimer = null;
    document.getElementById('planning-sync').disabled = false;
    toast(error.message, 'error');
  } finally { planningPollBusy = false; }
}
