/* Offline interaction regression with synthetic DOM; not a browser QA claim. */
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {value: '', textContent: '', innerHTML: '', hidden: false,
    disabled: false, focus() { this.focused = true; }, closest() { return this; }});
  return elements.get(id);
}
element('management-state').value = 'all';
element('management-severity').value = 'all';
const sample = {ok: true, scope: 'نمونه آزمایشی', evaluation_at: '2026-10-12T00:00:00Z',
  attribution_notice: 'مالک فعلی', summary: {status_distribution: {}, resolution_eligible: 0, resolution_denominator: 1},
  catalog: [], severity_settings: {}, status_mapping: {}, thresholds: {}, actions: [],
  cases: [{case_key: 'CASE-1', customer: 'مشتری', owner: 'مالک', service: 'سرویس', criteria: [
    {id: 'x', name: 'معیار', value: 2, threshold: 1, status: 'needs_correction', severity: 'critical', evidence: ['شاهد']},
    {id: 'y', name: 'داده ناقص', value: null, threshold: null, status: 'insufficient_data', severity: 'info', evidence: []}]}]};
let response = sample;
let historyCalls = 0;
const context = vm.createContext({document: {getElementById: element, querySelectorAll: () => []},
  window: {pywebview: true}, console, Date, Number, Set, JSON,
  api: () => ({get_management_evaluation: async () => response,
    retrieve_crm_case_history: async () => { historyCalls++; return {ok: true, message: 'ذخیره شد'}; }}),
  escapeHtml: value => String(value ?? '').replaceAll('<', '&lt;').replaceAll('>', '&gt;'), toast() {}});
vm.runInContext(fs.readFileSync('ui/management.js', 'utf8'), context);
(async () => {
  await context.loadManagementEvaluation();
  assert.match(element('management-rows').innerHTML, /بحرانی/);
  element('management-state').value = 'insufficient_data';
  context.renderManagementRows();
  assert.doesNotMatch(element('management-rows').innerHTML, /بحرانی/);
  assert.match(element('management-rows').innerHTML, /داده ناقص/);
  context.prepareManagementAction({dataset: {actionCase: 'CASE-1', actionCriterion: 'x'}});
  assert.equal(element('action-case').value, 'CASE-1');
  assert.equal(element('action-criterion').value, 'x');
  await context.retrieveSelectedHistory();
  assert.equal(historyCalls, 1);
  assert.equal(element('management-history-button').disabled, false);
  response = {ok: false, error: 'ارزیابی موجود نیست'};
  await context.loadManagementEvaluation();
  assert.equal(element('management-rows').innerHTML, '');
  assert.equal(element('management-actions').innerHTML, '');
  console.log('Management UI interactions: passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
