const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
function el(id) {
 if (!elements.has(id)) elements.set(id, {value: '', innerHTML: '', textContent: '', disabled: false,
  insertAdjacentHTML() {}, addEventListener() {}, replaceChildren() {this.innerHTML = '';}});
 return elements.get(id);
}
let data = {ok: true, loaded: true, snapshot_view: '<unsafe>', selected_view: 'view', fetched_at: '2026-10-14T10:00:00',
 counts: {cases: 30, notes: 30, tasks: 0}, rows: [{number: 'CASE', title: '<script>', status: '', notes: [{text: '<img>', date: '2026-10-14T09:00:00Z'}], tasks: []}],
 total: 30, page: 0, page_size: 25, view_mismatch: true};
let calls = [];
const context = vm.createContext({document: {getElementById: el}, Date, Number, String,
 api: () => ({get_module_cached_data: async (...args) => {calls.push(args); return data;}}),
 escapeHtml: text => text.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')});
vm.runInContext(fs.readFileSync('ui/cached-data.js', 'utf8'), context);
(async () => {
 await context.loadCachedInventory('crm-quality');
 assert.match(el('inventory-summary-crm-quality').innerHTML, /&lt;unsafe&gt;/);
 assert.match(el('inventory-rows-crm-quality').innerHTML, /&lt;img&gt;/);
 assert(!el('inventory-rows-crm-quality').innerHTML.includes('<script>'));
 assert.equal(el('inventory-prev-crm-quality').disabled, true);
 assert.equal(el('inventory-next-crm-quality').disabled, false);
 el('inventory-search-crm-quality').value = 'CASE';
 await context.changeInventoryPage('crm-quality', 1);
 assert.equal(calls.at(-1)[1], 1);
 assert.equal(calls.at(-1)[2], 'CASE');
 data = {ok: true, loaded: false, rows: [], total: 0, page: 0, page_size: 25};
 await context.loadCachedInventory('case-planning');
 assert.equal(el('inventory-next-case-planning').disabled, true);
 console.log('Cached inventory UI: passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
