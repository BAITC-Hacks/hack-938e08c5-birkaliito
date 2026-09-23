"""Contract-only Python helper. Reads the canonical Go API schema; no ML dependencies."""
import copy
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

SPEC = json.loads((Path(__file__).resolve().parents[2] / 'api/openapi.yaml').read_text(encoding='utf-8'))
UTC = timezone.utc

def timestamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Timezone offset required')
    return dt.astimezone(UTC)

def validate(name, value):
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
              '$ref': f'#/components/schemas/{name}', 'components': SPEC['components']}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    def finite(v):
        if isinstance(v, float) and not math.isfinite(v): raise ValueError('Nonfinite number')
        if isinstance(v, dict):
            for item in v.values(): finite(item)
        elif isinstance(v, list):
            for item in v: finite(item)
    finite(value)
    if name in ('ForecastRequest', 'ReplayRequest'):
        origins = [value['forecast_origin']] if name == 'ForecastRequest' else value['origins']
        times = [timestamp(origin) for origin in origins]
        if len(times) != len(set(times)): raise ValueError('Duplicate normalized origins')
        if any(t.minute or t.second or t.microsecond for t in times): raise ValueError('Origin must align to whole UTC hour')
        if not value['model_version'].strip(): raise ValueError('Empty model_version')
    if name == 'ForecastResult':
        origin = timestamp(value['forecast_origin'])
        validate('ForecastRequest', {k:value[k] for k in ('forecast_origin','horizon_hours','turbine_ids','model_version','data_mode')})
        if timestamp(value['training_data_available_through']) > origin: raise ValueError('Future training data')
        for w in value['weather_runs']:
            if not timestamp(w['initialization_time']) <= timestamp(w['effective_available_at']) <= origin: raise ValueError('Future weather')
            if w['availability_basis'] == 'conservative_policy' and not w['availability_policy_id']: raise ValueError('Missing availability policy')
            if value['data_mode']=='real' and ('fixture' in w['source_reference'].lower() or w['run_id'].startswith('fixture')): raise ValueError('Fixture source in real result')
        expected={(t,h) for t in value['turbine_ids'] for h in range(1,value['horizon_hours']+1)}
        actual={(p['turbine_id'],p['lead_hours']) for p in value['points']}
        if actual!=expected or len(actual)!=len(value['points']): raise ValueError('Missing/duplicate point')
        for p in value['points']:
            if timestamp(p['valid_time']) != origin+timedelta(hours=p['lead_hours']): raise ValueError('Wrong valid_time')
            if timestamp(p['interval_end']) != timestamp(p['valid_time'])+timedelta(hours=1): raise ValueError('Wrong interval')
            if not p['q10']<=p['q50']<=p['q90']: raise ValueError('Crossed quantiles')
    return value

def normalize_request(name, value):
    validate(name,value)
    result=copy.deepcopy(value)
    for field,schema in SPEC['components']['schemas'][name]['properties'].items():
        if field not in result and 'default' in schema: result[field]=copy.deepcopy(schema['default'])
    def iso(v): return timestamp(v).isoformat().replace('+00:00','Z')
    if name=='ForecastRequest': result['forecast_origin']=iso(result['forecast_origin'])
    else: result['origins']=[iso(v) for v in result['origins']]
    result['turbine_ids'].sort()
    return result
