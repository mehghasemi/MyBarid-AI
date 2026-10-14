/* Persisted inventory: all requests below are local, never CRM fetches. */
const cachedInventoryState = {};
for (const [module, page] of [['crm-quality', 'upload'], ['case-planning', 'planning-settings']]) {
 const section = document.getElementById('page-' + page);
 section.insertAdjacentHTML('beforeend', `<div class="card cached-inventory" id="inventory-${module}">
  <h3>اطلاعات دریافت‌شده و ذخیره‌شده این ماژول</h3>
  <p class="page-sub">این اطلاعات از دیتابیس محلی خوانده می‌شوند؛ باز کردن این صفحه دریافت جدید از CRM نیست.</p>
  <div id="inventory-summary-${module}" aria-live="polite">در حال خواندن اطلاعات ذخیره‌شده…</div>
  <div class="row"><div class="field"><label for="inventory-search-${module}">جست‌وجوی شماره یا عنوان مورد</label>
  <input id="inventory-search-${module}"></div><button class="btn" onclick="loadCachedInventory('${module}',0)">جست‌وجو / بازخوانی محلی</button></div>
  <div class="cached-table-scroll"><table><thead><tr><th>شماره مورد</th><th>عنوان</th><th>وضعیت</th><th>یادداشت</th><th>Task</th><th>رویدادهای ذخیره‌شده</th></tr></thead>
  <tbody id="inventory-rows-${module}"></tbody></table></div>
  <div class="row"><button class="btn" id="inventory-prev-${module}" onclick="changeInventoryPage('${module}',-1)">صفحه قبل</button>
  <span id="inventory-page-${module}"></span><button class="btn" id="inventory-next-${module}" onclick="changeInventoryPage('${module}',1)">صفحه بعد</button></div></div>`);
 cachedInventoryState[module] = {page: 0, request: 0};
 document.getElementById('inventory-search-' + module).addEventListener('keydown', event => {
  if (event.key === 'Enter') loadCachedInventory(module, 0);
 });
}
function inventoryDate(value, utc = false) {
 if (!value) return 'ثبت نشده';
 // Backend's naive timestamps are UTC, matching Dynamics serialization.
 const normalized = !utc || /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + 'Z';
 const date = new Date(normalized);
 return Number.isNaN(date.getTime()) ? 'تاریخ نامعتبر' : date.toLocaleString('fa-IR');
}
function changeInventoryPage(module, delta) {
 return loadCachedInventory(module, cachedInventoryState[module].page + delta);
}
async function loadCachedInventory(module, page = 0) {
 const current = cachedInventoryState[module];
 const request = ++current.request;
 const summary = document.getElementById('inventory-summary-' + module);
 const body = document.getElementById('inventory-rows-' + module);
 try {
  const result = await api().get_module_cached_data(module, page, document.getElementById('inventory-search-' + module).value);
  if (request !== current.request) return;
  if (!result.ok) throw new Error(result.error);
  current.page = result.page;
  const safe = value => escapeHtml(String(value ?? ''));
  const number = value => Number(value || 0).toLocaleString('fa-IR');
  summary.innerHTML = result.loaded ? `<p>View داده ذخیره‌شده: <strong>${safe(result.snapshot_view)}</strong><br>View انتخاب‌شده: ${safe(result.selected_view || 'انتخاب نشده')}<br>
   آخرین دریافت موفق: ${safe(inventoryDate(result.fetched_at))}<br>
   کل موردهای موجود: ${number(result.counts.cases)} | یادداشت: ${number(result.counts.notes)} | Task: ${number(result.counts.tasks)}<br>
   نوع آخرین دریافت: ${result.sync_mode === 'incremental' ? 'افزایشی' : result.sync_mode === 'full' ? 'کامل / اولیه' : 'ثبت نشده'}
   ${result.changed ? `<br>جدید یا تغییرکرده در آخرین دریافت: ${number(result.changed.notes)} یادداشت و ${number(result.changed.tasks)} Task` : ''}</p>
   ${result.new_or_changed_notes != null ? `<p>یادداشت جدید یا تغییرکرده: ${number(result.new_or_changed_notes)} | حذف‌شده در آخرین بررسی: ${number(result.deleted_notes)} | تعداد دریافت موفق: ${number(result.sync_count)}</p>` : ''}
   ${result.last_full_sync_at ? `<p>آخرین دریافت کامل: ${safe(inventoryDate(result.last_full_sync_at))}</p>` : ''}
   ${result.view_mismatch ? '<div class="warn-box">داده موجود متعلق به View قبلی است؛ انتخاب View جدید به‌تنهایی داده‌های قبلی را جایگزین نمی‌کند.</div>' : ''}
   <p class="page-sub">زمان بالا مربوط به آخرین دریافت کل Snapshot است، نه زمان واکشی تک‌تک رویدادها. فهرست فقط شامل اطلاعاتی است که واقعاً در برنامه ذخیره شده‌اند.</p>`
   : `<div class="warn-box">برای View ${safe(result.selected_view || 'انتخاب‌نشده')} هنوز داده محلی ذخیره نشده است. دریافت موفق لازم است.</div>`;
  body.innerHTML = result.rows.map(row => {
   const events = [...row.notes.map(event => ({...event, kind: 'یادداشت'})), ...row.tasks.map(event => ({...event, kind: 'Task'}))];
   return `<tr><td dir="ltr">${safe(row.number)}</td><td>${safe(row.title || 'عنوان ثبت نشده')}</td><td>${safe(row.status || 'ثبت نشده')}</td>
    <td>${number(row.notes.length)}</td><td>${number(row.tasks.length)}</td><td><details><summary>جزئیات و رویدادها (${number(events.length)})</summary>
    <p>مشتری: ${safe(row.customer || 'ثبت نشده')} | مسئول: ${safe(row.owner || 'ثبت نشده')} | سرویس: ${safe(row.service || 'ثبت نشده')}</p>
    ${events.map(event => `<div class="cached-event"><strong>${safe(event.kind)} — ${safe(event.title)}</strong><p>${safe(inventoryDate(event.date, true))}${event.modified_on ? ' | آخرین تغییر: ' + safe(inventoryDate(event.modified_on, true)) : ''}</p><div>${safe(event.text || 'متن ثبت نشده')}</div></div>`).join('')}</details></td></tr>`;
  }).join('') || '<tr><td colspan="6">موردی برای نمایش وجود ندارد.</td></tr>';
  document.getElementById('inventory-page-' + module).textContent = `${number(result.total)} مورد — صفحه ${number(result.page + 1)} از ${number(Math.max(1, Math.ceil(result.total/result.page_size)))}`;
  document.getElementById('inventory-prev-' + module).disabled = result.page === 0;
  document.getElementById('inventory-next-' + module).disabled = (result.page + 1) * result.page_size >= result.total;
 } catch (error) {
  if (request !== current.request) return;
  summary.textContent = 'خطا در خواندن داده محلی: ' + error.message;
  body.replaceChildren();
 }
}
