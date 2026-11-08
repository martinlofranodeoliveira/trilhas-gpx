"""Análise local e explícita de trilhas GPX 1.1."""
__version__ = "0.1.0"
from .core import GPX, GPXError, Point, Segment, analyze, parse_gpx, points_csv, to_geojson
from .svg import to_svg
__all__ = ["GPX", "GPXError", "Point", "Segment", "analyze", "parse_gpx", "points_csv", "to_geojson", "to_svg"]
