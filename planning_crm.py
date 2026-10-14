"""Read-only, schema-checked CRM planning context using the existing client."""
from urllib.parse import quote
from uuid import UUID
from xml.etree import ElementTree as ET
from crm_client import _powershell_get_json, _paged_values, _row_guid, _display, _value


def guid(value):
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def prepare_view(client, fetchxml):
    schema = _paged_values(f"{client.api_root}/EntityDefinitions(LogicalName='incident')/Attributes?$select=LogicalName,AttributeType",
                           client.username, client.password)
    attributes = {row.get('LogicalName'): row.get('AttributeType') for row in schema}
    relation = None
    if attributes.get('brd_plannedcase') == 'Lookup':
        lookup = _powershell_get_json(f"{client.api_root}/EntityDefinitions(LogicalName='incident')/Attributes(LogicalName='brd_plannedcase')/Microsoft.Dynamics.CRM.LookupAttributeMetadata?$select=LogicalName,Targets",
                                      client.username, client.password)
        if 'incident' in (lookup.get('Targets') or []):
            relation = 'brd_plannedcase'
    root = ET.fromstring(fetchxml)
    entity = root.find('./entity')
    if entity.get('name') == 'incident':
        target = entity
    else:
        target = entity.find("./link-entity[@name='incident']")
    if target is not None:
        present = {a.get('name') for a in target.findall('attribute')}
        for name in ('incidentid', 'title', 'ticketnumber', 'statecode', 'statuscode', 'modifiedon', 'customerid', 'brd_account', relation):
            if name and name in attributes and name not in present:
                ET.SubElement(target, 'attribute', {'name': name})
    return ET.tostring(root, encoding='unicode'), relation


def normalize_case(row, relation):
    identifier = _row_guid(row, 'ac.incidentid', 'incidentid', '_objectid_value', 'objectid')
    if not identifier:
        return None
    parent = _row_guid(row, 'ac.brd_plannedcase', '_brd_plannedcase_value', 'brd_plannedcase') if relation else None
    return {'id': identifier, 'number': _value(row, 'ac.ticketnumber', 'ticketnumber'),
            'title': _value(row, 'ac.title', 'title'),
            'customer_id': _row_guid(row, 'ac.brd_account', '_brd_account_value', 'ac.customerid', '_customerid_value'),
            'customer': _display(row, 'ac.brd_account', '_brd_account_value', 'ac.customerid', '_customerid_value'),
            'state': _value(row, 'ac.statecode', 'statecode'), 'status': _display(row, 'ac.statuscode', 'statuscode'),
            'state_label': _display(row, 'ac.statecode', 'statecode'), 'program_id': parent,
            'relation_field': relation, 'modified_on': _value(row, 'ac.modifiedon', 'modifiedon')}


def records_by_ids(client, ids, entity, since=None):
    result = []
    ids = sorted(set(filter(None, (guid(value) for value in ids))))
    for offset in range(0, len(ids), 100):
        root = ET.Element('fetch')
        table = ET.SubElement(root, 'entity', {'name': entity})
        ET.SubElement(table, 'all-attributes')
        filters = ET.SubElement(table, 'filter', {'type': 'and'})
        condition = ET.SubElement(filters, 'condition', {'attribute': 'incidentid' if entity == 'incident' else 'objectid' if entity == 'annotation' else 'regardingobjectid', 'operator': 'in'})
        for identifier in ids[offset:offset + 100]:
            ET.SubElement(condition, 'value').text = identifier
        if since:
            ET.SubElement(filters, 'condition', {'attribute': 'modifiedon', 'operator': 'gt', 'value': since.strftime('%Y-%m-%dT%H:%M:%SZ')})
        entity_set = {'incident': 'incidents', 'annotation': 'annotations', 'task': 'tasks'}[entity]
        result.extend(_paged_values(f"{client.api_root}/{entity_set}?fetchXml={quote(ET.tostring(root, encoding='unicode'), safe='')}", client.username, client.password))
    return result


def build_context(client, rows, notes, tasks, relation, previous, since, progress):
    cases = {record['id']: record for row in rows if (record := normalize_case(row, relation))}
    # On Note views, include linked incidents even if the View omits incident attributes.
    missing = {note.case_id for note in notes if note.case_id and note.case_id not in cases}
    for row in records_by_ids(client, missing, 'incident'):
        record = normalize_case(row, relation)
        if record:
            cases[record['id']] = record
    known = dict((previous or {}).get('cases') or {})
    known.update(cases)
    parent_ids = {record['program_id'] for record in known.values() if record.get('program_id')}
    previous_parents = (previous or {}).get('programs') or {}
    new_ids = parent_ids - set(previous_parents)
    progress('دریافت اطلاعات برنامه‌های مادر و شواهد مرتبط', 0, 0, 'رابطه واقعی CRM؛ بدون ادغام عنوانی')
    parents = records_by_ids(client, new_ids, 'incident') + records_by_ids(client, parent_ids - new_ids, 'incident', since)
    programs = {record['id']: record for row in parents if (record := normalize_case(row, relation))}
    events = {}
    for ids, watermark in ((new_ids, None), (parent_ids - new_ids, since)):
        for entity in ('annotation', 'task'):
            for row in records_by_ids(client, ids, entity, watermark):
                identifier = _row_guid(row, 'annotationid', 'activityid')
                parent = _row_guid(row, '_objectid_value', 'objectid', '_regardingobjectid_value', 'regardingobjectid')
                if identifier and parent:
                    events[identifier] = {'id': identifier, 'case_id': parent, 'entity': entity,
                        'title': _value(row, 'subject'), 'text': _value(row, 'notetext', 'description'),
                        'created_on': _value(row, 'createdon'), 'modified_on': _value(row, 'modifiedon')}
    return {'cases': cases, 'programs': programs, 'events': events, 'relation_field': relation,
            'relation_verified': bool(relation), 'scope_complete': not bool(since)}
