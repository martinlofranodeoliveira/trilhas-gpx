"""O leitor distingue subida acumulada de altitude e vê tempo excluído."""
import unittest
from xml.etree import ElementTree as ET
from trilhas_gpx import GPX,Point,Segment,to_svg
class SVGLabels(unittest.TestCase):
    def test_summary_explicitly_labels_ascent_descent_and_time_coverage(self):
        model=GPX('fixture',(Segment(1,1,'',(Point(0,0,100),Point(0,.001,110))),),1)
        root=ET.fromstring(to_svg(model));summary=next(n for n in root.iter() if n.get('id')=='summary')
        text=' '.join(summary.itertext()).lower()
        for label in ['subida observada','descida','inválidas: 1','longas: 0']:
            self.assertIn(label,text)
