from app_settings import MainSettingsMixin, main_settings
from database import db


def test_migration_and_view_preservation(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'settings.db')
    db.init_db()
    old = {'base_url': 'https://old.test', 'organization': 'Main', 'api_version': 'v9.1', 'view_name': 'evaluation'}
    db.set_setting('crm_settings', old)
    db.set_setting('planning_crm_settings', {'view_name': 'planning'})
    assert main_settings()['crm']['base_url'] == 'https://old.test'
    api = MainSettingsMixin()
    assert api.save_main_settings({'crm': {'base_url': 'https://new.test/', 'organization': 'Main', 'api_version': 'v9.1'}})['ok']
    assert main_settings()['crm']['base_url'] == 'https://new.test'
    assert db.get_setting('crm_settings') == old
    assert db.get_setting('planning_crm_settings')['view_name'] == 'planning'
    assert api.get_evaluation_module_settings()['ai_enabled'] is True
    assert api.save_evaluation_module_settings({'ai_enabled': False})['ok']
    assert api.get_evaluation_module_settings()['ai_enabled'] is False
    assert not api.save_evaluation_module_settings({'ai_enabled': 'false'})['ok']
    assert not api.save_main_settings({'crm': {'base_url': 'https://user:pass@new.test'}})['ok']
