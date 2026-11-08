"""Declarações perigosas são diferentes de texto literal inerte."""
import unittest
from trilhas_gpx import GPXError, parse_gpx
ROOT=b'<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="fixture">'
class DeclarationTests(unittest.TestCase):
    def test_standalone_entity_is_unsafe(self):
        with self.assertRaises(GPXError) as raised:parse_gpx(b'<!ENTITY item "texto">'+ROOT+b'</gpx>')
        self.assertEqual(raised.exception.code,'XML_UNSAFE')
    def test_entity_after_xml_declaration_is_unsafe(self):
        with self.assertRaises(GPXError) as raised:parse_gpx(b'<?xml version="1.0"?>\n<!ENTITY item "texto">'+ROOT+b'</gpx>')
        self.assertEqual(raised.exception.code,'XML_UNSAFE')
    def test_literal_comment_and_cdata_are_inert(self):
        g=parse_gpx(ROOT+b'<metadata><!-- <!ENTITY item "texto"> --><![CDATA[<!ENTITY item "texto">]]></metadata></gpx>')
        self.assertEqual(g.track_count,0)
    def test_entity_in_content_utf8_and_chunk_boundary_is_unsafe(self):
        # Padding lives in ignored attributes so the text4096 guard remains valid.
        padded=ROOT[:-1]+b' padding="'+b'x'*(65532-len(ROOT)-11)+b'">'
        for head in [ROOT,ROOT+'textoá'.encode('utf-8'),padded]:
            with self.subTest(length=len(head)):
                with self.assertRaises(GPXError) as raised:parse_gpx(head+b'<!ENTITY item "texto"></gpx>')
                self.assertEqual(raised.exception.code,'XML_UNSAFE')
