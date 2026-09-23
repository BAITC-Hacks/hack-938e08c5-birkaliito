import copy
import json
import unittest
from pathlib import Path
from contract import normalize_request, validate

class Contracts(unittest.TestCase):
    def test_snapshots(self):
        root=Path(__file__).resolve().parents[2]/'testdata/fixtures'
        for file,schema in json.loads((root/'manifest.json').read_text()).items():
            value=json.loads((root/file).read_text(encoding='utf-8'))
            with self.subTest(file=file):
                if schema.endswith('[]'):
                    for item in value: validate(schema[:-2],item)
                else: validate(schema,value)

    def test_normalization_and_defaults(self):
        q=normalize_request('ForecastRequest',dict(forecast_origin='2026-01-31T23:30:00+05:30',model_version='test'))
        self.assertEqual(q['forecast_origin'],'2026-01-31T18:00:00Z')
        self.assertEqual(q['horizon_hours'],48)
        self.assertEqual(q['turbine_ids'],[1,2])
        self.assertEqual(q['data_mode'],'real')
        for bad in ('2026-01-31T23:00:00+05:30','2026-01-31T18:00:00'):
            with self.assertRaises(Exception): normalize_request('ForecastRequest',dict(q,forecast_origin=bad))
        with self.assertRaises(Exception): normalize_request('ForecastRequest',dict(q,horizon_hours=None))

    def test_future_weather_and_missing_quantile(self):
        root=Path(__file__).resolve().parents[2]/'testdata/fixtures'
        result=json.loads((root/'success-result.fixture.json').read_text())
        bad=copy.deepcopy(result);bad['weather_runs'][0]['effective_available_at']='2026-02-02T00:00:00Z'
        with self.assertRaises(ValueError):validate('ForecastResult',bad)
        bad=copy.deepcopy(result);del bad['points'][0]['q10']
        with self.assertRaises(Exception):validate('ForecastResult',bad)

if __name__=='__main__':unittest.main()
