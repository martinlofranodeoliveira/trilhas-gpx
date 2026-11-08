"""Exemplos da documentação conferidos pela CLI instalada e oráculo analítico."""
import json,math,os,subprocess,unittest
from pathlib import Path
class ExampleTest(unittest.TestCase):
    def test_documented_fictitious_example(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([os.environ.get('TRILHAS_GPX_CLI','trilhas-gpx'),str(root/'examples/percurso-ficticio.gpx'),'--format','json'],capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        actual=json.loads(result.stdout);published=json.loads((root/'examples/resultado.json').read_text())
        self.assertEqual(actual['source'],published['source'])
        t=actual['totals'];self.assertAlmostEqual(t['distance_m'],6371008.8*math.pi/180*0.003,places=6)
        self.assertEqual(t['usable_time_s'],120);self.assertEqual(t['gap_time_edges'],1)
        self.assertEqual(t['elapsed_span_s'],4200);self.assertEqual(t['ascent_m'],10);self.assertEqual(t['descent_m'],5)
        self.assertEqual(t['elevation_edges'],2);self.assertEqual(t['missing_elevation_edges'],1)
        self.assertAlmostEqual(t['distance_m'],published['totals']['distance_m'],places=6)
