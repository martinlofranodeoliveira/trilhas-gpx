"""Casos públicos originais, sintéticos e sem arquivos GPS externos."""

import csv
import dataclasses
import io
import json
import math
import unittest
from datetime import datetime, timedelta, timezone, tzinfo

from trilhas_gpx.core import GPX, GPXError, Point, Segment, analyze, parse_gpx, points_csv, to_geojson


NS = "http://www.topografix.com/GPX/1/1"
RADIUS = 6371008.8
UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)
STAT_KEYS = {
    "point_count", "edge_count", "distance_m", "ascent_m", "descent_m", "elevation_edges",
    "missing_elevation_edges", "usable_time_edges", "invalid_time_edges", "gap_time_edges",
    "usable_time_s", "usable_distance_m", "moving_time_s", "moving_distance_m",
    "average_speed_kmh", "moving_speed_kmh", "start_time", "end_time", "elapsed_span_s", "bounds",
}


def xml(inner="", *, creator="Exemplos fictícios", extra=""):
    return f'<gpx xmlns="{NS}" version="1.1" creator="{creator}" {extra}>{inner}</gpx>'.encode("utf-8")


def trk(points="", *, name="", segments=None):
    body = f"<trkseg>{points}</trkseg>" if segments is None else segments
    return f"<trk>{name}{body}</trk>"


def pt(lat="0", lon="0", fields=""):
    return f'<trkpt lat="{lat}" lon="{lon}">{fields}</trkpt>'


def model(*segments):
    return GPX("Exemplo manual fictício", tuple(Segment(1, i, "", tuple(points)) for i, points in enumerate(segments, 1)), 1)


class Assertions(unittest.TestCase):
    def error(self, code, call):
        with self.assertRaises(GPXError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def parse_error(self, code, data):
        return self.error(code, lambda: parse_gpx(data))


class ParserTests(Assertions):
    def test_no_tracks_is_valid(self):
        self.assertEqual(parse_gpx(xml()), GPX("Exemplos fictícios", (), 0))

    def test_equivalent_namespace_prefix(self):
        data = f'<p:gpx xmlns:p="{NS}" version="1.1" creator="c"><p:trk><p:trkseg><p:trkpt lat="1" lon="2"/></p:trkseg></p:trk></p:gpx>'
        self.assertEqual(parse_gpx(data.encode()).segments[0].points, (Point(1.0, 2.0),))

    def test_utf8_bom_and_declarations(self):
        for declaration in (b"", b'<?xml version="1.0" encoding="UTF-8"?>', b'<?xml version="1.0" encoding="UTF8"?>'):
            with self.subTest(declaration=declaration):
                self.assertEqual(parse_gpx(b"\xef\xbb\xbf" + declaration + xml()).track_count, 0)

    def test_empty_tracks_segments_and_index_reset(self):
        data = xml("<trk/>" + trk(segments="<trkseg/><trkseg/>") + trk(segments="<trkseg/>"))
        result = parse_gpx(data)
        self.assertEqual(result.track_count, 3)
        self.assertEqual([(s.track_index, s.segment_index, s.points) for s in result.segments], [(2, 1, ()), (2, 2, ()), (3, 1, ())])

    def test_names_trim_without_inventing_names(self):
        result = parse_gpx(xml(trk(name="<name>  Trilha fictícia  </name>") + trk()))
        self.assertEqual([s.name for s in result.segments], ["Trilha fictícia", ""])

    def test_name_after_segments_applies_to_track(self):
        result = parse_gpx(xml("<trk><trkseg/><name>Depois</name><trkseg/></trk>"))
        self.assertEqual([s.name for s in result.segments], ["Depois", "Depois"])

    def test_creator_is_preserved(self):
        self.assertEqual(parse_gpx(xml(creator="  fictício  ")).creator, "  fictício  ")

    def test_only_direct_waypoints_routes_count(self):
        result = parse_gpx(xml("<wpt/><rte/><rte/><extensions><wpt/><rte/></extensions>"))
        self.assertEqual((result.ignored_waypoints, result.ignored_routes, result.segments), (1, 2, ()))

    def test_extension_points_tracks_and_segments_are_ignored(self):
        data = xml("<extensions>" + trk(pt("invalid", "invalid")) + "</extensions>" + trk(
            "<extensions>" + pt("invalid", "invalid") + "</extensions>" + pt("1", "2")))
        result = parse_gpx(data)
        self.assertEqual((result.track_count, result.segments[0].points), (1, (Point(1.0, 2.0),)))

    def test_foreign_namespace_fields_do_not_count(self):
        fields = '<x:ele xmlns:x="urn:example">bad</x:ele><x:time xmlns:x="urn:example">bad</x:time>'
        result = parse_gpx(xml(trk(pt(fields=fields))))
        self.assertEqual(result.segments[0].points, (Point(0.0, 0.0),))

    def test_xinclude_is_ignored_without_loading(self):
        data = xml('<xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="file:///synthetic-unavailable"/>' + trk())
        self.assertEqual(parse_gpx(data).track_count, 1)

    def test_decimal_forms_and_outer_whitespace(self):
        result = parse_gpx(xml(trk(pt(" +.5 ", " -1. ", "<ele> +10.25 </ele>"))))
        self.assertEqual(result.segments[0].points, (Point(0.5, -1.0, 10.25),))

    def test_coordinate_elevation_inclusive_bounds(self):
        result = parse_gpx(xml(trk(pt("-90", "-180", "<ele>-12000</ele>") + pt("90", "179", "<ele>100000</ele>"))))
        self.assertEqual(result.segments[0].points, (Point(-90.0, -180.0, -12000.0), Point(90.0, 179.0, 100000.0)))

    def test_longitude_decimal_just_below_upper_boundary_is_valid(self):
        point = parse_gpx(xml(trk(pt("0", "179.99999999999999999999999")))).segments[0].points[0]
        self.assertLess(point.longitude, 180.0)
        self.assertEqual(point.longitude, math.nextafter(180.0, -math.inf))
        self.assertEqual(analyze(model([point]))["totals"]["point_count"], 1)

    def test_time_normalized_to_utc_with_fraction(self):
        point = parse_gpx(xml(trk(pt(fields="<time>2026-01-02T03:04:05.12+03:30</time>")))).segments[0].points[0]
        self.assertEqual(point.time, datetime(2026, 1, 1, 23, 34, 5, 120000, tzinfo=UTC))
        self.assertIs(point.time.tzinfo, UTC)

    def test_bytes_required(self):
        for value in ("<gpx/>", bytearray(xml()), memoryview(xml()), None):
            with self.subTest(kind=type(value).__name__), self.assertRaises(GPXError):
                parse_gpx(value)

    def test_invalid_utf8(self):
        self.parse_error("XML_INVALID", xml() + b"\xff")

    def test_encoding_declaration_restricted(self):
        for encoding in ("ISO-8859-1", "US-ASCII", "UTF-16"):
            with self.subTest(encoding=encoding):
                self.parse_error("XML_INVALID", f'<?xml version="1.0" encoding="{encoding}"?>'.encode() + xml())

    def test_xml_version_restricted(self):
        self.parse_error("XML_INVALID", b'<?xml version="1.1"?>' + xml())

    def test_malformed_xml(self):
        for data in (b"", xml()[:-1], xml() + b"<extra/>", xml("<broken>")):
            with self.subTest(size=len(data)):
                self.parse_error("XML_INVALID", data)

    def test_wrong_root_namespace_and_version(self):
        for data in (b'<gpx version="1.1" creator="c"/>', xml().replace(b"GPX/1/1", b"GPX/1/0"), xml().replace(b'version="1.1"', b'version="1.0"')):
            with self.subTest(data=data):
                self.parse_error("GPX_FORMAT", data)

    def test_missing_or_blank_creator(self):
        self.parse_error("GPX_FORMAT", xml(creator=""))
        self.parse_error("GPX_FORMAT", xml(creator=" \t "))
        self.parse_error("GPX_FORMAT", xml().replace('creator="Exemplos fictícios"'.encode(), b""))

    def test_dtd_entity_and_external_entity_are_unsafe(self):
        declarations = (b'<!DOCTYPE gpx>', b'<!DOCTYPE gpx [<!ENTITY a "synthetic">]>',
                        b'<!DOCTYPE gpx SYSTEM "file:///synthetic-unavailable">')
        for declaration in declarations:
            with self.subTest(declaration=declaration):
                self.parse_error("XML_UNSAFE", declaration + xml())

    def test_duplicate_name_is_format_error(self):
        self.parse_error("GPX_FORMAT", xml(trk(name="<name/><name/>")))

    def test_duplicate_elevation_and_time_are_format_errors(self):
        for fields in ("<ele>1</ele><ele>2</ele>", "<time>2026-01-01T00:00:00Z</time><time/>" ):
            with self.subTest(fields=fields):
                self.parse_error("GPX_FORMAT", xml(trk(pt(fields=fields))))

    def test_nested_name_elevation_time_are_format_errors(self):
        self.parse_error("GPX_FORMAT", xml(trk(name="<name><extension/></name>")))
        for field_name in ("ele", "time"):
            with self.subTest(field=field_name):
                self.parse_error("GPX_FORMAT", xml(trk(pt(fields=f"<{field_name}><extension/></{field_name}>"))))

    def test_missing_coordinates_are_not_silently_discarded(self):
        self.parse_error("COORD_INVALID", xml(trk('<trkpt lon="0"/>')))
        self.parse_error("COORD_INVALID", xml(trk('<trkpt lat="0"/>')))

    def test_coordinate_lexical_and_range_errors(self):
        for lat, lon in (("1e0", "0"), ("NaN", "0"), ("Infinity", "0"), ("９", "0"),
                         ("90.00000000000000000001", "0"), ("-90.1", "0"), ("0", "180"), ("0", "-180.1"), ("", "0")):
            with self.subTest(lat=lat, lon=lon):
                self.parse_error("COORD_INVALID", xml(trk(pt(lat, lon))))

    def test_elevation_lexical_and_range_errors(self):
        for value in ("1e2", "nan", "-12000.1", "100000.00000000000000001", ""):
            with self.subTest(value=value):
                self.parse_error("ELEVATION_INVALID", xml(trk(pt(fields=f"<ele>{value}</ele>"))))

    def test_time_grammar_and_calendar_errors(self):
        values = ("2026-01-01T00:00:00", "2026-01-01t00:00:00Z", "2026-01-01T00:00:00z",
                  "2026-01-01T00:00:60Z", "2026-02-29T00:00:00Z", "0000-01-01T00:00:00Z",
                  "2026-01-01T24:00:00Z", "2026-01-01T00:00:00.1234567Z",
                  "2026-01-01T00:00:00+24:00", "2026-01-01T00:00:00+00:60", "")
        for value in values:
            with self.subTest(value=value):
                self.parse_error("TIME_INVALID", xml(trk(pt(fields=f"<time>{value}</time>"))))

    def test_time_utc_overflow(self):
        for value in ("0001-01-01T00:00:00+00:01", "9999-12-31T23:59:59-00:01"):
            with self.subTest(value=value):
                self.parse_error("TIME_INVALID", xml(trk(pt(fields=f"<time>{value}</time>"))))

    def test_errors_do_not_echo_input(self):
        secret = "synthetic-marker-DO-NOT-ECHO"
        error = self.parse_error("COORD_INVALID", xml(trk(pt(secret, "0"))))
        self.assertNotIn(secret, str(error))


class ParserLimitsTests(Assertions):
    def test_input_bytes_limit_is_inclusive(self):
        base = xml(extra='metadata=""')
        at_limit = base.replace(b'metadata=""', b'metadata="' + b"x" * (8 * 1024 * 1024 - len(base)) + b'"')
        self.assertEqual(len(at_limit), 8 * 1024 * 1024)
        self.assertEqual(parse_gpx(at_limit).track_count, 0)
        self.parse_error("LIMIT_EXCEEDED", at_limit + b" ")

    def test_depth_limit_includes_ignored_metadata(self):
        self.assertEqual(parse_gpx(xml("<x>" * 31 + "</x>" * 31)).track_count, 0)
        self.parse_error("LIMIT_EXCEEDED", xml("<x>" * 32 + "</x>" * 32))

    def test_element_limit_includes_ignored_metadata(self):
        self.assertEqual(parse_gpx(xml("<x/>" * 199999)).track_count, 0)
        self.parse_error("LIMIT_EXCEEDED", xml("<x/>" * 200000))

    def test_point_limit_is_total_across_segments(self):
        allowed = pt() * 25000
        result = parse_gpx(xml(trk(allowed) + trk(allowed)))
        self.assertEqual(sum(len(s.points) for s in result.segments), 50000)
        self.parse_error("LIMIT_EXCEEDED", xml(trk(allowed) + trk(allowed + pt())))

    def test_track_limit_counts_empty_tracks(self):
        self.assertEqual(parse_gpx(xml("<trk/>" * 100)).track_count, 100)
        self.parse_error("LIMIT_EXCEEDED", xml("<trk/>" * 101))

    def test_segment_limit_counts_empty_segments(self):
        self.assertEqual(len(parse_gpx(xml(trk(segments="<trkseg/>" * 1000))).segments), 1000)
        self.parse_error("LIMIT_EXCEEDED", xml(trk(segments="<trkseg/>" * 1001)))

    def test_direct_text_limit_accumulates_chunks(self):
        self.assertEqual(parse_gpx(xml("<x>" + "a" * 4096 + "</x>")).track_count, 0)
        self.parse_error("LIMIT_EXCEEDED", xml("<x>" + "a" * 2048 + "<![CDATA[" + "a" * 2049 + "]]></x>"))

    def test_label_limits_are_inclusive_after_name_trim(self):
        self.assertEqual(parse_gpx(xml(trk(name="<name> " + "n" * 256 + " </name>"), creator="c" * 256)).segments[0].name, "n" * 256)
        self.parse_error("LIMIT_EXCEEDED", xml(creator="c" * 257))
        self.parse_error("LIMIT_EXCEEDED", xml(trk(name="<name>" + "n" * 257 + "</name>")))

    def test_numeric_lexical_limit_is_inclusive(self):
        self.assertEqual(parse_gpx(xml(trk(pt("0" * 32, "0")))).segments[0].points[0].latitude, 0.0)
        self.parse_error("LIMIT_EXCEEDED", xml(trk(pt("0" * 33, "0"))))
        self.parse_error("LIMIT_EXCEEDED", xml(trk(pt(fields="<ele>" + "0" * 33 + "</ele>"))))


class ModelTests(Assertions):
    def test_models_are_frozen(self):
        values = ((Point(1, 2), "latitude", 3), (Segment(1, 1, "", ()), "name", "changed"), (GPX("c", (), 0), "creator", "changed"))
        for value, attr, replacement in values:
            with self.subTest(kind=type(value).__name__), self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(value, attr, replacement)

    def test_input_is_not_mutated_and_time_is_read_as_utc(self):
        offset = timezone(timedelta(hours=2))
        time = datetime(2026, 1, 1, 2, tzinfo=offset)
        original = model([Point(1, 2, 3, time)])
        self.assertEqual(analyze(original)["totals"]["start_time"], "2026-01-01T00:00:00Z")
        self.assertIs(original.segments[0].points[0].time, time)
        self.assertIs(time.tzinfo, offset)

    def test_all_model_entrypoints_validate(self):
        bad = model([Point(float("nan"), 0)])
        for operation in (analyze, points_csv, to_geojson):
            with self.subTest(operation=operation.__name__):
                self.error("MODEL_INVALID", lambda: operation(bad))

    def test_model_type_and_tuples_required(self):
        values = (None, {}, GPX("c", [], 0), GPX("c", (object(),), 1), GPX("c", (Segment(1, 1, "", []),), 1), model([object()]))
        for value in values:
            with self.subTest(value=type(value).__name__):
                self.error("MODEL_INVALID", lambda: analyze(value))

    def test_coordinate_types_and_finitude(self):
        for value in (True, "1", float("nan"), float("inf"), -float("inf"), 10 ** 1000, 91):
            with self.subTest(value_type=type(value).__name__):
                self.error("MODEL_INVALID", lambda: analyze(model([Point(value, 0)])))
        self.error("MODEL_INVALID", lambda: analyze(model([Point(0, 180)])))

    def test_elevation_types_and_finitude(self):
        for value in (True, "1", float("nan"), float("inf"), -12001, 100001):
            with self.subTest(value=value):
                self.error("MODEL_INVALID", lambda: to_geojson(model([Point(0, 0, value)])))

    def test_naive_and_non_datetime_time_rejected(self):
        for value in (datetime(2026, 1, 1), "2026-01-01T00:00:00Z", True):
            with self.subTest(value=value):
                self.error("MODEL_INVALID", lambda: points_csv(model([Point(0, 0, time=value)])))

    def test_manual_utc_overflow_rejected(self):
        time = datetime(1, 1, 1, tzinfo=timezone(timedelta(minutes=1)))
        self.error("MODEL_INVALID", lambda: analyze(model([Point(0, 0, time=time)])))

    def test_invalid_timezone_offset_rejected(self):
        class InvalidOffset(tzinfo):
            def utcoffset(self, value):
                return timedelta(days=1)
        self.error("MODEL_INVALID", lambda: to_geojson(model([Point(0, 0, time=datetime(2026, 1, 1, tzinfo=InvalidOffset()))])))

    def test_labels_and_creator_validated(self):
        for value in (GPX("", (), 0), GPX(" " * 2, (), 0), GPX("c" * 257, (), 0), GPX(1, (), 0),
                      GPX("c", (Segment(1, 1, "n" * 257, ()),), 1), GPX("c", (Segment(1, 1, None, ()),), 1)):
            with self.subTest(value=value.creator):
                self.error("MODEL_INVALID", lambda: analyze(value))

    def test_counts_are_exact_integers_in_range(self):
        for count in (True, 1.0, -1, 101):
            with self.subTest(count=count):
                self.error("MODEL_INVALID", lambda: analyze(GPX("c", (), count)))
        for count in (True, -1, 200001):
            with self.subTest(ignored=count):
                self.error("MODEL_INVALID", lambda: analyze(GPX("c", (), 0, count)))

    def test_segment_indices_are_contiguous_and_ordered(self):
        sequences = ((Segment(1, 2, "", ()),), (Segment(1, 1, "", ()), Segment(1, 1, "", ())),
                     (Segment(2, 1, "", ()), Segment(1, 1, "", ())), (Segment(True, 1, "", ()),),
                     (Segment(1, True, "", ()),), (Segment(3, 1, "", ()),))
        for segments in sequences:
            with self.subTest(segments=segments):
                self.error("MODEL_INVALID", lambda: analyze(GPX("c", segments, 2)))

    def test_empty_tracks_may_leave_track_index_gaps(self):
        result = analyze(GPX("c", (Segment(2, 1, "", ()), Segment(4, 1, "", ())), 4))
        self.assertEqual(result["source"]["track_count"], 4)

    def test_manual_point_and_segment_limits(self):
        self.error("MODEL_INVALID", lambda: analyze(model([Point(0, 0)] * 50001)))
        many = tuple(Segment(1, i, "", ()) for i in range(1, 1002))
        self.error("MODEL_INVALID", lambda: analyze(GPX("c", many, 1)))

    def test_manual_element_lower_bound_includes_retained_fields(self):
        points = (Point(0, 0, 0, T0),) * 50000
        self.error("MODEL_INVALID", lambda: analyze(GPX("c", (Segment(1, 1, "", points),), 1, 50000)))

    def test_option_invalid_types_ranges_and_finitude(self):
        for value in (True, "1", float("nan"), float("inf"), 0, -1, 86400.1, 10 ** 1000):
            with self.subTest(gap_type=type(value).__name__):
                self.error("OPTION_INVALID", lambda: analyze(model(), max_gap_seconds=value))
        for value in (True, "1", float("nan"), float("inf"), -0.1, 1000.1):
            with self.subTest(threshold=value):
                self.error("OPTION_INVALID", lambda: analyze(model(), moving_threshold_kmh=value))

    def test_option_boundaries(self):
        result = analyze(model(), max_gap_seconds=86400, moving_threshold_kmh=0)
        self.assertEqual(result["method"], {"earth_radius_m": RADIUS, "max_gap_seconds": 86400.0, "moving_threshold_kmh": 0.0})
        self.assertEqual(analyze(model(), moving_threshold_kmh=1000)["method"]["moving_threshold_kmh"], 1000.0)


class AnalysisTests(Assertions):
    def test_schema_and_empty_statistics(self):
        result = analyze(GPX("c", (), 0))
        self.assertEqual(set(result), {"schema_version", "method", "source", "totals", "segments"})
        self.assertEqual(set(result["totals"]), STAT_KEYS)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["totals"]["point_count"], 0)
        self.assertIsNone(result["totals"]["bounds"])
        self.assertIsNone(result["totals"]["elapsed_span_s"])
        self.assertIsNone(result["totals"]["average_speed_kmh"])

    def test_equatorial_quarter_circumference(self):
        stats = analyze(model([Point(0, 0), Point(0, 90)]))["totals"]
        self.assertAlmostEqual(stats["distance_m"], math.pi * RADIUS / 2, places=6)

    def test_poles_and_antipodes_are_finite(self):
        result = analyze(model([Point(90, 0), Point(90, 170)], [Point(0, 0), Point(0, -180)]))
        self.assertAlmostEqual(result["segments"][0]["distance_m"], 0, delta=1e-6)
        self.assertAlmostEqual(result["segments"][1]["distance_m"], math.pi * RADIUS, delta=1e-6)
        json.dumps(result, allow_nan=False)

    def test_antimeridian_shortest_path(self):
        stats = analyze(model([Point(0, 179), Point(0, -179)]))["totals"]
        self.assertAlmostEqual(stats["distance_m"], math.pi * RADIUS / 90, places=7)
        self.assertEqual(stats["bounds"], [-179.0, 0.0, 179.0, 0.0])

    def test_never_connects_segments_or_tracks(self):
        value = GPX("c", (Segment(1, 1, "a", (Point(0, 0),)), Segment(1, 2, "b", (Point(0, 90),)),
                          Segment(2, 1, "c", (Point(0, -90),))), 2)
        stats = analyze(value)["totals"]
        self.assertEqual((stats["point_count"], stats["edge_count"], stats["distance_m"]), (3, 0, 0.0))

    def test_elevation_uses_only_complete_adjacent_edges(self):
        value = model([Point(0, 0, 0), Point(0, 0, 10), Point(0, 0, 4), Point(0, 0), Point(0, 0, 20)])
        stats = analyze(value)["totals"]
        self.assertEqual((stats["ascent_m"], stats["descent_m"], stats["elevation_edges"], stats["missing_elevation_edges"]), (10.0, 6.0, 2, 2))
        self.assertEqual(stats["distance_m"], 0.0)

    def test_time_missing_repeated_and_reverse_are_invalid(self):
        value = model([Point(0, 0), Point(0, 1, time=T0)], [Point(0, 0, time=T0), Point(0, 1, time=T0)],
                      [Point(0, 0, time=T0), Point(0, 1, time=T0 - timedelta(seconds=1))])
        stats = analyze(value)["totals"]
        self.assertEqual((stats["invalid_time_edges"], stats["usable_time_edges"], stats["gap_time_edges"]), (3, 0, 0))
        self.assertGreater(stats["distance_m"], 0)
        self.assertEqual(stats["usable_distance_m"], 0)

    def test_gap_boundary_and_gap_distance(self):
        value = model([Point(0, 0, time=T0), Point(0, 1, time=T0 + timedelta(seconds=300)),
                       Point(0, 2, time=T0 + timedelta(seconds=601))])
        stats = analyze(value)["totals"]
        self.assertEqual((stats["usable_time_edges"], stats["gap_time_edges"], stats["invalid_time_edges"]), (1, 1, 0))
        self.assertEqual(stats["usable_time_s"], 300.0)
        self.assertAlmostEqual(stats["distance_m"], 2 * stats["usable_distance_m"])

    def test_moving_threshold_is_inclusive(self):
        value = model([Point(0, 0, time=T0), Point(0, 1, time=T0 + timedelta(seconds=1000))])
        speed = math.pi * RADIUS / 180 / 1000 * 3.6
        observed_speed = analyze(value, max_gap_seconds=1000)["totals"]["average_speed_kmh"]
        stats = analyze(value, max_gap_seconds=1000, moving_threshold_kmh=observed_speed)["totals"]
        self.assertEqual(stats["moving_time_s"], 1000.0)
        self.assertAlmostEqual(stats["moving_speed_kmh"], speed)
        self.assertEqual(analyze(value, max_gap_seconds=1000, moving_threshold_kmh=speed + 0.01)["totals"]["moving_time_s"], 0.0)

    def test_stationary_edge_can_move_only_at_zero_threshold(self):
        value = model([Point(0, 0, time=T0), Point(0, 0, time=T0 + timedelta(seconds=1))])
        self.assertEqual(analyze(value)["totals"]["moving_time_s"], 0.0)
        stats = analyze(value, moving_threshold_kmh=0)["totals"]
        self.assertEqual((stats["moving_time_s"], stats["moving_speed_kmh"], stats["average_speed_kmh"]), (1.0, 0.0, 0.0))

    def test_totals_recompute_speed_from_combined_time(self):
        value = model([Point(0, 0, time=T0), Point(0, 1, time=T0 + timedelta(seconds=100))],
                      [Point(0, 0, time=T0), Point(0, 1, time=T0 + timedelta(seconds=200))])
        result = analyze(value)
        expected = (2 * math.pi * RADIUS / 180) / 300 * 3.6
        self.assertAlmostEqual(result["totals"]["average_speed_kmh"], expected)
        self.assertNotAlmostEqual(result["totals"]["average_speed_kmh"], sum(s["average_speed_kmh"] for s in result["segments"]) / 2)

    def test_known_time_extrema_do_not_depend_on_point_order(self):
        value = model([Point(1, 2, time=T0 + timedelta(seconds=60)), Point(-1, -2, time=T0), Point(0, 0)])
        stats = analyze(value)["totals"]
        self.assertEqual((stats["start_time"], stats["end_time"], stats["elapsed_span_s"]), ("2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z", 60.0))
        self.assertEqual(stats["bounds"], [-2.0, -1.0, 2.0, 1.0])

    def test_singleton_time_has_zero_elapsed_span(self):
        stats = analyze(model([Point(1, 2, time=T0)]))["totals"]
        self.assertEqual(stats["elapsed_span_s"], 0.0)
        self.assertEqual(stats["edge_count"], 0)

    def test_empty_segment_retained_and_source_counts(self):
        value = GPX("c", (Segment(2, 1, "vazio", ()),), 2, 3, 4)
        result = analyze(value)
        self.assertEqual(result["source"], {"creator": "c", "track_count": 2, "segment_count": 1, "point_count": 0, "ignored_waypoints": 3, "ignored_routes": 4})
        self.assertEqual(set(result["segments"][0]), STAT_KEYS | {"track_index", "segment_index", "name"})
        self.assertIsNone(result["segments"][0]["bounds"])

    def test_coverage_identities_on_mixed_data(self):
        value = model([Point(0, 0, 1, T0), Point(0, 1, 2, T0 + timedelta(seconds=10)),
                       Point(0, 2, None, T0 + timedelta(seconds=1000)), Point(0, 3, 4)])
        result = analyze(value)
        for stats in [result["totals"], *result["segments"]]:
            self.assertEqual(stats["elevation_edges"] + stats["missing_elevation_edges"], stats["edge_count"])
            self.assertEqual(stats["usable_time_edges"] + stats["invalid_time_edges"] + stats["gap_time_edges"], stats["edge_count"])
        json.dumps(result, allow_nan=False)


class ExportTests(Assertions):
    def test_csv_exact_header_and_empty_output(self):
        self.assertEqual(points_csv(GPX("c", (), 0)), "track,segment,point,latitude,longitude,elevation_m,time_utc,distance_m\n")

    def test_csv_float_repr_missing_fields_and_utc(self):
        value = model([Point(1, -2, 0, datetime(2026, 1, 1, 2, 0, 0, 1, timezone(timedelta(hours=2))))], [Point(0, 0)])
        expected = ("track,segment,point,latitude,longitude,elevation_m,time_utc,distance_m\n"
                    "1,1,1,1.0,-2.0,0.0,2026-01-01T00:00:00.000001Z,0.0\n"
                    "1,2,1,0.0,0.0,,,0.0\n")
        self.assertEqual(points_csv(value), expected)

    def test_csv_distance_and_point_index_reset(self):
        value = model([Point(0, 0), Point(0, 1)], [Point(0, 100), Point(0, 101)])
        rows = list(csv.DictReader(io.StringIO(points_csv(value))))
        self.assertEqual([row["point"] for row in rows], ["1", "2", "1", "2"])
        self.assertEqual([float(rows[i]["distance_m"]) for i in (0, 2)], [0.0, 0.0])
        self.assertAlmostEqual(float(rows[1]["distance_m"]), math.pi * RADIUS / 180)
        self.assertEqual(rows[1]["distance_m"], rows[3]["distance_m"])

    def test_csv_does_not_expose_metadata_and_uses_lf(self):
        value = GPX("=creator-marker", (Segment(1, 1, "=name-marker\r\n", (Point(0, 0),)),), 1)
        output = points_csv(value)
        self.assertNotIn("marker", output)
        self.assertNotIn("\r", output)
        self.assertEqual(len(list(csv.reader(io.StringIO(output)))), 2)

    def test_geojson_empty_segment_and_exact_properties(self):
        result = to_geojson(GPX("hidden", (Segment(2, 1, "segmento", ()),), 2))
        self.assertEqual(result, {"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": "t2-s1", "properties": {"track_index": 2, "segment_index": 1, "name": "segmento", "point_count": 0}, "geometry": None}]})

    def test_geojson_point_and_3d_linestring(self):
        result = to_geojson(model([Point(1, 2)], [Point(3, 4, 5), Point(6, 7, 8)]))
        self.assertEqual(result["features"][0]["geometry"], {"type": "Point", "coordinates": [2.0, 1.0]})
        self.assertEqual(result["features"][1]["geometry"], {"type": "LineString", "coordinates": [[4.0, 3.0, 5.0], [7.0, 6.0, 8.0]]})

    def test_geojson_partial_elevation_makes_entire_segment_2d(self):
        geometry = to_geojson(model([Point(0, 179, 5), Point(10, -179)]))["features"][0]["geometry"]
        self.assertEqual(geometry["type"], "MultiLineString")
        self.assertTrue(all(len(position) == 2 for part in geometry["coordinates"] for position in part))

    def test_geojson_antimeridian_eastward_interpolation(self):
        geometry = to_geojson(model([Point(0, 179, 10), Point(2, -179, 30)]))["features"][0]["geometry"]
        self.assertEqual(geometry, {"type": "MultiLineString", "coordinates": [
            [[179.0, 0.0, 10.0], [180.0, 1.0, 20.0]], [[-180.0, 1.0, 20.0], [-179.0, 2.0, 30.0]]]})

    def test_geojson_antimeridian_westward_interpolation(self):
        geometry = to_geojson(model([Point(4, -179), Point(0, 179)]))["features"][0]["geometry"]
        self.assertEqual(geometry, {"type": "MultiLineString", "coordinates": [
            [[-179.0, 4.0], [-180.0, 2.0]], [[180.0, 2.0], [179.0, 0.0]]]})

    def test_geojson_exact_180_degree_edge_does_not_need_split(self):
        geometry = to_geojson(model([Point(0, -180), Point(1, 0)]))["features"][0]["geometry"]
        self.assertEqual(geometry, {"type": "LineString", "coordinates": [[-180.0, 0.0], [0.0, 1.0]]})

    def test_geojson_boundary_degeneracy_has_no_singleton_parts(self):
        for points in ([Point(0, -180), Point(1, 179)], [Point(0, 179), Point(1, -180)],
                       [Point(0, -180), Point(1, 179), Point(2, -180), Point(3, -179)]):
            with self.subTest(longitudes=[p.longitude for p in points]):
                geometry = to_geojson(model(points))["features"][0]["geometry"]
                self.assertEqual(geometry["type"], "MultiLineString")
                for part in geometry["coordinates"]:
                    self.assertGreaterEqual(len(part), 2)
                    self.assertTrue(all(abs(a[0] - b[0]) <= 180 for a, b in zip(part, part[1:])))
                self.assertEqual(geometry["coordinates"][0][0], [float(points[0].longitude), float(points[0].latitude)])
                self.assertEqual(geometry["coordinates"][-1][-1], [float(points[-1].longitude), float(points[-1].latitude)])

    def test_geojson_repeated_crossings_preserve_original_points(self):
        points = [Point(0, 179), Point(1, -179), Point(2, 178), Point(3, -178)]
        geometry = to_geojson(model(points))["features"][0]["geometry"]
        self.assertEqual(len(geometry["coordinates"]), 4)
        positions = [position for part in geometry["coordinates"] for position in part]
        for point in points:
            self.assertIn([point.longitude, point.latitude], positions)
        json.dumps(geometry, allow_nan=False)

    def test_exports_return_independent_values(self):
        value = model([Point(1, 2)])
        first = to_geojson(value)
        first["features"][0]["geometry"]["coordinates"][0] = 50
        self.assertEqual(to_geojson(value)["features"][0]["geometry"]["coordinates"], [2.0, 1.0])


if __name__ == "__main__":
    unittest.main()
