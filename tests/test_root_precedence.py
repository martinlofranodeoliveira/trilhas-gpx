"""Regressões de precedência sem mudar os testes anteriores."""
import unittest
from trilhas_gpx import GPXError, parse_gpx

class RootPrecedence(unittest.TestCase):
    def test_malformed_unsupported_root_is_xml_invalid(self):
        with self.assertRaises(GPXError) as raised:parse_gpx(b'<EXEMPLO>')
        self.assertEqual(raised.exception.code,'XML_INVALID')
    def test_wellformed_unsupported_root_is_gpx_format(self):
        with self.assertRaises(GPXError) as raised:parse_gpx(b'<EXEMPLO/>')
        self.assertEqual(raised.exception.code,'GPX_FORMAT')
