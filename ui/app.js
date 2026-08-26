/* ------------------------------------------------------------------------
   حالت کلی برنامه در سمت رابط کاربری
------------------------------------------------------------------------ */
const state = {
  notesPath: null,
  tasksPath: null,
  datasetLoaded: false,
  dateBounds: null,
  analysisDone: false,
  analysisMode: 'comparison',
  casesStatusReasons: [],
  casesService: '',
  suspiciousReasons: [],
  suspiciousService: '',
  casesPage: 0,
  casesPageSize: 25,
  selectedCaseKeys: new Set(),
  caseSelectionPage: 0,
  caseSelectionPageSize: 50,
  caseSelectionTotal: 0,
  caseSelectionQuery: '',
  caseSelectionSearchTimer: null,
  charts: {},
  criteriaConfig: null,
  currentExpert: null,
};

function api() { return window.pywebview.api; }

/* ------------------------------------------------------------------------
   ناوبری
------------------------------------------------------------------------ */
document.querySelectorAll('.nav-item').forEach(el => {
  const analysisPages = new Set(['dashboard', 'general', 'comparison', 'ranking', 'cases', 'suspicious', 'data-quality', 'mgmt-report', 'export']);
  if (analysisPages.has(el.dataset.page)) el.classList.add('analysis-nav');
  el.addEventListener('click', () => showPage(el.dataset.page));
});

document.querySelectorAll('.module-card').forEach(el => {
  el.addEventListener('click', () => {
    activateModule(el.dataset.module);
  });
});

function activateModule(moduleName) {
  document.querySelectorAll('.module-card').forEach(card => {
    const active = card.dataset.module === moduleName;
    card.classList.toggle('active', active);
    card.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  document.querySelectorAll('.module-menu').forEach(menu => {
    menu.classList.toggle('active', menu.dataset.moduleMenu === moduleName);
  });
  if (moduleName === 'project-management') {
    toast('ماژول مدیریت پروژه‌ها در دست توسعه است.');
  }
}

function showPage(name) {
  const analysisPages = new Set(['dashboard', 'general', 'comparison', 'ranking', 'cases', 'suspicious', 'data-quality', 'mgmt-report', 'export']);
  if (analysisPages.has(name) && !state.analysisDone) {
    toast('ابتدا بازه را انتخاب و تحلیل را اجرا کنید.', 'error');
    return;
  }
  document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.page === name));
  document.querySelectorAll('.page').forEach(el => el.classList.toggle('active', el.id === 'page-' + name));
}

function applyNavigationLabels() {
  const labels = {
    upload: '📂 بارگذاری داده‌ها',
    periods: '🗓 بازه‌ها و اجرای تحلیل',
    dashboard: '📊 داشبورد',
    general: '🔎 تحلیل کلی',
    comparison: '🔁 مقایسه دوره‌ها',
    ranking: '🏆 عملکرد کارشناسان',
    cases: '🗂 جزئیات موارد / Taskها',
    suspicious: '⚠️ موارد نیازمند بررسی',
    'data-quality': '🩺 سلامت داده',
    'mgmt-report': '📋 داشبورد مدیریتی',
    export: '⬇️ خروجی و گزارش‌ها',
    'expert-groups': '👥 گروه‌ها و تیم‌ها',
    criteria: '⚖️ معیارها و نحوه محاسبه',
    'ai-settings': '🤖 تنظیمات AI',
  };
  document.querySelectorAll('.nav-item').forEach(el => {
    if (el.dataset.page === 'mgmt-report') {
      el.hidden = true;
      return;
    }
    const label = labels[el.dataset.page];
    if (label) {
      const badge = el.querySelector('.nav-badge');
      el.textContent = label + ' ';
      if (badge) el.appendChild(badge);
    }
  });
}

function toast(message, type) {
  const c = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = 'toast' + (type ? ' ' + type : '');
  el.textContent = message;
  c.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

function fmt(v, digits) {
  if (v === null || v === undefined) return '—';
  if (typeof v !== 'number') return v;
  return v.toFixed(digits === undefined ? 1 : digits);
}

function deltaBadge(change) {
  if (change === null || change === undefined) return '<span class="badge muted">—</span>';
  if (change > 3) return `<span class="badge good">+${fmt(change)}</span>`;
  if (change < -3) return `<span class="badge bad">${fmt(change)}</span>`;
  return `<span class="badge warn">${fmt(change)}</span>`;
}

function scoreBadgeClass(score) {
  if (score === null || score === undefined) return 'muted';
  if (score >= 75) return 'good';
  if (score >= 50) return 'warn';
  return 'bad';
}

/* ------------------------------------------------------------------------
   تبدیل تاریخ میلادی↔شمسی با استفاده از تقویم فارسی داخلیِ Intl
   (توسط موتور Chromium/WebView2 به‌صورت بومی و دقیق پشتیبانی می‌شود؛
   نسبت به فرمول‌های دستی قبلی، در مرز نوروز و سال‌های کبیسه خطا ندارد)
------------------------------------------------------------------------ */
const _jalaliFormatter = new Intl.DateTimeFormat('en-US-u-ca-persian', { year: 'numeric', month: 'numeric', day: 'numeric', timeZone: 'UTC' });

function _jalaliPartsOf(utcDate) {
  const parts = _jalaliFormatter.formatToParts(utcDate);
  const o = {};
  parts.forEach(p => { if (p.type !== 'literal' && p.type !== 'era') o[p.type] = parseInt(p.value, 10); });
  return [o.year, o.month, o.day];
}

function gregorianToJalali(gy, gm, gd) {
  return _jalaliPartsOf(new Date(Date.UTC(gy, gm - 1, gd)));
}

// جستجوی دودویی روی روزهای تقویم میلادی تا روزی که معادل شمسی آن دقیقاً jy/jm/jd باشد
function jalaliToGregorian(jy, jm, jd) {
  const target = jy * 10000 + jm * 100 + jd;
  let loT = Date.UTC(jy + 620, 0, 1);
  let hiT = Date.UTC(jy + 623, 11, 31);
  while (loT < hiT) {
    const midDay = loT + Math.floor(((hiT - loT) / 86400000) / 2) * 86400000;
    const [py, pm, pd] = _jalaliPartsOf(new Date(midDay));
    const val = py * 10000 + pm * 100 + pd;
    if (val < target) loT = midDay + 86400000; else hiT = midDay;
  }
  const d = new Date(loT);
  return [d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate()];
}

function toShamsiStr(isoStr) {
  if (!isoStr) return '—';
  const d = new Date(isoStr);
  const [jy, jm, jd] = gregorianToJalali(d.getFullYear(), d.getMonth() + 1, d.getDate());
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${jy}/${String(jm).padStart(2, '0')}/${String(jd).padStart(2, '0')} ${hh}:${mm}`;
}
function toGregStr(isoStr) {
  if (!isoStr) return '—';
  const d = new Date(isoStr);
  return d.toLocaleString('en-GB', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}
function dateDual(isoStr) {
  return `${toShamsiStr(isoStr)} <span style="color:var(--muted);font-size:11px">(${toGregStr(isoStr)})</span>`;
}

/* ------------------------------------------------------------------------
   انتخاب موارد پیش از تحلیل
------------------------------------------------------------------------ */
function updateCaseSelectionSummary() {
  const el = document.getElementById('case-selection-count');
  if (!el) return;
  el.textContent = `${state.selectedCaseKeys.size.toLocaleString('fa-IR')} مورد از ${state.caseSelectionTotal.toLocaleString('fa-IR')} مورد انتخاب شده`;
}

function renderCaseSelectionRows(rows) {
  const body = document.getElementById('case-selection-body');
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="7" class="case-selection-empty">موردی با این جست‌وجو پیدا نشد.</td></tr>';
  } else {
    body.innerHTML = rows.map(row => {
      const encodedKey = encodeURIComponent(String(row.case_key));
      const title = row.case_title || 'بدون عنوان';
      return `<tr>
        <td class="case-selection-check"><input type="checkbox" ${state.selectedCaseKeys.has(String(row.case_key)) ? 'checked' : ''}
          data-case-key="${encodedKey}" onchange="toggleCaseSelection(this.dataset.caseKey)"></td>
        <td><strong>${escapeHtml(row.case_number || row.case_key)}</strong><small>${escapeHtml(title)}</small></td>
        <td>${escapeHtml(row.service || '—')}</td>
        <td>${escapeHtml(row.owner || '—')}</td>
        <td>${escapeHtml(row.status_reason || row.status || '—')}</td>
        <td>${row.notes ?? 0}</td>
        <td>${row.tasks ?? 0}</td>
      </tr>`;
    }).join('');
  }
  const pageCheck = document.getElementById('case-selection-page-check');
  if (pageCheck) {
    pageCheck.checked = rows.length > 0 && rows.every(row => state.selectedCaseKeys.has(String(row.case_key)));
    pageCheck.indeterminate = rows.some(row => state.selectedCaseKeys.has(String(row.case_key))) && !pageCheck.checked;
  }
}

async function loadCaseSelection(page = 0) {
  const body = document.getElementById('case-selection-body');
  if (!body || !state.datasetLoaded) return;
  body.innerHTML = '<tr><td colspan="7" class="case-selection-empty">در حال دریافت فهرست موارد...</td></tr>';
  try {
    const res = await api().get_dataset_cases(state.caseSelectionQuery, page, state.caseSelectionPageSize);
    if (!res.ok) throw new Error(res.error || 'دریافت فهرست موارد ناموفق بود');
    state.caseSelectionPage = res.page || page;
    state.caseSelectionTotal = res.total || 0;
    renderCaseSelectionRows(res.rows || []);
    const pageCount = Math.max(1, Math.ceil(state.caseSelectionTotal / state.caseSelectionPageSize));
    const pageLabel = document.getElementById('case-selection-page');
    if (pageLabel) pageLabel.textContent = `صفحه ${(state.caseSelectionPage + 1).toLocaleString('fa-IR')} از ${pageCount.toLocaleString('fa-IR')}`;
    updateCaseSelectionSummary();
  } catch (e) {
    body.innerHTML = `<tr><td colspan="7" class="case-selection-empty error-text">${escapeHtml(String(e))}</td></tr>`;
  }
}

async function initializeCaseSelection() {
  try {
    const res = await api().get_dataset_case_keys();
    if (!res.ok) throw new Error(res.error || 'دریافت موارد ناموفق بود');
    state.selectedCaseKeys = new Set((res.keys || []).map(String));
    state.caseSelectionQuery = '';
    state.caseSelectionPage = 0;
    state.caseSelectionTotal = res.keys ? res.keys.length : 0;
    const search = document.getElementById('case-selection-search');
    if (search) search.value = '';
    await loadCaseSelection(0);
  } catch (e) {
    toast('فهرست موارد بارگذاری نشد: ' + e, 'error');
  }
}

function toggleCaseSelection(encodedKey) {
  const key = decodeURIComponent(encodedKey);
  if (state.selectedCaseKeys.has(key)) state.selectedCaseKeys.delete(key);
  else state.selectedCaseKeys.add(key);
  updateCaseSelectionSummary();
}

function toggleCaseSelectionPage(checked) {
  document.querySelectorAll('#case-selection-body input[data-case-key]').forEach(input => {
    const key = decodeURIComponent(input.dataset.caseKey);
    input.checked = checked;
    if (checked) state.selectedCaseKeys.add(key);
    else state.selectedCaseKeys.delete(key);
  });
  updateCaseSelectionSummary();
}

async function selectAllCaseSelection() {
  const res = await api().get_dataset_case_keys();
  if (res.ok) {
    state.selectedCaseKeys = new Set((res.keys || []).map(String));
    renderCaseSelectionRows([]);
    await loadCaseSelection(state.caseSelectionPage);
  }
  updateCaseSelectionSummary();
}

function clearAllCaseSelection() {
  state.selectedCaseKeys.clear();
  renderCaseSelectionRows([]);
  loadCaseSelection(state.caseSelectionPage);
  updateCaseSelectionSummary();
}

function debouncedCaseSelectionSearch() {
  clearTimeout(state.caseSelectionSearchTimer);
  state.caseSelectionSearchTimer = setTimeout(() => {
    state.caseSelectionQuery = document.getElementById('case-selection-search')?.value || '';
    loadCaseSelection(0);
  }, 250);
}

function caseSelectionPrev() {
  if (state.caseSelectionPage > 0) loadCaseSelection(state.caseSelectionPage - 1);
}

function caseSelectionNext() {
  const pages = Math.ceil(state.caseSelectionTotal / state.caseSelectionPageSize);
  if (state.caseSelectionPage + 1 < pages) loadCaseSelection(state.caseSelectionPage + 1);
}

function daysInJalaliMonth(jy, jm) {
  if (jm <= 6) return 31;
  if (jm <= 11) return 30;
  // اسفند: ۲۹ یا ۳۰ — با یافتن آخرین روزی که هنوز در همان ماه/سال شمسی است
  for (const day of [30, 29]) {
    const [gy, gm, gd] = jalaliToGregorian(jy, 12, day);
    const [jy2, jm2, jd2] = gregorianToJalali(gy, gm, gd);
    if (jy2 === jy && jm2 === 12 && jd2 === day) return day;
  }
  return 29;
}

const JALALI_MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'];

function buildJalaliPicker(containerId, initialISO) {
  const container = document.getElementById(containerId);
  const now = initialISO ? new Date(initialISO) : new Date();
  const [jy, jm, jd] = gregorianToJalali(now.getFullYear(), now.getMonth() + 1, now.getDate());

  const yearOptions = [];
  for (let y = jy - 3; y <= jy + 1; y++) yearOptions.push(y);

  container.innerHTML = `
    <div style="display:flex;gap:5px">
      <select class="jp-year" style="flex:1.3">${yearOptions.map(y => `<option value="${y}" ${y === jy ? 'selected' : ''}>${y}</option>`).join('')}</select>
      <select class="jp-month" style="flex:1.6">${JALALI_MONTHS.map((m, i) => `<option value="${i + 1}" ${i + 1 === jm ? 'selected' : ''}>${m}</option>`).join('')}</select>
      <select class="jp-day" style="flex:1"></select>
    </div>`;

  const daySelect = container.querySelector('.jp-day');
  function refreshDays() {
    const y = parseInt(container.querySelector('.jp-year').value);
    const m = parseInt(container.querySelector('.jp-month').value);
    const maxDay = daysInJalaliMonth(y, m);
    const currentVal = parseInt(daySelect.value) || jd;
    daySelect.innerHTML = Array.from({ length: maxDay }, (_, i) => i + 1)
      .map(d => `<option value="${d}" ${d === Math.min(currentVal, maxDay) ? 'selected' : ''}>${d}</option>`).join('');
  }
  refreshDays();
  container.querySelector('.jp-year').addEventListener('change', refreshDays);
  container.querySelector('.jp-month').addEventListener('change', refreshDays);
}

function getJalaliPickerISO(containerId) {
  const c = document.getElementById(containerId);
  const jy = parseInt(c.querySelector('.jp-year').value);
  const jm = parseInt(c.querySelector('.jp-month').value);
  const jd = parseInt(c.querySelector('.jp-day').value);
  const [gy, gm, gd] = jalaliToGregorian(jy, jm, jd);
  const pad = n => String(n).padStart(2, '0');
  // فقط تاریخ (بدون ساعت) ارسال می‌شود؛ سرور خودش ابتدا/انتهای روز را در نظر می‌گیرد
  return `${gy}-${pad(gm)}-${pad(gd)}`;
}

/* ------------------------------------------------------------------------
   Upload
------------------------------------------------------------------------ */
async function pickFile(kind) {
  if (!(window.pywebview && window.pywebview.api && typeof window.pywebview.api.pick_file === 'function')) {
    document.getElementById('boot-error').style.display = 'flex';
    return;
  }
  try {
    const path = await api().pick_file();
    if (!path) return;
    if (kind === 'notes') {
      state.notesPath = path;
      document.getElementById('notes-file-name').textContent = path;
    } else {
      state.tasksPath = path;
      document.getElementById('tasks-file-name').textContent = path;
    }
    document.getElementById('btn-upload').disabled = !(state.notesPath && state.tasksPath);
  } catch (e) {
    toast('پنجره انتخاب فایل باز نشد: ' + e, 'error');
  }
}

async function doUpload() {
  const resultBox = document.getElementById('upload-result');
  resultBox.innerHTML = '<div class="warn-box">در حال پردازش...</div>';
  let res;
  try {
    res = await api().upload(state.notesPath, state.tasksPath);
  } catch (e) {
    resultBox.innerHTML = `<div class="err-box">خطای غیرمنتظره: ${e}</div>`;
    return;
  }
  if (!res.ok) {
    resultBox.innerHTML = `<div class="err-box">${res.error}</div>`;
    return;
  }
  state.datasetLoaded = true;
  state.dateBounds = res.date_bounds;
  document.getElementById('dataset-status').textContent =
    `${res.total_cases.toLocaleString('fa-IR')} مورد | داده بارگذاری شد`;

  const s = (label, sm) => `
    <div class="card">
      <h3>${label}</h3>
      <table>
        <tr><td>نام فایل</td><td>${sm.file_name}</td></tr>
        <tr><td>تعداد رکورد</td><td>${sm.total_rows}</td></tr>
        <tr><td>مورد یکتا</td><td>${sm.unique_cases}</td></tr>
        <tr><td>رکورد ناقص</td><td>${sm.incomplete_rows}</td></tr>
        <tr><td>ستون‌های شناسایی‌شده</td><td>${sm.usable_columns} از ${sm.total_columns}</td></tr>
        <tr><td>وضعیت اعتبارسنجی</td><td>${sm.missing_required_labels.length ? '<span class="badge bad">ناقص</span>' : '<span class="badge good">موفق</span>'}</td></tr>
      </table>
      ${sm.warnings.map(w => `<div class="warn-box" style="margin-top:10px">${w}</div>`).join('')}
    </div>`;

  resultBox.innerHTML = `
    <div class="ok-box">فایل‌ها با موفقیت پردازش شدند: ${res.total_cases} مورد، ${res.unmatched_tasks} Task بدون اتصال قطعی به مورد.</div>
    <div class="grid cols-2">${s('فایل Notes', res.notes_summary)}${s('فایل Tasks', res.tasks_summary)}</div>`;

  // پیش‌فرض بازه‌ها بر اساس داده واقعی
  if (res.date_bounds.min && res.date_bounds.max) {
    const min = new Date(res.date_bounds.min), max = new Date(res.date_bounds.max);
    const mid = new Date((min.getTime() + max.getTime()) / 2);
    buildJalaliPicker('p1-start-picker', min.toISOString());
    buildJalaliPicker('p1-end-picker', mid.toISOString());
    buildJalaliPicker('p2-start-picker', mid.toISOString());
    buildJalaliPicker('p2-end-picker', max.toISOString());
    document.getElementById('date-bounds-hint').textContent =
      `بازه داده موجود: ${toShamsiStr(res.date_bounds.min)} تا ${toShamsiStr(res.date_bounds.max)} (پیش‌فرض به دو نیمه مساوی تقسیم شد؛ قابل تغییر است)`;
  }
  loadCriteria();
  loadAiSettings();
  loadExpertChecklist();
  await initializeCaseSelection();
  toast('فایل‌ها بارگذاری شدند', 'success');
}

async function autoLoadDefaultFiles() {
  const box = document.getElementById('auto-input-info');
  if (!box) return;
  try {
    const info = await api().get_auto_input_info();
    box.innerHTML = `پوشه ورودی: <code>${escapeHtml(info.directory)}</code><br>
      Notes: <code>notes.xlsx</code> — Tasks: <code>tasks.xlsx</code>`;
    if (!info.notes_exists || !info.tasks_exists) {
      box.innerHTML += '<br><span class="muted">هر دو فایل هنوز در پوشه قرار نگرفته‌اند.</span>';
      return;
    }
    state.notesPath = info.notes_file;
    state.tasksPath = info.tasks_file;
    document.getElementById('notes-file-name').textContent = info.notes_file;
    document.getElementById('tasks-file-name').textContent = info.tasks_file;
    document.getElementById('btn-upload').disabled = false;
    await doUpload();
  } catch (e) {
    box.innerHTML = `<span class="error-text">بررسی پوشه ورودی ناموفق بود: ${escapeHtml(String(e))}</span>`;
  }
}

async function clearDataset() {
  await api().clear_dataset();
  state.datasetLoaded = false;
  state.analysisDone = false;
  state.selectedCaseKeys.clear();
  state.caseSelectionTotal = 0;
  const selectionBody = document.getElementById('case-selection-body');
  if (selectionBody) selectionBody.innerHTML = '<tr><td colspan="7" class="case-selection-empty">پس از بارگذاری داده‌ها، فهرست موارد اینجا نمایش داده می‌شود.</td></tr>';
  updateCaseSelectionSummary();
  state.notesPath = null; state.tasksPath = null;
  document.getElementById('notes-file-name').textContent = 'فایلی انتخاب نشده';
  document.getElementById('tasks-file-name').textContent = 'فایلی انتخاب نشده';
  document.getElementById('btn-upload').disabled = true;
  document.getElementById('upload-result').innerHTML = '';
  document.getElementById('dataset-status').textContent = 'فایلی بارگذاری نشده است.';
  toast('داده پاک شد');
}

/* ------------------------------------------------------------------------
   Periods & Run
------------------------------------------------------------------------ */
async function runAnalysis(forceAi = false) {
  if (!state.datasetLoaded) { toast('ابتدا فایل‌ها را بارگذاری کنید', 'error'); return; }
  if (!state.selectedCaseKeys.size) {
    toast('حداقل یک مورد را برای تحلیل انتخاب کنید', 'error');
    return;
  }
  const mode = document.getElementById('analysis-mode').value;
  const p1s = mode === 'comparison' ? getJalaliPickerISO('p1-start-picker') : '';
  const p1e = mode === 'comparison' ? getJalaliPickerISO('p1-end-picker') : '';
  const p2s = mode === 'comparison' ? getJalaliPickerISO('p2-start-picker') : '';
  const p2e = mode === 'comparison' ? getJalaliPickerISO('p2-end-picker') : '';
  const expertGroup = document.getElementById('run-expert-group').value || null;

  state.analysisMode = mode;
  state.analysisDone = false;
  document.getElementById('btn-run').disabled = true;
  document.getElementById('btn-cancel-analysis').style.display = 'inline-flex';
  document.getElementById('progress-area').style.display = 'block';
  document.getElementById('run-result').innerHTML = '';

  const res = await api().start_analysis(
    p1s, p1e, p2s, p2e, expertGroup, mode, forceAi,
    Array.from(state.selectedCaseKeys)
  );
  if (!res.ok) {
    toast(res.error, 'error');
    document.getElementById('btn-run').disabled = false;
    document.getElementById('btn-cancel-analysis').style.display = 'none';
    return;
  }
  pollStatus();
}

async function cancelAnalysis() {
  const res = await api().cancel_analysis();
  if (!res.ok) {
    toast(res.message || 'تحلیلی در حال اجرا نیست.', 'error');
    return;
  }
  document.getElementById('btn-cancel-analysis').style.display = 'none';
  document.getElementById('btn-run').disabled = false;
  document.getElementById('run-result').innerHTML = '<div class="warn-box">تحلیل لغو شد و نتیجه ناقص نمایش داده نمی‌شود.</div>';
}

function toggleAnalysisMode() {
  const general = document.getElementById('analysis-mode').value === 'general';
  ['p1-start-picker', 'p1-end-picker', 'p2-start-picker', 'p2-end-picker'].forEach(id => {
    const el = document.getElementById(id);
    if (el && el.closest('.card')) el.closest('.card').style.display = general ? 'none' : '';
  });
}

async function pollStatus() {
  const status = await api().get_status();
  const total = status.total || 1;
  const pct = status.total ? Math.round((status.current / status.total) * 100) : 0;
  document.getElementById('progress-label').textContent = `${status.stage || ''} ${status.total ? `(${status.current}/${status.total})` : ''}`;
  document.getElementById('progress-fill').style.width = pct + '%';

  if (status.error) {
    document.getElementById('run-result').innerHTML = `<div class="err-box">${status.error}</div>`;
    document.getElementById('btn-run').disabled = false;
    document.getElementById('btn-cancel-analysis').style.display = 'none';
    return;
  }
  if (status.cancelled) {
    document.getElementById('run-result').innerHTML = '<div class="warn-box">تحلیل توسط کاربر لغو شد.</div>';
    document.getElementById('btn-run').disabled = false;
    document.getElementById('btn-cancel-analysis').style.display = 'none';
    return;
  }
  if (status.running) {
    setTimeout(pollStatus, 400);
    return;
  }
  if (status.done) {
    state.analysisDone = true;
    document.getElementById('run-result').innerHTML = `<div class="ok-box">تحلیل با موفقیت انجام شد.</div>`;
    document.getElementById('btn-run').disabled = false;
    document.getElementById('btn-cancel-analysis').style.display = 'none';
    refreshAllReports();
  }
}

function openChangelog() {
  const overlay = document.getElementById('changelog-overlay');
  if (!overlay) return;
  overlay.style.display = 'flex';
  const body = document.getElementById('changelog-body');
  body.innerHTML = '<div class="empty-state">در حال دریافت تاریخچه تغییرات...</div>';
  api().get_changelog().then(items => {
    if (!items || !items.length) {
      body.innerHTML = '<div class="empty-state">تاریخچه تغییرات در دسترس نیست.</div>';
      return;
    }
    const sorted = items.slice().sort((a, b) => compareVersions(b.version, a.version));
    body.innerHTML = sorted.map((item, index) => `
      <article class="changelog-entry">
        <div class="changelog-entry-head">
          <h3>نگارش ${escapeHtml(item.version || '—')}${index === 0 ? ' — آخرین نگارش' : ''}</h3>
          <span class="badge muted">${escapeHtml(formatChangelogDate(item.date))}</span>
        </div>
        <ul>${(item.changes || []).map(change => `<li>${escapeHtml(change)}</li>`).join('')}</ul>
      </article>
    `).join('');
  }).catch(() => {
    body.innerHTML = '<div class="err-box">امکان دریافت تاریخچه تغییرات وجود ندارد.</div>';
  });
}

function compareVersions(a, b) {
  const left = String(a || '0').split('.').map(Number);
  const right = String(b || '0').split('.').map(Number);
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    const diff = (left[i] || 0) - (right[i] || 0);
    if (diff) return diff;
  }
  return 0;
}

function formatChangelogDate(value) {
  if (!value) return '—';
  const iso = /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value;
  return toShamsiStr(iso).split(' ')[0];
}

function closeChangelog() {
  const overlay = document.getElementById('changelog-overlay');
  if (overlay) overlay.style.display = 'none';
}

async function refreshAllReports() {
  await Promise.all([
    loadDashboard(), loadGeneral(), loadComparison(), loadRanking(), loadSuspicious(),
    loadDataQuality(), loadMgmtReport(), loadCasesTable(0),
  ]);
}

/* ------------------------------------------------------------------------
   Criteria
------------------------------------------------------------------------ */
async function loadCriteria() {
  let cfg;
  try {
    cfg = await api().get_criteria();
  } catch (e) {
    toast('بارگذاری معیارها ناموفق بود: ' + e, 'error');
    return;
  }
  state.criteriaConfig = cfg;
  document.getElementById('ratio-objective').value = cfg.objective_ai_ratio.objective;
  document.getElementById('ratio-ai').value = cfg.objective_ai_ratio.ai;
  renderCriteria();
  renderEvaluationProfiles();
}

function allCriteria() {
  return (state.criteriaConfig?.categories || []).flatMap(cat => cat.criteria || []);
}

function renderEvaluationProfiles() {
  const box = document.getElementById('evaluation-profiles-list');
  if (!box) return;
  const criteria = allCriteria();
  box.innerHTML = (state.criteriaConfig.evaluation_profiles || []).map(profile => `
    <div class="card" style="margin-top:10px;padding:12px">
      <h4 style="margin:0 0 8px">${escapeHtml(profile.name_fa)}</h4>
      <input type="hidden" data-profile-id="${escapeHtml(profile.id)}">
      <div class="field">
        <label class="field-label">مقادیر دقیق Service (با کاما جدا کنید)</label>
        <input type="text" id="profile-services-${profile.id}" value="${escapeHtml((profile.service_values || []).join(', '))}">
      </div>
      <div class="field">
        <label class="field-label">کلمات تشخیصی در عنوان/شرح (با کاما جدا کنید)</label>
        <input type="text" id="profile-keywords-${profile.id}" value="${escapeHtml((profile.keywords || []).join(', '))}">
      </div>
      <div class="field">
        <label class="field-label">معیارهای فعال این پروفایل</label>
        <div class="chip-list">${criteria.map(c => `
          <label class="crit-chip ${profile.criteria_ids.includes(c.id) ? '' : 'crit-chip-inactive'}">
            <input type="checkbox" id="profile-${profile.id}-${c.id}" ${profile.criteria_ids.includes(c.id) ? 'checked' : ''}>
            ${escapeHtml(c.name_fa)}
          </label>`).join('')}</div>
      </div>
      <button class="btn primary" onclick="saveEvaluationProfile('${escapeHtml(profile.id)}')">ذخیره پروفایل</button>
    </div>
  `).join('');
}

async function saveEvaluationProfile(profileId) {
  const profile = (state.criteriaConfig.evaluation_profiles || []).find(p => p.id === profileId);
  if (!profile) return;
  const services = document.getElementById(`profile-services-${profileId}`).value.split(',');
  const keywords = document.getElementById(`profile-keywords-${profileId}`).value.split(',');
  const criteriaIds = allCriteria().filter(c => document.getElementById(`profile-${profileId}-${c.id}`)?.checked).map(c => c.id);
  const res = await api().update_evaluation_profile(profileId, services, keywords, criteriaIds);
  if (res.ok) { toast('پروفایل ارزیابی ذخیره شد', 'success'); loadCriteria(); }
  else toast(res.error || 'ذخیره پروفایل ناموفق بود', 'error');
}

function renderCriteria() {
  const cfg = state.criteriaConfig;
  if (!cfg) return;
  const box = document.getElementById('criteria-list');
  box.innerHTML = '';

  cfg.categories.forEach(cat => {
    const active = cat.criteria.filter(c => c.active);
    const inactive = cat.criteria.filter(c => !c.active);

    const catDiv = document.createElement('div');
    catDiv.className = 'card criteria-cat';

    const activeChips = active.map(c => `
      <span class="crit-chip ${c.evaluation_type === 'AI' ? 'ai-type' : ''}" title="${escapeHtml(c.description_fa)}">
        ${c.name_fa} (<span class="crit-weight" onclick="editCriterionWeight('${c.id}')">${fmtWeight(c.weight)}</span> امتیاز)
        <button class="crit-guide-btn" title="راهنمای کامل معیار" onclick="showCriterionGuide('${c.id}')">?</button>
        <button class="crit-x" title="حذف از معیارهای فعال" onclick="onCriterionChange('${c.id}', false)">×</button>
      </span>`).join('');

    const inactiveChips = inactive.map(c => `
      <span class="crit-chip-inactive" title="${escapeHtml(c.description_fa)}" onclick="onCriterionChange('${c.id}', true)">
        + ${c.name_fa} <button class="crit-guide-btn" title="راهنمای کامل معیار" onclick="event.stopPropagation(); showCriterionGuide('${c.id}')">?</button>
      </span>`).join('');

    catDiv.innerHTML = `
      <div class="crit-cat-header">
        <h3 style="margin:0">${cat.name_fa}</h3>
        <span class="cat-hint">${active.length} معیار فعال از ${cat.criteria.length}</span>
      </div>
      <div class="crit-chip-wrap">${activeChips || '<span style="color:var(--muted);font-size:12px">هیچ معیار فعالی در این دسته نیست.</span>'}</div>
      ${inactive.length ? `<div class="crit-inactive-wrap">${inactiveChips}</div>` : ''}
    `;
    box.appendChild(catDiv);
  });
}

function showCriterionGuide(id) {
  const cfg = state.criteriaConfig;
  let criterion = null;
  let category = null;
  (cfg?.categories || []).forEach(cat => (cat.criteria || []).forEach(c => {
    if (c.id === id) { criterion = c; category = cat; }
  }));
  if (!criterion) return;
  const body = document.getElementById('criterion-guide-body');
  const section = (title, value) => value
    ? `<section class="guide-section"><h3>${title}</h3><p>${escapeHtml(value)}</p></section>`
    : '';
  body.innerHTML = `
    <div class="guide-kicker">${escapeHtml(category?.name_fa || '')} · ${criterion.evaluation_type === 'AI' ? 'AI' : 'Rule-Based'} · وزن ${fmtWeight(criterion.weight)}</div>
    <h2>${escapeHtml(criterion.name_fa)}</h2>
    <p class="guide-description">${escapeHtml(criterion.description_fa || '')}</p>
    ${section('هدف معیار', criterion.goal_fa)}
    ${section('روش دقیق محاسبه', criterion.calculation_fa)}
    ${section('تفسیر امتیاز', criterion.interpretation_fa)}
    ${section('مثال', criterion.example_fa)}
    ${section('محدودیت و موارد N/A', criterion.limitations_fa)}
  `;
  document.getElementById('criterion-guide-overlay').style.display = 'flex';
}

function closeCriterionGuide() {
  const overlay = document.getElementById('criterion-guide-overlay');
  if (overlay) overlay.style.display = 'none';
}

function fmtWeight(w) {
  return (Math.round(w * 10) / 10).toString();
}

async function editCriterionWeight(id) {
  const cfg = state.criteriaConfig;
  let crit = null;
  cfg.categories.forEach(cat => cat.criteria.forEach(c => { if (c.id === id) crit = c; }));
  if (!crit) return;
  const newVal = prompt(`امتیاز جدید برای «${crit.name_fa}»:`, fmtWeight(crit.weight));
  if (newVal === null) return;
  const num = parseFloat(newVal);
  if (isNaN(num) || num < 0) { toast('عدد وارد شده معتبر نیست', 'error'); return; }
  crit.weight = num;
  await api().update_criterion(id, num, true);
  renderCriteria();
}

async function onCriterionChange(id, active) {
  const cfg = state.criteriaConfig;
  let crit = null;
  cfg.categories.forEach(cat => cat.criteria.forEach(c => { if (c.id === id) crit = c; }));
  if (!crit) return;
  crit.active = active;
  await api().update_criterion(id, crit.weight, active);
  renderCriteria();
}

async function saveRatio() {
  const o = parseFloat(document.getElementById('ratio-objective').value);
  const a = parseFloat(document.getElementById('ratio-ai').value);
  const res = await api().update_ratio(o, a);
  if (res.ok) toast('نسبت ذخیره شد', 'success'); else toast(res.error, 'error');
}

async function resetCriteria() {
  await api().reset_criteria();
  loadCriteria();
  toast('به تنظیمات پیش‌فرض بازگشت');
}

/* ------------------------------------------------------------------------
   AI Settings
------------------------------------------------------------------------ */
async function loadAiSettings() {
  let s;
  try {
    s = await api().get_ai_settings();
  } catch (e) {
    toast('بارگذاری تنظیمات AI ناموفق بود: ' + e, 'error');
    return;
  }
  document.getElementById('ai-enabled').value = String(s.enabled);
  document.getElementById('ai-provider').value = s.provider;
  document.getElementById('ai-model').value = s.model;
  document.getElementById('ai-base-url').value = s.base_url;
  document.getElementById('ai-temperature').value = s.temperature;
  document.getElementById('ai-max-tokens').value = s.max_tokens;
  document.getElementById('ai-batch-size').value = s.batch_size;
  document.getElementById('ai-key-masked').textContent = s.has_key ? `(کلید ذخیره‌شده: ${s.api_key_masked})` : '(کلیدی ذخیره نشده)';
  loadAiPresets();
}

async function loadAiPresets() {
  const select = document.getElementById('ai-preset');
  if (!select) return;
  const presets = await api().get_ai_presets();
  select.innerHTML = '<option value="">انتخاب کنید...</option>' +
    presets.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`).join('');
  select._aiPresets = presets;
}

function applyAiPreset() {
  const select = document.getElementById('ai-preset');
  const preset = (select._aiPresets || []).find(p => p.id === select.value);
  if (!preset) return;
  document.getElementById('ai-enabled').value = 'true';
  document.getElementById('ai-provider').value = preset.provider;
  document.getElementById('ai-model').value = preset.model;
  document.getElementById('ai-base-url').value = preset.base_url;
  document.getElementById('ai-preset-note').textContent = preset.note || '';
  toast('Preset مدل اعمال شد؛ API Key را وارد و تنظیمات را ذخیره کنید.', 'success');
}

async function saveAiSettings() {
  const payload = {
    enabled: document.getElementById('ai-enabled').value === 'true',
    provider: document.getElementById('ai-provider').value,
    model: document.getElementById('ai-model').value,
    base_url: document.getElementById('ai-base-url').value,
    temperature: parseFloat(document.getElementById('ai-temperature').value),
    max_tokens: parseInt(document.getElementById('ai-max-tokens').value),
    batch_size: parseInt(document.getElementById('ai-batch-size').value),
  };
  const key = document.getElementById('ai-api-key').value;
  if (key) payload.api_key = key;
  const res = await api().save_ai_settings(payload);
  if (res.ok) { toast('تنظیمات AI ذخیره شد', 'success'); document.getElementById('ai-api-key').value = ''; loadAiSettings(); }
}

async function testAi() {
  const box = document.getElementById('ai-test-result');
  box.innerHTML = '<div class="warn-box">در حال تست...</div>';
  const res = await api().test_ai_connection();
  box.innerHTML = res.ok ? `<div class="ok-box">${res.message}</div>` : `<div class="err-box">${res.message}</div>`;
}

async function deleteAiKey() {
  await api().delete_ai_key();
  loadAiSettings();
  toast('کلید حذف شد');
}

/* ------------------------------------------------------------------------
   Dashboard
------------------------------------------------------------------------ */
async function loadDashboard() {
  const d = await api().get_dashboard();
  if (!d.ok) return;
  document.getElementById('dashboard-empty').style.display = 'none';
  document.getElementById('dashboard-content').style.display = 'block';

  const kpi = (label, value, extra) => `
    <div class="card kpi"><div class="label">${label}</div><div class="value ${typeof value === 'string' && value.length > 6 ? 'small' : ''}">${value}</div>${extra || ''}</div>`;

  document.getElementById('dashboard-kpis').innerHTML = [
    kpi(d.unit === 'task' ? 'تعداد Task' : 'تعداد مورد', d.total_cases),
    kpi('تعداد کارشناسان', d.total_experts),
    kpi('تعداد Note', d.total_notes),
    kpi('تعداد Task', d.total_tasks),
    kpi('شاخص سلامت داده', fmt(d.data_quality) + '%'),
    kpi('امتیاز دوره اول', fmt(d.period1_score)),
    kpi('امتیاز دوره دوم', fmt(d.period2_score)),
    kpi('تغییر', (d.improvement_pct === null ? '—' : fmt(d.improvement_pct) + '%'),
      `<div class="delta ${d.improvement_pct > 0 ? 'up' : (d.improvement_pct < 0 ? 'down' : 'flat')}">${d.improvement_pct > 0 ? '▲' : (d.improvement_pct < 0 ? '▼' : '—')}</div>`),
  ].join('');

  if (d.mode === 'general') {
    drawChart('chart-categories', 'bar', {
      labels: d.category_chart.map(c => c.name),
      datasets: [{ label: 'تحلیل کلی', data: d.category_chart.map(c => c.value), backgroundColor: '#1f4e78' }],
    });
    drawChart('chart-overall', 'line', {
      labels: ['تحلیل کلی'],
      datasets: [{ label: 'امتیاز کلی', data: [d.general_score], borderColor: '#2f80ed', backgroundColor: '#eaf1f8', fill: true }],
    });
    return;
  }
  drawChart('chart-categories', 'bar', {
    labels: d.category_chart.map(c => c.name),
    datasets: [
      { label: 'دوره اول', data: d.category_chart.map(c => c.period1), backgroundColor: '#8fb3d9' },
      { label: 'دوره دوم', data: d.category_chart.map(c => c.period2), backgroundColor: '#1f4e78' },
    ],
  });

  drawChart('chart-overall', 'line', {
    labels: ['دوره اول', 'دوره دوم'],
    datasets: [{ label: 'امتیاز کلی', data: [d.period1_score, d.period2_score], borderColor: '#2f80ed', backgroundColor: '#eaf1f8', fill: true, tension: 0.3 }],
  });
}

async function loadGeneral() {
  const d = await api().get_dashboard();
  if (!d.ok || d.mode !== 'general') return;
  document.getElementById('general-empty').style.display = 'none';
  document.getElementById('general-content').style.display = 'block';
  document.getElementById('general-score').textContent = fmt(d.general_score);
  document.getElementById('general-count').textContent = d.total_cases;
  document.getElementById('general-health').textContent = fmt(d.data_quality) + '%';
  document.getElementById('general-categories').innerHTML = d.category_chart
    .map(c => `<span class="chip">${escapeHtml(c.name)}: ${fmt(c.value)}</span>`).join('');
}

function drawChart(canvasId, type, data) {
  const ctx = document.getElementById(canvasId);
  if (state.charts[canvasId]) state.charts[canvasId].destroy();
  state.charts[canvasId] = new Chart(ctx, {
    type, data,
    options: {
      responsive: true,
      plugins: { legend: { labels: { font: { family: 'Vazirmatn' } } } },
      scales: { y: { beginAtZero: true, max: 100, ticks: { font: { family: 'Vazirmatn' } } }, x: { ticks: { font: { family: 'Vazirmatn' } } } },
    },
  });
}

/* ------------------------------------------------------------------------
   Comparison
------------------------------------------------------------------------ */
async function loadComparison() {
  const c = await api().get_comparison();
  if (!c.ok) {
    document.getElementById('comparison-empty').style.display = 'block';
    document.getElementById('comparison-content').style.display = 'none';
    return;
  }
  document.getElementById('comparison-empty').style.display = 'none';
  document.getElementById('comparison-content').style.display = 'block';
  document.getElementById('comparison-narrative').innerHTML = `<h3>تحلیل علت تغییر</h3><p>${c.narrative}</p>`;

  document.getElementById('comparison-cat-body').innerHTML = c.categories.map(row => `
    <tr><td>${row.name_fa}</td><td>${fmt(row.period1)}</td><td>${fmt(row.period2)}</td><td>${deltaBadge(row.change)}</td></tr>
  `).join('');

  document.getElementById('comparison-crit-body').innerHTML = c.criteria.map(row => `
    <tr><td>${row.name_fa}</td><td>${fmt(row.period1)}</td><td>${fmt(row.period2)}</td><td>${deltaBadge(row.change)}</td></tr>
  `).join('');
}

/* ------------------------------------------------------------------------
   Ranking
------------------------------------------------------------------------ */
async function loadRanking() {
  const r = await api().get_ranking();
  if (!r.ok) return;
  document.getElementById('ranking-empty').style.display = 'none';
  document.getElementById('ranking-content').style.display = 'block';
  document.getElementById('ranking-body').innerHTML = r.rows.map(row => `
    <tr class="clickable" onclick="showExpertDetail('${row.expert.replace(/'/g, "\\'")}')">
      <td>${row.expert}</td><td>${fmt(row.score !== undefined ? row.score : row.period1_score)}</td>
      <td>${fmt(row.period2_score)}</td><td>${deltaBadge(row.change)}</td>
      <td><span class="badge ${statusBadgeClass(row.status)}">${row.status}</span></td>
      <td>${row.cases !== undefined ? row.cases : row.period2_cases}</td>
    </tr>`).join('');
}

function statusBadgeClass(status) {
  if (status.includes('بهبود')) return 'good';
  if (status.includes('افت')) return 'bad';
  if (status === 'ثابت') return 'warn';
  return 'muted';
}

function strengthCard(s, isPositive) {
  const cls = isPositive ? 'good' : 'bad';
  const cases = s.sample_cases.map(c => `<span class="chip" title="${escapeHtml(c.evidence || '')}">${c.case_number || c.case_key} (${fmt(c.score, 0)})</span>`).join('');
  return `
    <div class="card" style="padding:10px 12px;margin-top:8px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <b style="font-size:12.5px">${s.criterion}</b>
        <span class="badge ${cls}">${fmt(s.avg_score)}</span>
      </div>
      <div style="font-size:11.5px;color:var(--muted);margin:4px 0">میانگین در ${s.count} مورد بررسی‌شده (دسته: ${s.category})</div>
      <div class="chip-list">${cases}</div>
    </div>`;
}

async function showExpertDetail(expert) {
  const d = await api().get_expert_detail(expert);
  if (!d.ok) return;
  state.currentExpert = expert;
  document.getElementById('expert-export-result').innerHTML = '';
  document.getElementById('expert-detail-panel').style.display = 'block';
  document.getElementById('expert-detail-title').textContent = `کارشناس: ${expert}`;

  const statCard = (title, s) => {
    if (!s) return `<div class="card"><h3>${title}</h3><p style="color:var(--muted)">داده‌ای در این دوره وجود ندارد.</p></div>`;
    return `<div class="card"><h3>${title}</h3>
      <table>
        <tr><td>تعداد مورد</td><td>${s.case_count}</td></tr>
        <tr><td>تعداد Note</td><td>${s.note_count}</td></tr>
        <tr><td>تعداد Task</td><td>${s.task_count}</td></tr>
        <tr><td>Objective</td><td>${fmt(s.avg_objective)}</td></tr>
        <tr><td>AI</td><td>${fmt(s.avg_ai)}</td></tr>
        <tr><td>Final</td><td><b>${fmt(s.avg_final)}</b></td></tr>
      </table>
      ${s.weak_criteria.length ? `<div style="margin-top:8px"><b style="font-size:12px">ضعف‌های تکرارشونده:</b> <div class="chip-list" style="margin-top:6px">${s.weak_criteria.map(w => `<span class="chip">${w[0]} (${w[1]})</span>`).join('')}</div></div>` : ''}
      ${s.strong_criteria.length ? `<div style="margin-top:8px"><b style="font-size:12px">نقاط قوت:</b> <div class="chip-list" style="margin-top:6px">${s.strong_criteria.map(w => `<span class="chip">${w[0]} (${w[1]})</span>`).join('')}</div></div>` : ''}
      </div>`;
  };

  document.getElementById('expert-detail-stats').innerHTML = d.general
    ? statCard('تحلیل کلی', d.general)
    : statCard('دوره اول', d.period1) + statCard('دوره دوم', d.period2);

  const fbBox = document.getElementById('expert-feedback-box');
  if (d.feedback && (d.feedback.strengths.length || d.feedback.weaknesses.length)) {
    const fb = d.feedback;
    fbBox.style.display = 'block';
    fbBox.innerHTML = `
      <h3>گزارش عملکرد و بازخورد (دوره دوم در صورت وجود داده، وگرنه دوره اول)</h3>
      <div class="grid cols-2">
        <div>
          <b style="font-size:12.5px">نقاط قوت</b>
          ${fb.strengths.map(s => strengthCard(s, true)).join('') || '<p style="color:var(--muted);font-size:12px">داده کافی برای شناسایی نقطه قوت مستند وجود ندارد.</p>'}
        </div>
        <div>
          <b style="font-size:12.5px">نقاط قابل بهبود</b>
          ${fb.weaknesses.map(s => strengthCard(s, false)).join('') || '<p style="color:var(--muted);font-size:12px">ضعف قابل توجهی شناسایی نشد.</p>'}
        </div>
      </div>
      ${fb.action_plan.length ? `
        <div style="margin-top:14px">
          <b style="font-size:12.5px">برنامه بهبود پیشنهادی</b>
          <table style="margin-top:6px"><thead><tr><th>اولویت</th><th>تمرکز</th><th>دسته</th><th>هدف</th></tr></thead>
          <tbody>${fb.action_plan.map(a => `<tr><td>${a.priority}</td><td>${a.focus}</td><td>${a.category}</td><td>${a.target}</td></tr>`).join('')}</tbody></table>
        </div>` : ''}
    `;
  } else {
    fbBox.style.display = 'none';
  }

  document.getElementById('expert-cases-body').innerHTML = d.cases.map(c => `
    <tr class="clickable" onclick="openCaseDetail('${c.case_key.replace(/'/g, "\\'")}','period2')">
      <td>${c.case_number || '—'}</td><td>${c.case_title || '—'}</td>
      <td><span class="badge ${scoreBadgeClass(c.final_score)}">${fmt(c.final_score)}</span></td>
    </tr>`).join('');
}

/* ------------------------------------------------------------------------
   Expert Groups
------------------------------------------------------------------------ */
let allDetectedExperts = [];
let editingGroupName = null; // اگر null باشد یعنی حالت «ساخت گروه جدید»

async function loadExpertChecklist() {
  const res = await api().get_detected_experts();
  allDetectedExperts = (res.ok && res.experts) ? res.experts : [];
  renderExpertChecklist(allDetectedExperts);
}

function renderExpertChecklist(experts, checkedSet) {
  const box = document.getElementById('expert-checklist');
  checkedSet = checkedSet || new Set(Array.from(document.querySelectorAll('.expert-check:checked')).map(c => c.value));
  if (!experts.length) {
    box.innerHTML = '<span style="color:var(--muted);font-size:12.5px">کارشناسی با این مشخصات پیدا نشد.</span>';
    return;
  }
  box.innerHTML = experts.map(e => `
    <label style="display:flex;align-items:center;gap:6px;padding:4px 0;font-size:12.5px">
      <input type="checkbox" value="${escapeHtml(e)}" class="expert-check" ${checkedSet.has(e) ? 'checked' : ''}> ${e}
    </label>`).join('');
}

function filterExpertChecklist() {
  const q = document.getElementById('expert-search-box').value.trim();
  const checkedSet = new Set(Array.from(document.querySelectorAll('.expert-check:checked')).map(c => c.value));
  const filtered = q ? allDetectedExperts.filter(e => e.includes(q)) : allDetectedExperts;
  renderExpertChecklist(filtered, checkedSet);
}

async function saveNewExpertGroup() {
  const name = document.getElementById('new-group-name').value.trim();
  const unit = document.getElementById('new-group-unit').value;
  const checked = Array.from(document.querySelectorAll('.expert-check:checked')).map(c => c.value);
  if (!name) { toast('نام گروه را وارد کنید', 'error'); return; }
  if (!checked.length) { toast('حداقل یک کارشناس انتخاب کنید', 'error'); return; }
  const res = await api().save_expert_group(name, checked, unit);
  if (!res.ok) { toast(res.error, 'error'); return; }
  toast(editingGroupName ? 'گروه به‌روزرسانی شد' : 'گروه ذخیره شد', 'success');
  cancelEditGroup();
  loadExpertGroupsSettings();
}

function editExpertGroup(name, unit, experts) {
  editingGroupName = name;
  document.getElementById('group-form-title').textContent = `ویرایش گروه: ${name}`;
  document.getElementById('new-group-name').value = name;
  document.getElementById('new-group-name').disabled = true;
  document.getElementById('new-group-unit').value = unit;
  document.getElementById('expert-search-box').value = '';
  renderExpertChecklist(allDetectedExperts, new Set(experts));
  document.getElementById('cancel-edit-group-btn').style.display = 'inline-flex';
  document.getElementById('group-form-title').scrollIntoView({ behavior: 'smooth' });
}

function cancelEditGroup() {
  editingGroupName = null;
  document.getElementById('group-form-title').textContent = 'ساخت گروه جدید';
  document.getElementById('new-group-name').value = '';
  document.getElementById('new-group-name').disabled = false;
  document.getElementById('new-group-unit').value = 'case';
  document.getElementById('expert-search-box').value = '';
  document.getElementById('cancel-edit-group-btn').style.display = 'none';
  renderExpertChecklist(allDetectedExperts, new Set());
}

async function deleteExpertGroup(name) {
  await api().delete_expert_group(name);
  loadExpertGroupsSettings();
  toast('گروه حذف شد');
}

async function loadExpertGroupsSettings() {
  const res = await api().get_expert_groups();
  const groups = res.ok ? res.groups : {};
  const listBox = document.getElementById('expert-groups-list');
  const names = Object.keys(groups);
  if (listBox) {
    listBox.innerHTML = names.length ? names.map(name => {
      const g = groups[name];
      const unitLabel = g.review_unit === 'task' ? 'بر اساس Task' : 'بر اساس مورد';
      return `
      <div class="card" style="padding:12px 14px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <div><b style="font-size:13px">${escapeHtml(name)}</b> <span class="badge muted">${unitLabel}</span></div>
          <div>
            <button class="btn ghost" onclick='editExpertGroup(${JSON.stringify(name)}, ${JSON.stringify(g.review_unit)}, ${JSON.stringify(g.experts)})'>ویرایش</button>
            <button class="btn ghost" onclick="deleteExpertGroup('${name.replace(/'/g, "\\'")}')">حذف گروه</button>
          </div>
        </div>
        <div class="chip-list">${g.experts.map(e => `<span class="chip">${escapeHtml(e)}</span>`).join('')}</div>
      </div>`;
    }).join('') : '<span style="color:var(--muted);font-size:12.5px">هنوز گروهی ساخته نشده است.</span>';
  }
  const select = document.getElementById('run-expert-group');
  if (select) {
    const current = select.value;
    select.innerHTML = '<option value="">همه کارشناسان</option>' +
      names.map(n => `<option value="${escapeHtml(n)}" data-unit="${groups[n].review_unit}">${escapeHtml(n)} (${groups[n].review_unit === 'task' ? 'Task' : 'مورد'})</option>`).join('');
    if (names.includes(current)) select.value = current;
  }
}

/* --------------------------------------------------------- Default groups */
async function loadDefaultGroupSuggestions() {
  const box = document.getElementById('default-groups-suggestions');
  if (!state.datasetLoaded) { toast('ابتدا فایل‌ها را بارگذاری کنید', 'error'); return; }
  box.innerHTML = '<div class="warn-box">در حال بررسی تطبیق نام‌ها...</div>';
  const res = await api().suggest_default_groups();
  if (!res.ok) { box.innerHTML = `<div class="err-box">${res.error}</div>`; return; }

  const groupBlocks = Object.entries(res.suggestions).map(([groupName, data]) => {
    const rows = data.entries.map((e, i) => {
      const fieldId = `sugg-${groupName}-${i}`;
      let control;
      if (e.status === 'matched') {
        control = `<span class="badge good">${e.matches[0]}</span><input type="hidden" id="${fieldId}" value="${escapeHtml(e.matches[0])}">`;
      } else if (e.status === 'ambiguous') {
        control = `<select id="${fieldId}">${e.matches.map(m => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`).join('')}</select>`;
      } else {
        control = `<span class="badge bad">پیدا نشد</span><input type="hidden" id="${fieldId}" value="">`;
      }
      return `<div class="suggestion-row"><span class="target">${escapeHtml(e.target)}</span>${control}</div>`;
    }).join('');
    return `
      <div class="card" style="margin-bottom:12px">
        <h3>${escapeHtml(groupName)} <span class="badge muted">${data.review_unit === 'task' ? 'بر اساس Task' : 'بر اساس مورد'}</span></h3>
        ${rows}
      </div>`;
  }).join('');

  box.innerHTML = groupBlocks + `<button class="btn primary" onclick='confirmDefaultGroups(${JSON.stringify(res.suggestions)})'>ایجاد این گروه‌ها</button>`;
}

async function confirmDefaultGroups(suggestions) {
  const selections = {};
  for (const [groupName, data] of Object.entries(suggestions)) {
    const experts = [];
    data.entries.forEach((e, i) => {
      const el = document.getElementById(`sugg-${groupName}-${i}`);
      const val = el ? el.value : '';
      if (val) experts.push(val);
    });
    selections[groupName] = { review_unit: data.review_unit, experts };
  }
  const res = await api().create_default_groups(selections);
  if (res.ok) {
    toast(`گروه‌های ${res.created.join('، ')} ایجاد شدند`, 'success');
    document.getElementById('default-groups-suggestions').innerHTML = '';
    loadExpertGroupsSettings();
  } else {
    toast(res.error || 'خطا در ایجاد گروه‌ها', 'error');
  }
}

/* --------------------------------------------------- Export/Import settings */
async function exportSettings() {
  const path = await api().pick_save_path('تنظیمات-ارزیابی-CRM.json');
  if (!path) return;
  const res = await api().export_settings(path);
  document.getElementById('settings-io-result').innerHTML = res.ok
    ? `<div class="ok-box">تنظیمات در ${res.path} ذخیره شد.</div>` : `<div class="err-box">${res.error}</div>`;
}

async function importSettings() {
  const path = await api().pick_file();
  if (!path) return;
  const mode = document.getElementById('import-mode').value;
  const res = await api().import_settings(path, mode);
  const box = document.getElementById('settings-io-result');
  if (!res.ok) { box.innerHTML = `<div class="err-box">${res.error}</div>`; return; }
  box.innerHTML = `<div class="ok-box">تنظیمات وارد شد. گروه‌های وارد‌شده: ${res.imported_groups.join('، ') || 'هیچ‌کدام'}.<br>${res.note}</div>`;
  loadCriteria();
  loadAiSettings();
  loadExpertGroupsSettings();
}


/* ------------------------------------------------------------------------
   Cases table + detail
------------------------------------------------------------------------ */
async function loadCasesTable(page) {
  state.casesPage = page;
  const period = state.analysisMode === 'general' ? 'general' : document.getElementById('cases-period').value;
  const expertFilter = document.getElementById('cases-expert-filter').value || null;
  const statusFilter = state.casesStatusReasons.slice();
  const numberQuery = document.getElementById('cases-number-search').value.trim() || null;
  const serviceFilter = document.getElementById('cases-service-filter').value || null;
  const res = await api().get_cases_table(period, page, state.casesPageSize, expertFilter,
    statusFilter.length ? statusFilter : null, numberQuery, serviceFilter);
  if (!res.ok) return;
  document.getElementById('cases-empty').style.display = 'none';
  document.getElementById('cases-content').style.display = 'block';

  // پر کردن گزینه‌های فیلتر (فقط اگر قبلاً پر نشده یا دوره عوض شده)
  fillFilterOptions('cases-expert-filter', res.experts, expertFilter);
  fillFilterOptions('cases-service-filter', res.services || [], serviceFilter);
  state.casesStatusReasons = state.casesStatusReasons.filter(v => (res.status_reasons || []).includes(v));
  renderMultiFilterOptions('cases-status-options', res.status_reasons, state.casesStatusReasons, values => {
    state.casesStatusReasons = values;
    updateMultiFilterButton('cases-status-filter-wrap', values, 'انتخاب وضعیت‌ها');
    loadCasesTable(0);
  });

  const isTask = res.unit === 'task';
  document.getElementById('cases-table-head').innerHTML = isTask
    ? '<tr><th>شماره Task</th><th>عنوان</th><th>نوع مورد</th><th>کارشناس</th><th colspan="2">—</th><th>Objective</th><th>AI</th><th>Final</th></tr>'
    : '<tr><th>شماره مورد</th><th>عنوان</th><th>نوع مورد</th><th>کارشناس</th><th>Note</th><th>Task</th><th>Objective</th><th>AI</th><th>Final</th></tr>';

  document.getElementById('cases-table-body').innerHTML = res.rows.map(r => `
    <tr class="clickable" onclick="openCaseDetail('${r.case_key.replace(/'/g, "\\'")}','${period}')">
      <td>${r.case_number || '—'}</td><td>${r.case_title || '—'}</td><td>${r.service || '—'}</td><td>${r.expert}</td>
      ${isTask ? '<td colspan="2">—</td>' : `<td>${r.notes}</td><td>${r.tasks}</td>`}
      <td>${fmt(r.objective_score)}</td><td>${r.ai_analyzed ? `<span class="badge good" title="تحلیل AI قبلاً انجام شده است">${fmt(r.ai_score)} ✓</span>` : '<span class="badge muted">انجام نشده</span>'}</td>
      <td><span class="badge ${scoreBadgeClass(r.final_score)}">${fmt(r.final_score)}</span></td>
    </tr>`).join('');
  const start = page * state.casesPageSize;
  document.getElementById('cases-page-info').textContent =
    `نمایش ${res.total ? start + 1 : 0}-${Math.min(start + state.casesPageSize, res.total)} از ${res.total}`;
}

function fillFilterOptions(selectId, options, currentValue) {
  const select = document.getElementById(selectId);
  const existing = Array.from(select.options).map(o => o.value).slice(1).sort().join(',');
  const incoming = (options || []).slice().sort().join(',');
  if (existing === incoming) { select.value = currentValue || ''; return; }
  const placeholder = select.options[0].outerHTML;
  select.innerHTML = placeholder + (options || []).map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('');
  select.value = currentValue || '';
}

function renderMultiFilterOptions(containerId, options, currentValues, onChange) {
  const container = document.getElementById(containerId);
  const set = new Set(currentValues || []);
  container.innerHTML = (options || []).map(value => `
    <label class="multi-filter-option"><input type="checkbox" value="${escapeHtml(value)}" ${set.has(value) ? 'checked' : ''}>${escapeHtml(value)}</label>
  `).join('') || '<span style="color:var(--muted);font-size:12px">موردی موجود نیست</span>';
  container.querySelectorAll('input').forEach(input => input.addEventListener('change', () => {
    onChange(Array.from(container.querySelectorAll('input:checked')).map(x => x.value));
  }));
}

function toggleMultiFilter(id) { document.getElementById(id).classList.toggle('open'); }
function updateMultiFilterButton(id, values, emptyLabel) {
  const btn = document.querySelector(`#${id} .multi-filter-button`);
  if (btn) btn.textContent = values.length ? `${values.length} انتخاب شده` : emptyLabel;
}
function clearCasesStatusFilter() {
  state.casesStatusReasons = [];
  updateMultiFilterButton('cases-status-filter-wrap', [], 'انتخاب وضعیت‌ها');
  loadCasesTable(0);
}

let casesSearchTimer = null;
function debouncedCasesSearch() {
  clearTimeout(casesSearchTimer);
  casesSearchTimer = setTimeout(() => loadCasesTable(0), 350);
}

function filterSuspiciousTable() {
  const q = document.getElementById('suspicious-number-search').value.trim().toLowerCase();
  document.querySelectorAll('#suspicious-body tr').forEach(tr => {
    const num = (tr.dataset.caseNumber || '').toLowerCase();
    tr.style.display = (!q || num.includes(q)) ? '' : 'none';
  });
}

function casesPrev() { if (state.casesPage > 0) loadCasesTable(state.casesPage - 1); }
function casesNext() { loadCasesTable(state.casesPage + 1); }

async function openCaseDetail(caseKey, period) {
  const d = await api().get_case_detail(caseKey, period);
  if (!d.ok) { toast(d.error || 'خطا در بارگذاری مورد', 'error'); return; }
  document.getElementById('case-modal-overlay').style.display = 'flex';
  document.getElementById('case-detail-title').textContent = `${d.case_number || ''} — ${d.case_title || ''}`;
  document.getElementById('case-detail-meta').innerHTML =
    `مشتری: ${d.customer || '—'} | Owner: ${d.owner || '—'} | سرویس: ${d.service || '—'} | وضعیت: ${d.status || '—'} / ${d.status_reason || ''}` +
    (d.ai_analysis?.analyzed_at ? ` | آخرین تحلیل AI: ${dateDual(d.ai_analysis.analyzed_at)}` : '');

  renderCaseAiActions(caseKey, d.ai_analyzed);
  renderCaseAiSuggestions(d.improvement_suggestions || []);
  const scenarioBox = document.getElementById('case-detail-scenario-desc');
  let scenarioHtml = '';
  if (d.scenario && d.scenario.trim()) {
    scenarioHtml += `<div class="scenario-box"><span class="label">سناریوی وقوع (Scenario)</span>${escapeHtml(d.scenario)}</div>`;
  }
  if (d.case_description && d.case_description.trim()) {
    scenarioHtml += `<div class="scenario-box"><span class="label">شرح مورد (Description)</span>${escapeHtml(d.case_description)}</div>`;
  }
  scenarioBox.innerHTML = scenarioHtml;

  document.getElementById('case-timeline').innerHTML = d.timeline.map(ev => `
    <div class="timeline-item ${ev.role.includes('مشتری') ? 'customer' : ''}">
      <div class="meta">${dateDual(ev.date)} — ${ev.role} (${ev.author}) — ${ev.type === 'note' ? 'Note' : 'Task'}</div>
      <div class="text">${escapeHtml(ev.text)}</div>
    </div>`).join('') || '<p style="color:var(--muted)">رویداد دارای تاریخ معتبر ثبت نشده است.</p>';

  if (d.breakdown) {
    document.getElementById('case-score-summary').innerHTML = [
      ['Objective', d.breakdown.objective_score], ['AI', d.breakdown.ai_score], ['Final', d.breakdown.final_score],
      ['Coverage', `${Math.round((d.breakdown.coverage || 0) * 100)}%`],
      ['Confidence', d.breakdown.confidence || '—'],
      ['AI استفاده شده؟', d.breakdown.ai_used ? 'بله' : 'خیر'],
      ['Outcome', d.breakdown.outcome_status || 'Unknown'],
      ['Lifecycle', d.breakdown.lifecycle_status || '—'],
    ].map(([l, v]) => `<div class="card kpi"><div class="label">${l}</div><div class="value small">${typeof v === 'number' ? fmt(v) : v}</div></div>`).join('');

    document.getElementById('case-breakdown-body').innerHTML = d.breakdown.criteria.map(c => `
      <tr><td>${c.name_fa}</td><td>${c.category}</td><td><span class="type-tag">${c.type}</span></td>
        <td>${c.score === null ? '<span class="badge muted">N/A</span>' : `<span class="badge ${scoreBadgeClass(c.score)}">${fmt(c.score, 0)}</span>`}</td>
        <td>${Math.round((c.coverage || 0) * 100)}%</td>
        <td><span class="badge ${c.confidence === 'high' ? 'good' : c.confidence === 'medium' ? 'warn' : 'muted'}">${c.confidence || 'low'}</span></td>
        <td style="font-size:12px;color:var(--muted)">${escapeHtml(c.evidence || c.na_reason || '')}</td></tr>`).join('');
  } else {
    document.getElementById('case-score-summary').innerHTML = '';
    document.getElementById('case-breakdown-body').innerHTML = '<tr><td colspan="5" style="color:var(--muted)">برای این مورد امتیازی در دوره انتخاب‌شده محاسبه نشده است.</td></tr>';
  }
  switchCaseTab('timeline');
}

function renderCaseAiActions(caseKey, analyzed, running = false) {
  const box = document.getElementById('case-ai-actions');
  const errorBox = document.getElementById('case-ai-error');
  if (!box) return;
  if (errorBox) errorBox.style.display = 'none';
  if (running) {
    box.innerHTML = '<span class="badge warn">در حال بررسی با AI...</span>';
  } else if (analyzed) {
    box.innerHTML = `<span class="badge good">این کیس قبلاً با AI بررسی شده است</span>
      <button class="btn ghost" onclick="runSingleCaseAi('${caseKey.replace(/'/g, "\\'")}', true)">بررسی مجدد با AI</button>`;
  } else {
    box.innerHTML = `<button class="btn primary" onclick="runSingleCaseAi('${caseKey.replace(/'/g, "\\'")}', false)">بررسی این کیس با AI</button>`;
  }
}

async function runSingleCaseAi(caseKey, force = false) {
  renderCaseAiActions(caseKey, true, true);
  const started = await api().start_case_ai_analysis(caseKey, force);
  if (!started.ok) {
    renderCaseAiActions(caseKey, false);
    showCaseAiError(started.error || 'شروع بررسی AI ناموفق بود');
    return;
  }
  const poll = async () => {
    const status = await api().get_case_ai_status(caseKey);
    if (status.running) { setTimeout(poll, 500); return; }
    if (status.error) {
      renderCaseAiActions(caseKey, false);
      showCaseAiError(status.error);
      return;
    }
    toast('بررسی AI این کیس با موفقیت انجام شد', 'success');
    const detail = await api().get_case_detail(caseKey, 'all');
    renderCaseAiActions(caseKey, detail.ai_analyzed);
    renderCaseAiSuggestions(detail.improvement_suggestions || []);
    if (detail.breakdown) renderCaseBreakdown(detail.breakdown);
    refreshAllReports();
  };
  poll();
}

function showCaseAiError(message) {
  const box = document.getElementById('case-ai-error');
  if (box) {
    box.textContent = `بررسی AI انجام نشد:\n${message}`;
    box.style.display = 'block';
  }
  toast('بررسی AI انجام نشد؛ جزئیات در پنجره کیس نمایش داده شد', 'error');
}

function renderCaseAiSuggestions(items) {
  const box = document.getElementById('case-ai-suggestions');
  if (!box) return;
  if (!items || !items.length) {
    box.innerHTML = '';
    return;
  }
  const typeNames = {
    add_pattern: 'افزودن واژه/الگو به Rule موجود',
    activate_criterion: 'فعال‌سازی معیار برای نوع Case/Service',
    new_rule: 'پیشنهاد Rule جدید',
  };
  box.innerHTML = `
    <div class="card" style="border-right:4px solid var(--accent);padding:12px">
      <div style="font-weight:700;margin-bottom:8px">پیشنهادهای بهبود معیارها</div>
      <div style="font-size:12px;color:var(--muted);margin-bottom:10px">
        این موارد فقط پیشنهاد AI هستند و هیچ Rule یا امتیازی را خودکار تغییر نمی‌دهند.
      </div>
      ${items.map(item => `
        <div style="padding:9px 0;border-top:1px solid var(--border)">
          <div style="font-weight:600">${escapeHtml(item.title)}
            <span class="badge muted">${escapeHtml(typeNames[item.type] || item.type)}</span>
          </div>
          <div style="font-size:12px;margin-top:4px">
            معیار: ${escapeHtml(item.criterion_id)} — اعتماد: ${escapeHtml(item.confidence || 'low')}
          </div>
          <div style="font-size:12px;color:var(--muted);margin-top:4px">
            مشکل: ${escapeHtml(item.problem)}<br>
            پیشنهاد: ${escapeHtml(item.suggestion)}<br>
            شواهد: ${escapeHtml(item.evidence)}
          </div>
        </div>`).join('')}
    </div>`;
}

function renderCaseBreakdown(breakdown) {
  document.getElementById('case-score-summary').innerHTML = [
    ['Objective', breakdown.objective_score], ['AI', breakdown.ai_score], ['Final', breakdown.final_score],
    ['Coverage', `${Math.round((breakdown.coverage || 0) * 100)}%`],
    ['Confidence', breakdown.confidence || '—'],
    ['AI استفاده شده؟', breakdown.ai_used ? 'بله' : 'خیر'],
    ['Outcome', breakdown.outcome_status || 'Unknown'],
    ['Lifecycle', breakdown.lifecycle_status || '—'],
  ].map(([l, v]) => `<div class="card kpi"><div class="label">${l}</div><div class="value small">${typeof v === 'number' ? fmt(v) : v}</div></div>`).join('');
  document.getElementById('case-breakdown-body').innerHTML = breakdown.criteria.map(c => `
    <tr><td>${c.name_fa}</td><td>${c.category}</td><td><span class="type-tag">${c.type}</span></td>
      <td>${c.score === null ? '<span class="badge muted">N/A</span>' : `<span class="badge ${scoreBadgeClass(c.score)}">${fmt(c.score, 0)}</span>`}</td>
      <td>${Math.round((c.coverage || 0) * 100)}%</td>
      <td><span class="badge ${c.confidence === 'high' ? 'good' : c.confidence === 'medium' ? 'warn' : 'muted'}">${c.confidence || 'low'}</span></td>
      <td style="font-size:12px;color:var(--muted)">${escapeHtml(c.evidence || c.na_reason || '')}</td></tr>`).join('');
}

function closeCaseModal() {
  document.getElementById('case-modal-overlay').style.display = 'none';
}

function switchCaseTab(tab) {
  document.querySelectorAll('#case-modal-overlay .tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.getElementById('case-tab-timeline').style.display = tab === 'timeline' ? 'block' : 'none';
  document.getElementById('case-tab-breakdown').style.display = tab === 'breakdown' ? 'block' : 'none';
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text || '';
  return div.innerHTML;
}

/* ------------------------------------------------------------------------
   Suspicious
------------------------------------------------------------------------ */
async function loadSuspicious() {
  const expert = document.getElementById('suspicious-expert-filter')?.value || null;
  const service = document.getElementById('suspicious-service-filter')?.value || null;
  const r = await api().get_suspicious(expert, state.suspiciousReasons.length ? state.suspiciousReasons : null, service);
  if (!r.ok) return;
  const badge = document.getElementById('suspicious-badge');
  if (badge) {
    badge.textContent = String(r.rows.length);
    badge.hidden = r.rows.length === 0;
  }
  document.getElementById('suspicious-empty').style.display = 'none';
  document.getElementById('suspicious-content').style.display = 'block';
  fillFilterOptions('suspicious-expert-filter', r.experts || [], expert);
  fillFilterOptions('suspicious-service-filter', r.services || [], service);
  renderMultiFilterOptions('suspicious-reason-options', r.reasons || [], state.suspiciousReasons, values => {
    state.suspiciousReasons = values;
    updateMultiFilterButton('suspicious-reason-filter-wrap', values, 'انتخاب دلایل');
    loadSuspicious();
  });
  document.getElementById('suspicious-body').innerHTML = r.rows.map(row => `
    <tr class="clickable" data-case-number="${escapeHtml(row.case_number || '')}" onclick="openCaseDetail('${row.case_key.replace(/'/g, "\\'")}','all')">
      <td>${row.case_number || '—'}</td><td>${row.case_title || '—'}</td><td>${row.service || '—'}</td>
      <td><div class="chip-list">${row.reasons.map(rs => `<span class="chip">${rs}</span>`).join('')}</div></td>
    </tr>`).join('');
  filterSuspiciousTable();
}

function clearSuspiciousReasonFilter() {
  state.suspiciousReasons = [];
  updateMultiFilterButton('suspicious-reason-filter-wrap', [], 'انتخاب دلایل');
  loadSuspicious();
}

/* ------------------------------------------------------------------------
   Data Quality
------------------------------------------------------------------------ */
async function loadDataQuality() {
  const d = await api().get_data_quality();
  if (!d.ok) return;
  document.getElementById('dq-empty').style.display = 'none';
  document.getElementById('dq-content').style.display = 'block';
  document.getElementById('dq-index').textContent = fmt(d.index) + '%';
  document.getElementById('dq-body').innerHTML = d.checks.map(c => `
    <tr><td>${c.name_fa}</td>
      <td><span class="badge ${scoreBadgeClass(c.healthy_score)}">${fmt(c.healthy_score)}%</span></td>
      <td>${c.issue_count}</td><td style="font-size:12px;color:var(--muted)">${c.detail_fa}</td></tr>`).join('');
}

/* ------------------------------------------------------------------------
   Management report
------------------------------------------------------------------------ */
async function loadMgmtReport() {
  const r = await api().get_management_report();
  if (!r.ok) return;
  document.getElementById('mgmt-empty').style.display = 'none';
  document.getElementById('mgmt-content').style.display = 'block';
  document.getElementById('mgmt-status').textContent = r.overall_status;
  document.getElementById('mgmt-strengths').innerHTML = r.top_strengths.length
    ? r.top_strengths.map(s => `<span class="chip">${s}</span>`).join('') : '<span style="color:var(--muted)">موردی شناسایی نشد.</span>';
  document.getElementById('mgmt-weaknesses').innerHTML = r.top_weaknesses.map(w => `<span class="chip">${w.name} (${fmt(w.score)})</span>`).join('');
  document.getElementById('mgmt-improved').innerHTML = r.most_improved.map(e => `<li>${e.expert}: +${fmt(e.change)}</li>`).join('') || '<li style="color:var(--muted)">موردی نیست</li>';
  document.getElementById('mgmt-declined').innerHTML = r.most_declined.map(e => `<li>${e.expert}: ${fmt(e.change)}</li>`).join('') || '<li style="color:var(--muted)">موردی نیست</li>';
  document.getElementById('mgmt-data-issues').innerHTML = r.data_issues.length
    ? r.data_issues.map(s => `<span class="chip">${s}</span>`).join('') : '<span style="color:var(--muted)">مشکل قابل‌توجهی نیست.</span>';
  document.getElementById('mgmt-recs').innerHTML = r.recommendations.map(x => `<li>${x}</li>`).join('');
}

/* ------------------------------------------------------------------------
   Export
------------------------------------------------------------------------ */
async function exportExcel() {
  const path = await api().pick_save_path('گزارش-ارزیابی-کیفیت-CRM.xlsx');
  if (!path) return;
  const res = await api().export_excel_report(path);
  document.getElementById('export-result').innerHTML = res.ok
    ? `<div class="ok-box">فایل ذخیره شد: ${res.path}</div>` : `<div class="err-box">${res.error}</div>`;
}

async function exportCsv() {
  const table = document.getElementById('csv-table-select').value;
  const path = await api().pick_save_path(table + '.csv');
  if (!path) return;
  const res = await api().export_csv_table(table, path);
  document.getElementById('export-result').innerHTML = res.ok
    ? `<div class="ok-box">فایل ذخیره شد: ${res.path}</div>` : `<div class="err-box">${res.error}</div>`;
}

async function exportExpertReport() {
  if (!state.currentExpert) return;
  const box = document.getElementById('expert-export-result');
  const safeName = state.currentExpert.replace(/[\\/:*?"<>|]/g, '_');
  const path = await api().pick_save_path(`گزارش-عملکرد-${safeName}.xlsx`);
  if (!path) return;
  box.innerHTML = '<div class="warn-box">در حال ساخت گزارش...</div>';
  const res = await api().export_expert_report_excel(state.currentExpert, path);
  box.innerHTML = res.ok
    ? `<div class="ok-box">گزارش ذخیره شد: ${res.path}</div>` : `<div class="err-box">${res.error}</div>`;
}

/* ------------------------------------------------------------------------
   Init
   نکته: در برخی نسخه‌ها/بک‌اندهای pywebview، رویداد pywebviewready ممکن
   است قبل از اتصال این Listener شلیک شده باشد؛ برای اطمینان، هم رویداد
   را گوش می‌دهیم و هم به‌صورت Polling بررسی می‌کنیم که window.pywebview.api
   آماده شده یا نه.
------------------------------------------------------------------------ */
let appInitialized = false;
function apiMethodsReady() {
  return !!(window.pywebview && window.pywebview.api &&
    typeof window.pywebview.api.get_criteria === 'function' &&
    typeof window.pywebview.api.get_ai_settings === 'function' &&
    typeof window.pywebview.api.pick_file === 'function');
}
function initApp() {
  if (appInitialized) return;
  if (!apiMethodsReady()) return; // هنوز کامل آماده نشده؛ Poll ادامه پیدا می‌کند
  appInitialized = true;
  applyNavigationLabels();
  const loadingOverlay = document.getElementById('boot-loading');
  if (loadingOverlay) loadingOverlay.style.display = 'none';
  loadCriteria();
  loadAiSettings();
  loadExpertGroupsSettings();
  autoLoadDefaultFiles();
  buildJalaliPicker('p1-start-picker');
  buildJalaliPicker('p1-end-picker');
  buildJalaliPicker('p2-start-picker');
  buildJalaliPicker('p2-end-picker');
  api().get_version().then(v => {
    document.getElementById('app-version').textContent = 'نگارش: ' + v;
  }).catch(() => {});
}

if (apiMethodsReady()) {
  initApp();
} else {
  window.addEventListener('pywebviewready', initApp);
  let tries = 0;
  const readyPoll = setInterval(() => {
    tries += 1;
    if (apiMethodsReady()) {
      clearInterval(readyPoll);
      initApp();
    } else if (tries > 200) {
      // بعد از ~۲۰ ثانیه هنوز متدهای API کامل آماده نشده -> به‌جای شکست
      // خاموش (که قبلاً باعث می‌شد دکمه‌ها و معیارها بدون هیچ توضیحی کار نکنند)
      // یک پیام خطای واضح، قابل‌مشاهده و قابل‌اقدام به کاربر نشان می‌دهیم.
      clearInterval(readyPoll);
      const loadingOverlay = document.getElementById('boot-loading');
      if (loadingOverlay) loadingOverlay.style.display = 'none';
      document.getElementById('boot-error').style.display = 'flex';
      console.error('متدهای pywebview API کامل آماده نشدند.');
    }
  }, 100);
}
