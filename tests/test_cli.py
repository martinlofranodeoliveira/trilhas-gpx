"""Exercita o executável instalado, nunca importa pelo checkout."""
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

XML = b'<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="EXEMPLO"><trk><trkseg><trkpt lat="0" lon="0"><ele>5</ele><time>2026-01-01T00:00:00Z</time></trkpt><trkpt lat="0" lon="0.001"><ele>8</ele><time>2026-01-01T00:01:00Z</time></trkpt></trkseg></trk></gpx>'

class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.exe = os.environ.get('TRILHAS_GPX_CLI', 'trilhas-gpx')
    def run_cli(self, *args, data=XML):
        return subprocess.run([self.exe, *map(str,args)], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.root, timeout=20)
    def error(self, result, code):
        self.assertEqual(result.returncode,2)
        self.assertEqual(result.stdout,b'')
        err=json.loads(result.stderr)
        self.assertEqual(err['error']['code'],code)
        self.assertNotIn('EXEMPLO',result.stderr.decode())
    def test_help(self):
        r=self.run_cli('--help'); self.assertEqual(r.returncode,0); self.assertIn(b'--format',r.stdout)
    def test_version(self):
        r=self.run_cli('--version'); self.assertEqual(r.returncode,0); self.assertIn(b'0.1.0',r.stdout)
    def test_json_stdin(self):
        r=self.run_cli('-','--format','json'); self.assertEqual(r.returncode,0,r.stderr)
        d=json.loads(r.stdout); self.assertEqual(d['source']['point_count'],2); self.assertAlmostEqual(d['totals']['ascent_m'],3)
    def test_real_input_output(self):
        source=self.root/'entrada.gpx';source.write_bytes(XML);out=self.root/'resultado.json'
        r=self.run_cli(source,'--format','json','--output',out);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout,b'')
        self.assertEqual(json.loads(out.read_text())['totals']['usable_time_s'],60);self.assertEqual(source.read_bytes(),XML)
    def test_summary(self):
        r=self.run_cli('-');self.assertEqual(r.returncode,0,r.stderr);self.assertIn('distância',r.stdout.decode().lower());self.assertIn('aproxima',r.stdout.decode().lower())
    def test_geojson(self):
        r=self.run_cli('-','--format','geojson');self.assertEqual(r.returncode,0,r.stderr);d=json.loads(r.stdout)
        self.assertEqual(d['features'][0]['geometry']['coordinates'],[[0.0,0.0,5.0],[0.001,0.0,8.0]])
    def test_csv(self):
        r=self.run_cli('-','--format','csv');self.assertEqual(r.returncode,0,r.stderr);rows=list(csv.reader(io.StringIO(r.stdout.decode())))
        self.assertEqual(len(rows),3);self.assertEqual(rows[1][:5],['1','1','1','0.0','0.0']);self.assertEqual(rows[1][6],'2026-01-01T00:00:00Z')
    def test_no_overwrite(self):
        out=self.root/'saida';out.write_bytes(b'nao apagar');self.error(self.run_cli('-','--output',out),'OUTPUT_EXISTS');self.assertEqual(out.read_bytes(),b'nao apagar')
    def test_output_symlink(self):
        original=self.root/'original';original.write_bytes(b'preservar');out=self.root/'atalho';out.symlink_to(original)
        self.error(self.run_cli('-','--output',out),'OUTPUT_EXISTS');self.assertEqual(original.read_bytes(),b'preservar');self.assertTrue(out.is_symlink())
    def test_output_dangling_symlink(self):
        out=self.root/'atalho';out.symlink_to(self.root/'ausente');self.error(self.run_cli('-','--output',out),'OUTPUT_EXISTS');self.assertTrue(out.is_symlink())
    def test_input_symlink(self):
        original=self.root/'original';original.write_bytes(XML);link=self.root/'link';link.symlink_to(original)
        self.error(self.run_cli(link),'IO_ERROR')
    def test_input_fifo(self):
        fifo=self.root/'fifo';os.mkfifo(fifo);self.error(self.run_cli(fifo),'IO_ERROR')
    def test_missing_input(self):
        self.error(self.run_cli(self.root/'EXEMPLO-ausente'),'IO_ERROR')
    def test_invalid_xml_leaves_no_output(self):
        out=self.root/'saida';self.error(self.run_cli('-','--output',out,data=b'<EXEMPLO>'),'XML_INVALID');self.assertFalse(out.exists());self.assertEqual(list(self.root.iterdir()),[])
    def test_missing_output_parent(self):
        self.error(self.run_cli('-','--output',self.root/'missing'/'out'),'IO_ERROR');self.assertEqual(list(self.root.iterdir()),[])
    def test_input_size(self):
        self.error(self.run_cli('-',data=b' '*((8<<20)+1)),'LIMIT_EXCEEDED')
    def test_invalid_numeric_option(self):
        self.error(self.run_cli('-','--max-gap-seconds','EXEMPLO'),'OPTION_INVALID')
    def test_invalid_bounds_options(self):
        for args in [('--max-gap-seconds','0'),('--moving-threshold-kmh','-1'),('--max-gap-seconds','NaN')]:
            with self.subTest(args=args):self.error(self.run_cli('-',*args),'OPTION_INVALID')
    def test_options_change_coverage(self):
        r=self.run_cli('-','--format','json','--max-gap-seconds','30');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout)['totals']['gap_time_edges'],1)
    def test_bad_format_is_sanitized(self):
        self.error(self.run_cli('-','--format','EXEMPLO'),'ARGUMENT_ERROR')

    def test_closed_stdout_pipe_is_json_error(self):
        read_fd,write_fd=os.pipe();os.close(read_fd)
        try:
            process=subprocess.Popen([self.exe,'-','--format','json'],stdin=subprocess.PIPE,stdout=write_fd,stderr=subprocess.PIPE,cwd=self.root)
        finally:os.close(write_fd)
        _,error=process.communicate(XML,timeout=20)
        self.assertEqual(process.returncode,2,error)
        self.assertEqual(json.loads(error)['error']['code'],'IO_ERROR')
        self.assertNotIn(b'Exception ignored',error)

    def test_stdout_device_failure_is_json_error(self):
        with open('/dev/full','wb') as full:
            process=subprocess.Popen([self.exe,'-','--format','json'],stdin=subprocess.PIPE,stdout=full,stderr=subprocess.PIPE,cwd=self.root)
            _,error=process.communicate(XML,timeout=20)
        self.assertEqual(process.returncode,2,error)
        self.assertEqual(json.loads(error)['error']['code'],'IO_ERROR')
        self.assertNotIn(b'Exception ignored',error)

if __name__=='__main__':unittest.main()
