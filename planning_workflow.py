"""Phase-one planning workflow. No AI, ranking or CRM mutations."""
import hashlib
import json
import getpass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4
from urllib.parse import urlencode
from database import db
from planning import source_key
from planning_crm import guid
from planning_store import read_records, save, audit

STATES = {'unassigned', 'blocked', 'scheduled', 'executed_waiting', 'settled'}
ACTIONS = {'upgrade', 'technical', 'training', 'decision', 'unknown'}
OUTCOMES = {'pending', 'confirmed', 'continue', 'excluded'}


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def date_field(value):
    if not value:
        return None
    parsed = parse_time(value)
    if parsed is None:
        raise ValueError('زمان باید معتبر و دارای منطقه زمانی باشد.')
    return parsed.isoformat()


def connection_scope(settings):
    return hashlib.sha256(json.dumps({key: settings.get(key) for key in ('base_url', 'organization', 'api_version')}, sort_keys=True).encode()).hexdigest()


def actor_identity(actor):
    if actor:
        if actor.get('role') not in {'admin', 'analyst'}:
            raise PermissionError('کاربر مشاهده‌گر فقط دسترسی خواندن دارد.')
        return {key: actor.get(key) for key in ('username', 'display_name', 'role')}
    try:
        name = getpass.getuser()
        return {'username': name, 'origin': 'local_os'} if name else None
    except (OSError, KeyError):
        return None


def crm_link(settings, identifier, entity='incident'):
    identifier = guid(identifier)
    if not identifier:
        return None
    return settings['base_url'].rstrip('/') + '/' + settings['organization'].strip('/') + '/main.aspx?' + urlencode({'etn': entity, 'pagetype': 'entityrecord', 'id': identifier})


def inventory(api):
    settings = api.get_planning_settings()
    scope = connection_scope(settings)
    snapshot = db.get_latest_crm_snapshot(source_key(settings)) if settings.get('view_id') else None
    payload = (snapshot or {}).get('payload') or {}
    context = payload.get('planning_crm') or {}
    cases = dict(context.get('cases') or {})
    # Legacy data stays visible; never infer a program from customer/title.
    for note in payload.get('notes', []) + payload.get('tasks', []):
        identifier = guid(note.get('case_id'))
        key = identifier or 'unidentified:' + str(note.get('case_number') or note.get('case_title') or note.get('note_id') or note.get('task_id'))
        if key not in cases:
            cases[key] = {'id': identifier, 'key': key, 'number': note.get('case_number'),
                'title': note.get('case_title') or note.get('regarding'), 'customer': note.get('customer'),
                'program_id': None, 'status': note.get('case_status'), 'identity_missing': not bool(identifier)}
    for key, case in cases.items():
        case['key'] = key
        case['crm_url'] = crm_link(settings, case.get('id'))
    records = read_records(scope)
    locals_by_id = {row['id']: row for row in records if row['_kind'] == 'program'}
    programs = {}
    for key, case in cases.items():
        parent = guid(case.get('program_id'))
        if not parent:
            continue
        program_id = 'crm:' + parent
        base = (context.get('programs') or {}).get(parent) or {}
        program = programs.setdefault(program_id, {'id': program_id, 'crm_id': parent, 'title': base.get('title') or 'اطلاعات برنامه مادر ناکافی است',
            'customer': base.get('customer') or case.get('customer') or 'نامشخص', 'customer_id': base.get('customer_id'),
            'crm_status': base.get('status'), 'crm_state': base.get('state'), 'case_ids': [], 'origin': 'crm',
            'parent_missing': not bool(base), 'crm_url': crm_link(settings, parent)})
        program['case_ids'].append(key)
    # Retain local decisions even if a View/relation changes. Never auto-delete.
    for identifier, local in locals_by_id.items():
        if identifier not in programs:
            programs[identifier] = {'id': identifier, 'case_ids': local.get('case_ids', []), 'origin': 'local' if identifier.startswith('local:') else 'crm',
                                    'outside_current_scope': identifier.startswith('crm:')}
        program = programs[identifier]
        current_ids = list(program['case_ids'])
        if program['origin'] == 'local':
            current_ids = local.get('case_ids', [])
        program['relation_changed'] = program['origin'] == 'crm' and set(local.get('case_ids', [])) != set(current_ids)
        program['local'] = {key: value for key, value in local.items() if key != '_kind'}
        for key in ('title', 'customer', 'customer_id'):
            if program['origin'] == 'local':
                program[key] = local.get(key) or 'نامشخص'
        program['case_ids'] = list(dict.fromkeys(current_ids + local.get('case_ids', [])))
    linked = set()
    for program in programs.values():
        program.setdefault('local', {})
        program['revision'] = program['local'].get('revision', 0)
        program['state'] = program['local'].get('state', 'unassigned')
        program['followups'] = [row for row in records if row['_kind'] == 'followup' and row['program_id'] == program['id']]
        program['results'] = {row['case_id']: row for row in records if row['_kind'] == 'case_result' and row['program_id'] == program['id']}
        program['cases'] = [{**cases.get(key, {'id': key, 'key': key, 'title': 'اطلاعات قدیمی / خارج از محدوده جاری'}),
                             'result': program['results'].get(key)} for key in program['case_ids']]
        program['last_synced'] = (snapshot or {}).get('fetched_at')
        linked.update(program['case_ids'])
    return settings, scope, snapshot, context, cases, programs, [case for key, case in cases.items() if key not in linked]


def reasons(program, evaluated):
    local = program['local']
    found = []
    def add(kind, label, evidence):
        found.append({'kind': kind, 'label': label, 'evidence': evidence})
    if program['state'] != 'settled':
        missing = [label for field, label in (('next_step', 'قدم بعدی'), ('next_owner', 'مسئول قدم بعدی'), ('next_due', 'موعد معتبر')) if not local.get(field) or field == 'next_due' and not parse_time(local.get(field))]
        if missing:
            add('insufficient', 'اطلاعات ناکافی', 'ثبت نشده: ' + '، '.join(missing))
    if program.get('parent_missing'):
        add('insufficient', 'اطلاعات ناکافی برنامه مادر', 'شناسه رابطه موجود است اما اطلاعات برنامه مادر در Snapshot نیست.')
    if program.get('outside_current_scope') or program.get('relation_changed'):
        add('review', 'نیازمند بازبینی رابطه', 'تصمیم قبلی حفظ شده؛ رابطه یا محدوده داده فعلی با زمان ثبت تصمیم یکسان نیست. این به معنی حذف از CRM نیست.')
    for followup in program['followups']:
        due = parse_time(followup.get('due'))
        if followup.get('state') == 'open' and due and due < evaluated:
            add('overdue', 'پیگیری عقب‌افتاده و انجام‌نشده', f"{followup.get('title', '')}؛ موعد ثبت‌شده: {followup['due']}")
    announced = local.get('execution_announced') or program['state'] == 'executed_waiting'
    if announced and not execution_confirmed(program):
        add('insufficient', 'نتیجه اجرا نیازمند تأیید است', 'برای همه کیس‌های مشمول، نتیجه مستند و تأیید لازم ثبت نشده است؛ Done در CRM جای تأیید را نمی‌گیرد.')
    if program['state'] == 'settled' and any(str(case.get('state')) == '0' for case in program['cases']):
        add('review', 'نیازمند بازبینی وضعیت کیس', 'برنامه محلی تعیین‌تکلیف‌شده است اما حداقل یک کیس با statecode=0 باز است؛ خطای قطعی نیست.')
    customers = {case.get('customer_id') for case in program['cases'] if case.get('customer_id')}
    if len(customers) > 1:
        add('review', 'نیازمند بازبینی رابطه مشتری', 'کیس‌های مرتبط بیش از یک شناسه مشتری CRM دارند.')
    return found


def execution_confirmed(program):
    if not program['cases']:
        return False
    for case in program['cases']:
        result = case.get('result') or {}
        if result.get('outcome') == 'excluded':
            if not result.get('reason'):
                return False
        elif result.get('outcome') not in {'confirmed', 'continue'} or not result.get('evidence') or not parse_time(result.get('confirmed_at')):
            return False
    return True


def metrics(programs, evaluated):
    opened = [program for program in programs if program['state'] != 'settled']
    covered = sum(bool(p['local'].get('next_step') and p['local'].get('next_owner') and parse_time(p['local'].get('next_due'))) for p in opened)
    due_followups = [f for p in programs for f in p['followups'] if f.get('state') != 'cancelled' and parse_time(f.get('original_due')) and parse_time(f['original_due']) <= evaluated]
    timely = sum(f.get('state') == 'done' and parse_time(f.get('completed_at')) is not None and parse_time(f['completed_at']) <= parse_time(f['original_due']) for f in due_followups)
    announced = [p for p in programs if p['local'].get('execution_announced') or p['state'] == 'executed_waiting']
    def ratio(name, numerator, denominator, incomplete):
        return {'name': name, 'numerator': numerator, 'denominator': denominator, 'percent': numerator * 100 / denominator if denominator else None, 'incomplete': incomplete}
    return [ratio('پوشش قدم بعدی', covered, len(opened), len(opened) - covered),
            ratio('پیگیری به‌موقع', timely, len(due_followups), sum(f.get('state') == 'done' and not parse_time(f.get('completed_at')) for f in due_followups)),
            ratio('تأیید نتیجه اجرا', sum(execution_confirmed(p) for p in announced), len(announced), sum(not execution_confirmed(p) for p in announced))]


class PlanningWorkflowMixin:
    def get_planning_workflow(self, filters=None, evaluation_at=None):
        try:
            evaluated = parse_time(evaluation_at) if evaluation_at else datetime.now(timezone.utc)
            if evaluated is None:
                raise ValueError('زمان ارزیابی معتبر نیست.')
            filters = filters or {}
            settings, scope, snapshot, context, cases, programs, unlinked = inventory(self)
            selected = []
            today = evaluated.astimezone(ZoneInfo('Asia/Tehran')).date()
            for program in programs.values():
                local = program['local']
                if any(filters.get(key) and str(filters[key]).casefold() not in str(value or '').casefold() for key, value in
                       (('customer', program.get('customer')), ('owner', ' '.join(str(local.get(k) or '') for k in ('coordinator', 'executor', 'next_owner', 'blocker_owner'))),
                        ('action_type', local.get('action_type', 'unknown')), ('blocker', local.get('blocker', 'unknown')))):
                    continue
                program['reasons'] = reasons(program, evaluated)
                schedule = parse_time(local.get('scheduled_at'))
                program['today_reasons'] = []
                for followup in program['followups']:
                    due = parse_time(followup.get('due'))
                    if followup.get('state') == 'open' and due and due.astimezone(ZoneInfo('Asia/Tehran')).date() <= today:
                        program['today_reasons'].append('پیگیری امروز' if due.astimezone(ZoneInfo('Asia/Tehran')).date() == today else 'پیگیری عقب‌افتاده')
                if schedule and schedule.astimezone(ZoneInfo('Asia/Tehran')).date() == today:
                    program['today_reasons'].append('اجرای برنامه‌ریزی‌شده امروز')
                if local.get('manager_decision'):
                    program['today_reasons'].append('صریحاً نیازمند تصمیم مدیر')
                due = parse_time(local.get('next_due'))
                if program['state'] != 'settled' and due and due.astimezone(ZoneInfo('Asia/Tehran')).date() <= today:
                    program['today_reasons'].append('قدم بعدی امروز یا عقب‌افتاده')
                program['today_reasons'] = list(dict.fromkeys(program['today_reasons']))
                selected.append(program)
            def ordering(program):
                deadlines = [f.get('due') for f in program['followups'] if f.get('state') == 'open'] + [program['local'].get('next_due'), program['local'].get('scheduled_at')]
                values = [parse_time(value) for value in deadlines if parse_time(value)]
                return (min(values).isoformat() if values else '9999', -int(program['local'].get('priority', 0)), program['id'])
            selected.sort(key=ordering)
            visible_unlinked = [case for case in unlinked if not filters.get('customer') or str(filters['customer']).casefold() in str(case.get('customer') or '').casefold()]
            if any(filters.get(k) for k in ('owner', 'action_type', 'blocker')):
                visible_unlinked = []
            return {'ok': True, 'programs': selected, 'unlinked': visible_unlinked, 'evaluation_at': evaluated.isoformat(),
                'scope': settings.get('view_name') or 'بدون View', 'snapshot_at': (snapshot or {}).get('fetched_at'),
                'relation_verified': context.get('relation_verified', False), 'scope_checked': context.get('scope_checked', False),
                'metrics': metrics(selected, evaluated), 'limitations': 'دریافت افزایشی حذف یا خروج از View را ثابت نمی‌کند؛ داده قدیمی ممکن است باقی مانده باشد. نبود یادداشت جدید اثبات نبود فعالیت نیست.',
                'due_policy': 'موعد مبنا نخستین موعد معتبر ثبت‌شده است و تغییر بعدی آن را عوض نمی‌کند. زمان انجام نامعلوم فرض نمی‌شود.'}
        except (ValueError, TypeError) as exc:
            return {'ok': False, 'error': str(exc)}

    def get_planning_program_detail(self, program_id):
        settings, scope, snapshot, context, cases, programs, unlinked = inventory(self)
        program = programs.get(program_id)
        if not program:
            return {'ok': False, 'error': 'برنامه در محدوده فعلی یافت نشد.'}
        linked_ids = set(program['case_ids']) | {program.get('crm_id')}
        events = [event for event in (context.get('events') or {}).values() if event.get('case_id') in linked_ids]
        payload = (snapshot or {}).get('payload') or {}
        for kind in ('notes', 'tasks'):
            for row in payload.get(kind, []):
                if row.get('case_id') in linked_ids:
                    events.append({'id': row.get('note_id') or row.get('task_id'), 'case_id': row.get('case_id'),
                        'entity': 'annotation' if kind == 'notes' else 'task', 'title': row.get('subject'),
                        'text': row.get('description'), 'created_on': row.get('note_date') or row.get('created_on')})
        program = dict(program)
        program['events'] = [{**event, 'crm_url': crm_link(settings, event.get('id'), event['entity']),
                              'source_level': 'برنامه مادر' if event.get('case_id') == program.get('crm_id') else 'کیس فرزند'} for event in events]
        program['history'] = audit(scope, program_id)
        return {'ok': True, 'program': program}

    def save_planning_program(self, payload, *, _actor=None):
        try:
            actor = actor_identity(_actor)
            settings, scope, snapshot, context, cases, programs, unlinked = inventory(self)
            identifier = payload.get('id') or 'local:' + str(uuid4())
            existing = programs.get(identifier)
            if identifier.startswith('crm:') and not existing:
                raise ValueError('رابطه برنامه CRM معتبر نیست.')
            if not identifier.startswith(('local:', 'crm:')) or not guid(identifier.split(':', 1)[1]):
                raise ValueError('شناسه برنامه معتبر نیست.')
            case_ids = list(dict.fromkeys(payload.get('case_ids', [])))
            if existing and existing.get('origin') == 'crm':
                case_ids = existing['case_ids']
            elif not case_ids or any(key not in cases or not guid(key) for key in case_ids):
                raise ValueError('حداقل یک کیس دارای شناسه معتبر CRM انتخاب کنید.')
            customer_ids = {cases[key].get('customer_id') for key in case_ids if key in cases and cases[key].get('customer_id')}
            if len(customer_ids) > 1:
                raise ValueError('یک برنامه محلی نمی‌تواند کیس‌های چند مشتری متفاوت را پوشش دهد.')
            document = dict((existing or {}).get('local') or {})
            for field in ('title', 'customer', 'action', 'expected_result', 'coordinator', 'executor', 'blocker', 'blocker_detail', 'blocker_owner', 'next_step', 'next_owner', 'execution_result', 'execution_evidence'):
                document[field] = str(payload.get(field, document.get(field, '')) or '').strip()
            document.update(id=identifier, program_id=identifier, case_ids=case_ids,
                customer_id=next(iter(customer_ids), document.get('customer_id')), state=payload.get('state', document.get('state', 'unassigned')),
                action_type=payload.get('action_type', document.get('action_type', 'unknown')))
            if document['state'] not in STATES or document['action_type'] not in ACTIONS:
                raise ValueError('وضعیت یا نوع اقدام معتبر نیست.')
            for field in ('next_due', 'scheduled_at', 'executed_at'):
                document[field] = date_field(payload.get(field, document.get(field)))
            if parse_time(document.get('executed_at')) and parse_time(document['executed_at']) > datetime.now(timezone.utc):
                raise ValueError('زمان اجرای واقعی نمی‌تواند آینده باشد.')
            document['manager_decision'] = bool(payload.get('manager_decision', False))
            document['execution_announced'] = bool(payload.get('execution_announced', False)) or document['state'] == 'executed_waiting'
            document['priority'] = int(payload.get('priority', 0))
            if document['priority'] not in range(4):
                raise ValueError('اولویت باید بین صفر و سه باشد.')
            if not document['title'] and identifier.startswith('local:'):
                raise ValueError('عنوان برنامه محلی لازم است.')
            document.pop('_kind', None)
            document.pop('revision', None)
            result = save(scope, 'program', document, payload.get('revision', 0), actor)
            return {'ok': True, 'record': result}
        except (ValueError, TypeError, PermissionError) as exc:
            return {'ok': False, 'error': str(exc)}

    def save_planning_followup(self, payload, *, _actor=None):
        try:
            actor = actor_identity(_actor)
            settings, scope, snapshot, context, cases, programs, unlinked = inventory(self)
            program = programs.get(payload.get('program_id'))
            if not program:
                raise ValueError('برنامه معتبر نیست.')
            document = {key: str(payload.get(key) or '').strip() for key in ('title', 'owner', 'result', 'evidence')}
            document.update(id=payload.get('id') or str(uuid4()), program_id=program['id'], state=payload.get('state', 'open'))
            if document['state'] not in {'open', 'done', 'cancelled'} or not document['title']:
                raise ValueError('عنوان و وضعیت پیگیری معتبر لازم است.')
            if document['state'] in {'done', 'cancelled'} and not document['result']:
                raise ValueError('برای انجام یا لغو پیگیری، توضیح نتیجه لازم است.')
            document['due'] = date_field(payload.get('due'))
            document['completed_at'] = date_field(payload.get('completed_at')) if document['state'] == 'done' else None
            if document['state'] == 'done' and (not document['completed_at'] or parse_time(document['completed_at']) > datetime.now(timezone.utc)):
                raise ValueError('زمان واقعی انجام معتبر و غیرآینده لازم است؛ زمان فرضی ثبت نمی‌شود.')
            old = next((f for f in program['followups'] if f['id'] == document['id']), None)
            if old and old['program_id'] != document['program_id']:
                raise ValueError('انتقال پیگیری مجاز نیست.')
            result = save(scope, 'followup', document, payload.get('revision', 0), actor)
            return {'ok': True, 'record': result}
        except (ValueError, TypeError, PermissionError) as exc:
            return {'ok': False, 'error': str(exc)}

    def save_planning_case_result(self, payload, *, _actor=None):
        try:
            actor = actor_identity(_actor)
            settings, scope, snapshot, context, cases, programs, unlinked = inventory(self)
            program = programs.get(payload.get('program_id'))
            if not program or payload.get('case_id') not in program['case_ids']:
                raise ValueError('کیس متعلق به برنامه انتخابی نیست.')
            outcome = payload.get('outcome', 'pending')
            if outcome not in OUTCOMES:
                raise ValueError('نتیجه معتبر نیست.')
            reason, evidence = str(payload.get('reason') or '').strip(), str(payload.get('evidence') or '').strip()
            confirmed_at = date_field(payload.get('confirmed_at'))
            if outcome != 'pending' and not reason:
                raise ValueError('توضیح نتیجه مستقل کیس لازم است.')
            if outcome in {'confirmed', 'continue'} and (not evidence or not confirmed_at or parse_time(confirmed_at) > datetime.now(timezone.utc)):
                raise ValueError('شاهد و زمان تأیید معتبر و غیرآینده لازم است.')
            document = {'id': program['id'] + ':' + payload['case_id'], 'program_id': program['id'], 'case_id': payload['case_id'],
                        'outcome': outcome, 'reason': reason, 'evidence': evidence, 'confirmed_at': confirmed_at}
            return {'ok': True, 'record': save(scope, 'case_result', document, payload.get('revision', 0), actor)}
        except (ValueError, TypeError, PermissionError) as exc:
            return {'ok': False, 'error': str(exc)}
