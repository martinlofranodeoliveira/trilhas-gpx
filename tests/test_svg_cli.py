"""Integração SVG na CLI instalada e no protocolo exclusivo de publicação."""
import json,os,subprocess,tempfile,unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from trilhas_gpx import parse_gpx,to_svg
XML=b'<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="texto-nao-publicar"><trk><name>nome-nao-publicar</name><trkseg><trkpt lat="0" lon="179"><ele>100</ele></trkpt><trkpt lat="0" lon="-179"><ele>120</ele></trkpt></trkseg></trk></gpx>'
class SVGCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.exe=os.environ.get('TRILHAS_GPX_CLI','trilhas-gpx')
    def run_cli(self,*args,data=XML):
        return subprocess.run([self.exe,'-','--format','svg',*map(str,args)],input=data,capture_output=True,cwd=self.root,timeout=20)
    def test_installed_svg_stdout_matches_api(self):
        result=self.run_cli();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.decode(),to_svg(parse_gpx(XML)))
        self.assertEqual(ET.fromstring(result.stdout).tag,'{http://www.w3.org/2000/svg}svg')
        self.assertNotIn(b'texto-nao-publicar',result.stdout);self.assertNotIn(b'nome-nao-publicar',result.stdout)
    def test_installed_svg_exclusive_complete_output(self):
        out=self.root/'relatorio.svg';result=self.run_cli('--output',out)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout,b'')
        original=out.read_bytes();self.assertEqual(original.decode(),to_svg(parse_gpx(XML)))
        result=self.run_cli('--output',out);self.assertEqual(result.returncode,2)
        self.assertEqual(json.loads(result.stderr)['error']['code'],'OUTPUT_EXISTS');self.assertEqual(out.read_bytes(),original)
    def test_svg_keeps_symlink_destination(self):
        target=self.root/'target';target.write_bytes(b'preservado');link=self.root/'link.svg';link.symlink_to(target)
        result=self.run_cli('--output',link);self.assertEqual(result.returncode,2)
        self.assertEqual(json.loads(result.stderr)['error']['code'],'OUTPUT_EXISTS');self.assertEqual(target.read_bytes(),b'preservado')
    def test_invalid_svg_input_leaves_no_output(self):
        out=self.root/'relatorio.svg';result=self.run_cli('--output',out,data=b'<invalid>')
        self.assertEqual(result.returncode,2);self.assertEqual(json.loads(result.stderr)['error']['code'],'XML_INVALID')
        self.assertEqual(result.stdout,b'');self.assertFalse(out.exists());self.assertEqual(list(self.root.iterdir()),[])
    def test_svg_invalid_option_is_sanitized(self):
        result=self.run_cli('--moving-threshold-kmh','NaN');self.assertEqual(result.returncode,2)
        self.assertEqual(json.loads(result.stderr)['error']['code'],'OPTION_INVALID');self.assertEqual(result.stdout,b'')
    def test_svg_empty_book_is_explicit(self):
        result=self.run_cli(data=b'<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="fixture"/>')
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('Sem pontos de trilha',result.stdout.decode())
