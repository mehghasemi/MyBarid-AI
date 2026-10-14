/* Shared settings and module-specific navigation; no automatic CRM fetch. */
const settingsHost = document.getElementById('page-management').parentElement;
settingsHost.insertAdjacentHTML('beforeend', `
<section class="page" id="page-main-settings">
 <h1 class="page-title">تنظیمات اصلی برنامه</h1>
 <p class="page-sub">اتصال CRM و مدل هوش مصنوعی بین ماژول‌ها مشترک هستند. View هر ماژول جداگانه ذخیره می‌شود.</p>
 <div class="card"><h3>اتصال مشترک CRM</h3>
 <div class="row"><div class="field"><label for="main-crm-url">آدرس CRM</label><input id="main-crm-url" dir="ltr"></div>
 <div class="field"><label for="main-crm-org">نام سازمان</label><input id="main-crm-org" dir="ltr"></div>
 <div class="field"><label for="main-crm-api">نسخه API</label><input id="main-crm-api" dir="ltr"></div></div>
 <button class="btn primary" onclick="saveMainSettings()">ذخیره تنظیمات اصلی</button>
 <p>ورود CRM در فرم دریافت هر ماژول انجام می‌شود؛ این صفحه رمز عبور ذخیره نمی‌کند.</p></div>
 <div class="card"><h3>ماژول پیش‌فرض هنگام ورود</h3><label for="main-default-module">برنامه با کدام ماژول باز شود؟</label>
 <select id="main-default-module"><option value="crm-quality">ارزیابی موارد</option><option value="case-planning">برنامه‌ریزی موارد</option></select>
 <p>با دکمه «ذخیره تنظیمات اصلی» ذخیره کنید. از ورود بعدی اعمال می‌شود؛ دریافت CRM خودکار شروع نمی‌شود.</p></div>
 <div class="card"><h3>هوش مصنوعی مشترک</h3><p>سرویس، مدل و کلید مشترک هستند. فعال‌بودن AI در ارزیابی جداگانه قابل تنظیم است.</p>
 <button class="btn" onclick="showPage('ai-settings')">تنظیمات مدل و کلید AI</button></div>
 <div class="card"><h3>محل نگهداری تنظیمات و داده‌ها</h3><p id="main-storage" dir="ltr"></p><p>تنظیمات ذخیره‌شده با بستن برنامه باقی می‌مانند.</p></div>
</section>
<section class="page" id="page-evaluation-settings"><h1 class="page-title">تنظیمات ماژول ارزیابی موارد</h1>
 <div class="card"><label><input type="checkbox" id="evaluation-ai-enabled"> استفاده از AI در ارزیابی (علاوه بر فعال‌بودن تنظیمات اصلی)</label>
 <button class="btn primary" onclick="saveEvaluationSettings()">ذخیره</button></div>
 <div class="card"><p>این تنظیمات فقط متعلق به ماژول ارزیابی هستند؛ روی برنامه‌ریزی موارد اثر ندارند.</p>
 <button class="btn" onclick="showPage('upload')">View پیش‌فرض و دریافت CRM</button>
 <button class="btn" onclick="showPage('criteria')">معیارها و وزن‌ها</button>
 <button class="btn" onclick="showPage('analysis-rules')">قواعد تحلیل</button>
 <button class="btn" onclick="showPage('expert-groups')">گروه‌بندی کارشناسان</button></div>
</section>`);
const evaluationMenu = document.querySelector('[data-module-menu="crm-quality"]');
evaluationMenu.insertAdjacentHTML('afterbegin', '<div class="nav-item" data-page="evaluation-settings">⚙️ تنظیمات ماژول ارزیابی</div>');
const sharedSettingsNav = document.createElement('div');
sharedSettingsNav.className = 'sidebar-shared-settings';
sharedSettingsNav.insertAdjacentHTML('beforeend', '<div class="nav-item" data-page="main-settings">⚙️ تنظیمات اصلی برنامه</div>');
document.getElementById('dataset-status').before(sharedSettingsNav);
const sharedAiNav = document.querySelector('.nav-item[data-page="ai-settings"]');
sharedSettingsNav.appendChild(sharedAiNav);
for (const id of ['crm-base-url', 'crm-organization', 'planning-url', 'planning-org', 'planning-api']) {
 const input = document.getElementById(id);
 if (input) { input.readOnly = true; input.title = 'از تنظیمات اصلی برنامه تغییر دهید'; }
}
async function loadMainSettings() {
 try {
  const result = await api().get_main_settings();
  if (!result.ok) throw new Error(result.error);
  document.getElementById('main-crm-url').value = result.crm.base_url;
  document.getElementById('main-crm-org').value = result.crm.organization;
  document.getElementById('main-crm-api').value = result.crm.api_version;
  document.getElementById('main-storage').textContent = result.storage_path;
  document.getElementById('main-default-module').value = result.default_module || 'crm-quality';
 } catch (error) { toast(error.message, 'error'); }
}
async function saveMainSettings() {
 try {
  const result = await api().save_main_settings({default_module: document.getElementById('main-default-module').value, crm: {
   base_url: document.getElementById('main-crm-url').value,
   organization: document.getElementById('main-crm-org').value,
   api_version: document.getElementById('main-crm-api').value}});
  if (!result.ok) throw new Error(result.error);
  toast(result.message, 'success');
  await loadCrmSettings(false); await loadPlanningSettings();
 } catch (error) { toast(error.message, 'error'); }
}
async function loadEvaluationSettings() {
 try { const result = await api().get_evaluation_module_settings();
  document.getElementById('evaluation-ai-enabled').checked = result.ai_enabled;
 } catch (error) { toast(error.message, 'error'); }
}
async function saveEvaluationSettings() {
 try { const result = await api().save_evaluation_module_settings({ai_enabled: document.getElementById('evaluation-ai-enabled').checked});
  if (!result.ok) throw new Error(result.error); toast('تنظیمات ارزیابی ذخیره شد.', 'success');
 } catch (error) { toast(error.message, 'error'); }
}
