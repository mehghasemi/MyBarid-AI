let managementData = null;
let managementLimit = 300;
const managementLabels = {pass: 'قبول', needs_correction: 'نیازمند اصلاح', not_applicable: 'نامرتبط', insufficient_data: 'کمبود داده', measured: 'بدون حدنصاب'};

async function loadManagementEvaluation() {
  let response;
  try { response = await api().get_management_evaluation(); }
  catch (error) { response = {ok: false, error: error.message || 'دریافت ارزیابی ناموفق بود.'}; }
  managementData = response.ok ? response : null;
  document.getElementById('management-info').textContent = response.ok
    ? `${response.scope} — زمان ثابت ارزیابی: ${new Date(response.evaluation_at).toLocaleString('fa-IR')} — ${response.attribution_notice}`
    : response.error;
  if (!response.ok) {
    document.getElementById('management-rows').innerHTML = '';
    document.getElementById('management-count').textContent = '';
    document.getElementById('management-more').hidden = true;
    document.getElementById('management-thresholds').innerHTML = '';
    document.getElementById('management-severity-settings').innerHTML = '';
    document.getElementById('management-actions').innerHTML = '';
    return;
  }
  let role = 'admin';
  if (!window.pywebview) {
    try { role = (await api().get_current_user()).user.role; } catch (_error) { role = 'viewer'; }
  }
  ['management-status-mapping', 'management-severity-settings', 'management-thresholds'].forEach(id => {
    const panel = document.getElementById(id)?.closest('.card');
    if (panel) panel.hidden = role !== 'admin';
  });
  const actionPanel = document.getElementById('action-due')?.closest('.card');
  if (actionPanel) actionPanel.hidden = role === 'viewer';
  document.getElementById('management-status-mapping').value = JSON.stringify(response.status_mapping || {}, null, 2);
  const summary = response.summary;
  document.getElementById('management-info').textContent += ` — توزیع وضعیت: ${JSON.stringify(summary.status_distribution)} — میانه رسیدگی: ${summary.resolution_median_hours ?? 'غیرقابل‌محاسبه'} — صدک ۹۰: ${summary.resolution_p90_hours ?? 'غیرقابل‌محاسبه'} — قابل‌محاسبه: ${summary.resolution_eligible}/${summary.resolution_denominator}`;
  const criteria = (response.cases[0]?.criteria || []).filter(c => c.category !== 'qualitative');
  document.getElementById('management-severity-settings').innerHTML = (response.catalog || []).map(c => `<div class="field"><label>${escapeHtml(c.name)}</label><select data-criterion-severity="${escapeHtml(c.id)}">${[['info','اطلاعاتی'],['warning','هشدار'],['critical','بحرانی']].map(([value,label]) => `<option value="${value}" ${value === (response.severity_settings[c.id] || 'warning') ? 'selected' : ''}>${label}</option>`).join('')}</select></div>`).join('');
  const structured = new Set(['status_dwell', 'status_entries', 'owner_changes', 'followup_delay']);
  document.getElementById('management-thresholds').innerHTML = criteria.filter(c => !structured.has(c.id)).map(c => `<div class="field"><label>${escapeHtml(c.name)} (${c.unit || 'ساعت تقویمی'})</label><input type="number" min="0" step="any" data-management-threshold="${escapeHtml(c.id)}" value="${response.thresholds[c.id] ?? ''}" placeholder="تعریف نشده"></div>`).join('');
  document.getElementById('management-actions').innerHTML = response.actions.map(a => `<p>${escapeHtml(a.case_key)} — ${escapeHtml(a.decision)} — مسئول: ${escapeHtml(a.responsible)} — موعد: ${escapeHtml(a.due_at)}</p>`).join('');
  renderManagementRows();
}

function renderManagementRows() {
  if (!managementData) return;
  const status = document.getElementById('management-state').value;
  const query = document.getElementById('management-query').value.trim().toLocaleLowerCase('fa-IR');
  const rows = managementData.cases.flatMap(c => c.criteria.map(m => ({c, m}))).filter(({c, m}) =>
    (status === 'all' || m.status === status) &&
    (document.getElementById('management-severity').value === 'all' || m.severity === document.getElementById('management-severity').value) &&
    (!query || [c.case_key,c.customer,c.owner,c.service,c.status,m.name,m.id].join(' ').toLocaleLowerCase('fa-IR').includes(query)));
  document.getElementById('management-count').textContent = `نمایش ${Math.min(rows.length, managementLimit).toLocaleString('fa-IR')} از ${rows.length.toLocaleString('fa-IR')} نتیجه معیار`;
  document.getElementById('management-more').hidden = rows.length <= managementLimit;
  document.getElementById('management-rows').innerHTML = rows.slice(0, managementLimit).map(({c, m}) => `<tr><td>${escapeHtml(c.case_number || c.case_key)}<br><small>${escapeHtml(c.customer || '')} — ${escapeHtml(c.status || '')}<br>مالک فعلی: ${escapeHtml(c.owner || 'نامشخص')} — ${escapeHtml(c.service || '')}</small></td><td>${escapeHtml(m.name)}<br><small>${escapeHtml(m.id)}</small></td><td>${escapeHtml(m.value === null ? 'قابل‌محاسبه نیست' : typeof m.value === 'object' ? JSON.stringify(m.value) : Number(m.value).toLocaleString('fa-IR'))} ${escapeHtml(m.unit || '')}</td><td>${m.threshold === null ? 'تعریف نشده' : Number(m.threshold).toLocaleString('fa-IR')}</td><td>${managementLabels[m.status]}<br>${({warning:'هشدار',critical:'بحرانی',info:'اطلاعاتی'})[m.severity] || 'نامشخص'}</td><td>${escapeHtml(m.reason || '')}<details><summary>شواهد مبنا</summary><pre dir="auto">${escapeHtml(JSON.stringify(m.evidence, null, 2))}</pre></details><button class="btn" data-action-case="${escapeHtml(c.case_key)}" data-action-criterion="${escapeHtml(m.id)}" onclick="prepareManagementAction(this)">انتخاب برای ثبت اقدام</button></td></tr>`).join('') || '<tr><td colspan="6">موردی با این فیلتر وجود ندارد.</td></tr>';
}

function prepareManagementAction(button) {
  document.getElementById('action-case').value = button.dataset.actionCase;
  document.getElementById('action-criterion').value = button.dataset.actionCriterion;
  document.getElementById('action-decision').focus();
}

function showMoreManagementRows() { managementLimit += 300; renderManagementRows(); }

async function saveManagementSeverities() {
  const values = Object.fromEntries([...document.querySelectorAll('[data-criterion-severity]')].map(el => [el.dataset.criterionSeverity, el.value]));
  const response = await api().save_management_severities(values);
  toast(response.message || response.error, response.ok ? 'success' : 'error');
}

async function retrieveSelectedHistory() {
  const key = document.getElementById('action-case').value.trim();
  if (!key) { toast('ابتدا یک مورد را از جدول انتخاب کنید.', 'error'); return; }
  const button = document.getElementById('management-history-button');
  button.disabled = true;
  document.getElementById('management-history-result').textContent = 'در حال بررسی تاریخچه واقعی CRM؛ فقط این مورد خوانده می‌شود…';
  try {
    const response = await api().retrieve_crm_case_history(key);
    document.getElementById('management-history-result').textContent = response.message || response.error;
  } catch (error) {
    document.getElementById('management-history-result').textContent = `دریافت تاریخچه ناموفق بود: ${error.message}`;
  } finally { button.disabled = false; }
}

async function saveStatusMapping() {
  try {
    const values = JSON.parse(document.getElementById('management-status-mapping').value || '{}');
    const response = await api().save_crm_status_mapping(values);
    toast(response.ok ? 'نگاشت ذخیره شد؛ تاریخچه مورد را دوباره دریافت کنید.' : response.error, response.ok ? 'success' : 'error');
  } catch (error) { toast(`ساختار نگاشت JSON معتبر نیست: ${error.message}`, 'error'); }
}

async function saveManagementThresholds() {
  const values = Object.fromEntries([...document.querySelectorAll('[data-management-threshold]')].map(el => [el.dataset.managementThreshold, el.value === '' ? null : Number(el.value)]));
  const response = await api().save_management_thresholds(values);
  toast(response.message || response.error, response.ok ? 'success' : 'error');
}

async function saveManagementAction() {
  const response = await api().record_management_action(document.getElementById('action-case').value.trim(), document.getElementById('action-criterion').value.trim(), document.getElementById('action-decision').value, document.getElementById('action-owner').value, document.getElementById('action-due').value);
  toast(response.ok ? 'اقدام در بانک محلی ثبت شد.' : response.error, response.ok ? 'success' : 'error');
  if (response.ok) await loadManagementEvaluation();
}

async function editCriterionThreshold(id) {
  const criterion = allCriteria().find(c => c.id === id);
  if (!criterion) return;
  const value = prompt(`حداقل امتیاز قابل‌قبول «${criterion.name_fa}» از صفر تا صد؛ خالی برای حذف حدنصاب:`, criterion.pass_threshold ?? '');
  if (value === null) return;
  const threshold = value.trim() === '' ? null : Number(value);
  if (threshold !== null && (!Number.isFinite(threshold) || threshold < 0 || threshold > 100)) { toast('عدد بین صفر تا صد وارد کنید.', 'error'); return; }
  const response = await api().set_criterion_threshold(id, threshold);
  toast(response.ok ? 'حدنصاب ذخیره شد؛ از ارزیابی بعدی اعمال می‌شود.' : response.error, response.ok ? 'success' : 'error');
  if (response.ok) await loadCriteria();
}
