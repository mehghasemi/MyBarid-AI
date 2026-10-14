from app_settings import MainSettingsMixin
from planning import PlanningApiMixin, source_key
from database import db


class LocalApi(MainSettingsMixin, PlanningApiMixin):
    def get_crm_settings(self):
        return {"base_url": "https://crm.test", "organization": "Main", "api_version": "v9.1", "view_name": "new-view"}


def test_local_inventory_isolated_paginated_and_restored(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'local.db')
    db.init_db()
    api = LocalApi()
    assert api.get_module_cached_data('crm-quality')['loaded'] is False
    selection = {'view_id': '00000000-0000-0000-0000-000000000001', 'view_kind': 'savedqueries', 'view_name': 'planning'}
    db.set_setting('planning_crm_settings', selection)
    rows = [{'note_id': str(i), 'case_number': f'CAS-{i:03}', 'case_title': f'عنوان {i}', 'description': 'متن یادداشت'} for i in range(30)]
    db.save_crm_snapshot('dynamics365', 'old-view', '2026-10-14T09:00:00', {'sync_mode': 'full'}, {'notes': rows, 'tasks': []})
    db.save_crm_snapshot(source_key({**api.get_crm_settings(), **selection}), 'planning', '2026-10-14T10:00:00',
                         {'changed': {'notes': 1, 'tasks': 0}}, {'notes': [{'note_id': 'p', 'case_number': 'PLANNING'}], 'tasks': []})
    restored = LocalApi().get_module_cached_data('crm-quality')
    assert restored['counts'] == {'cases': 30, 'notes': 30, 'tasks': 0}
    assert restored['view_mismatch'] is True
    assert len(restored['rows']) == 25
    assert restored['rows'][0]['notes'][0]['text'] == 'متن یادداشت'
    assert len(api.get_module_cached_data('crm-quality', 1)['rows']) == 5
    assert api.get_module_cached_data('crm-quality', 999)['page'] == 1
    assert api.get_module_cached_data('crm-quality', 0, 'CAS-029')['total'] == 1
    assert api.get_module_cached_data('case-planning')['rows'][0]['number'] == 'PLANNING'
    assert not api.get_module_cached_data('unknown')['ok']
    assert not api.get_module_cached_data('crm-quality', 'bad')['ok']


def test_default_module_persists_and_rejects_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'prefs.db')
    db.init_db()
    api = LocalApi()
    assert api.get_main_settings()['default_module'] == 'crm-quality'
    payload = {'crm': api.get_main_settings()['crm'], 'default_module': 'case-planning'}
    assert api.save_main_settings(payload)['ok']
    assert LocalApi().get_main_settings()['default_module'] == 'case-planning'
    assert api.save_main_settings({'crm': payload['crm']})['ok']
    assert api.get_main_settings()['default_module'] == 'case-planning'
    assert not api.save_main_settings({**payload, 'default_module': 'project-management'})['ok']
    assert api.get_main_settings()['default_module'] == 'case-planning'
