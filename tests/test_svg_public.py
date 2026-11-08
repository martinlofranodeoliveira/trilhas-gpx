"""Contratos públicos do relatório, com trajetos exclusivamente sintéticos."""

import copy
import math
import re
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from trilhas_gpx.core import GPX, GPXError, Point, Segment, analyze
from trilhas_gpx import svg


NS = {"s": "http://www.w3.org/2000/svg"}


def model(*segments):
    return GPX("Criador fictício", tuple(Segment(1, index, "", tuple(points))
               for index, points in enumerate(segments, 1)), 1)


def render(gpx, **options):
    return ET.fromstring(svg.to_svg(gpx, **options))


def by_id(root, identifier):
    return next(node for node in root.iter() if node.get("id") == identifier)


def roles(root, role):
    return [node for node in root.iter() if node.get("data-role") == role]


def path_points(node):
    data = node.get("d")
    if not re.fullmatch(r"M-?\d+\.\d{3} -?\d+\.\d{3}(?: L-?\d+\.\d{3} -?\d+\.\d{3})+", data):
        raise AssertionError("Traçado deve conter apenas M/L e coordenadas finitas de três casas")
    values = [float(value) for value in re.findall(r"-?\d+\.\d{3}", data)]
    return list(zip(values[::2], values[1::2]))


class SVGPublicTests(unittest.TestCase):
    def assert_error(self, code, function):
        with self.assertRaises(GPXError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)

    def test_document_dimensions_namespace_and_accessible_description(self):
        root = render(model([Point(0, 0, 12)]))
        self.assertEqual(root.tag, "{" + NS["s"] + "}svg")
        self.assertEqual([root.get(key) for key in ("width", "height", "viewBox", "role")],
                         ["1200", "960", "0 0 1200 960", "img"])
        identifiers = root.get("aria-labelledby").split()
        self.assertEqual(len(identifiers), 2)
        self.assertEqual([by_id(root, value).tag for value in identifiers],
                         ["{" + NS["s"] + "}title", "{" + NS["s"] + "}desc"])
        self.assertIn("Relatório", by_id(root, identifiers[0]).text)

    def test_document_is_deterministic_without_mutating_manual_model(self):
        timestamp = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=-3)))
        gpx = model([Point(0, 1, 20, timestamp), Point(1, 2, None, timestamp)])
        original = copy.deepcopy(gpx)
        first = svg.to_svg(gpx)
        self.assertEqual(first, svg.to_svg(gpx))
        self.assertEqual(gpx, original)
        self.assertIs(gpx.segments[0].points[0].time, timestamp)

    def test_free_text_timestamps_and_file_like_metadata_are_never_echoed(self):
        marker = 'SEGREDO-ficticio-<script onload="alert(1)">file:///home/exemplo'
        timestamp = datetime(2025, 7, 16, 8, 9, 10, tzinfo=timezone.utc)
        gpx = GPX(marker, (Segment(1, 1, marker, (Point(1, 2, 3, timestamp),)),), 1)
        text = svg.to_svg(gpx)
        for value in ("SEGREDO", "<script", "alert(1)", "file:", "/home", "2025-07-16", "08:09:10", "creator", "onload"):
            self.assertNotIn(value, text)
        self.assertIn('data-longitude="2.0"', text)
        self.assertIn('data-elevation-m="3.0"', text)

    def test_passive_markup_has_no_resources_events_or_foreign_namespace(self):
        root = render(model([Point(-90, -180, -12000), Point(90, 179, 100000)]))
        allowed = {"svg", "title", "desc", "rect", "g", "text", "line", "path", "circle"}
        for node in root.iter():
            self.assertTrue(node.tag.startswith("{" + NS["s"] + "}"))
            self.assertIn(node.tag.split("}")[1], allowed)
            for key, value in node.attrib.items():
                self.assertFalse(key.lower().startswith("on"))
                self.assertNotIn("href", key)
                self.assertNotIn("url(", value.lower())
                self.assertNotIn("://", value)
        self.assertEqual(root.get("font-family"), "sans-serif")

    def test_summary_preserves_exact_analysis_statistics_with_options(self):
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        gpx = model([Point(0, 0, 10, t0), Point(0, 0.1, 30, t0 + timedelta(seconds=60)),
                     Point(0, 0.2, None, t0 + timedelta(seconds=120))])
        options = dict(max_gap_seconds=30, moving_threshold_kmh=20)
        summary = by_id(render(gpx, **options), "summary")
        stats = analyze(gpx, **options)["totals"]
        keys = ("distance_m", "ascent_m", "descent_m", "edge_count", "elevation_edges",
                "missing_elevation_edges", "usable_time_edges", "invalid_time_edges", "gap_time_edges")
        for key in keys:
            self.assertEqual(summary.get("data-stat-" + key.replace("_", "-")), repr(stats[key]))
        self.assertEqual(summary.get("data-point-count"), "3")
        self.assertEqual(summary.get("data-segment-count"), "1")
        self.assertIn("Tempo utilizável: 0 / 2", " ".join(summary.itertext()))

    def test_all_empty_and_nonempty_segment_identities_remain_in_both_panels(self):
        gpx = GPX("Fictício", (Segment(2, 1, "", ()), Segment(2, 2, "", (Point(0, 0),)),
                              Segment(3, 1, "", ())), 3)
        root = render(gpx)
        for panel in ("route", "profile"):
            groups = by_id(root, panel).findall("s:g", NS)
            self.assertEqual([node.get("id") for node in groups],
                             [panel + "-t2-s1", panel + "-t2-s2", panel + "-t3-s1"])
            self.assertEqual([(node.get("data-track"), node.get("data-segment")) for node in groups],
                             [("2", "1"), ("2", "2"), ("3", "1")])

    def test_inventory_is_bounded_but_all_thousand_segments_are_retained(self):
        gpx = model(*[[] for _ in range(1000)])
        root = render(gpx)
        inventory = " ".join(by_id(root, "inventory").itertext())
        self.assertEqual(re.findall(r"t\d+-s\d+", inventory), [f"t1-s{i}" for i in range(1, 9)])
        self.assertIn("992 segmentos omitidos", inventory)
        for panel in ("route", "profile"):
            self.assertEqual(len(by_id(root, panel).findall("s:g", NS)), 1000)

    def test_no_points_has_explicit_message_and_no_geometry(self):
        root = render(GPX("Fictício", (), 0))
        self.assertIn("Sem pontos de trilha", " ".join(root.itertext()))
        self.assertFalse(root.findall(".//s:path", NS))
        self.assertFalse(root.findall(".//s:circle", NS))
        self.assertEqual(by_id(root, "route").get("data-seam-deg"), "0.0")

    def test_missing_elevations_do_not_become_zero_points(self):
        root = render(model([Point(0, 0), Point(0, 1)]))
        profile = by_id(root, "profile")
        self.assertIn("Sem elevação registrada", " ".join(profile.itertext()))
        self.assertFalse(roles(profile, "profile-line"))
        self.assertFalse(roles(profile, "profile-point"))
        self.assertEqual(len(roles(root, "route-point")), 2)

    def test_elevation_gaps_split_runs_and_keep_isolated_measured_points(self):
        points = [Point(0, i, value) for i, value in enumerate((1, 2, None, 4, None, 6, 7))]
        profile = by_id(render(model(points)), "profile")
        self.assertEqual(len(roles(profile, "profile-line")), 2)
        circles = roles(profile, "profile-point")
        self.assertEqual([node.get("data-point") for node in circles], ["1", "2", "4", "6", "7"])
        self.assertEqual([node.get("data-elevation-m") for node in circles], ["1.0", "2.0", "4.0", "6.0", "7.0"])
        for node in roles(profile, "profile-line"):
            self.assertEqual(len(path_points(node)), 2)

    def test_singletons_and_flat_stationary_measurements_have_visible_markers(self):
        root = render(model([Point(10, 10, 20)], [Point(10, 10, 20), Point(10, 10, 20)]))
        circles = roles(root, "profile-point")
        self.assertEqual(len(circles), 3)
        self.assertEqual(len({(node.get("cx"), node.get("cy")) for node in circles}), 1)
        self.assertTrue(all(float(node.get("r")) >= 2 for node in circles))
        self.assertEqual(len(roles(root, "profile-line")), 1)
        self.assertEqual(len(roles(root, "route-point")), 3)

    def test_profile_accumulates_inside_segments_without_adding_jumps(self):
        gpx = model([Point(0, 0, 10), Point(0, 1, 20)], [Point(70, 100, 30), Point(70, 101, 40)])
        root = render(gpx)
        circles = roles(root, "profile-point")
        distances = [float(node.get("data-distance-m")) for node in circles]
        first_edge = 6371008.8 * math.pi / 180
        second_edge = 2 * 6371008.8 * math.asin(math.cos(math.radians(70)) * math.sin(math.pi / 360))
        for actual, expected in zip(distances, (0, first_edge, first_edge, first_edge + second_edge)):
            self.assertAlmostEqual(actual, expected, places=7)
        self.assertEqual(circles[1].get("cx"), circles[2].get("cx"))
        self.assertEqual(by_id(root, "profile").get("data-distance-m"), repr(analyze(gpx)["totals"]["distance_m"]))
        self.assertEqual(len(roles(root, "profile-line")), 2)

    def test_segment_boundaries_exist_only_for_segments_with_points(self):
        root = render(model([], [Point(0, 0)], [], [Point(1, 1, 12)]))
        profile = by_id(root, "profile")
        self.assertEqual(len(roles(profile, "segment-boundary")), 2)
        self.assertEqual(len(roles(by_id(root, "profile-t1-s2"), "segment-boundary")), 1)
        self.assertFalse(roles(by_id(root, "profile-t1-s3"), "segment-boundary"))

    def test_antimeridian_short_window_has_two_degree_real_span(self):
        root = render(model([Point(0, 179), Point(0, -179)]))
        route = by_id(root, "route")
        self.assertEqual(float(route.get("data-seam-deg")), 0)
        self.assertEqual(float(route.get("data-longitude-span-deg")), 2)
        self.assertEqual(float(route.get("data-latitude-span-deg")), 0)
        lines = roles(route, "route-line")
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(path_points(lines[0])), 2)

    def test_largest_gap_tie_selects_smallest_normalized_start(self):
        root = render(model([Point(0, 0)], [Point(0, 90)], [Point(0, -180)], [Point(0, -90)]))
        route = by_id(root, "route")
        self.assertEqual(float(route.get("data-seam-deg")), 45)
        self.assertEqual(float(route.get("data-longitude-span-deg")), 270)
        self.assertFalse(roles(route, "route-line"))

    def test_one_distinct_longitude_places_seam_on_opposite_meridian(self):
        root = render(model([Point(0, -170), Point(1, -170)]))
        route = by_id(root, "route")
        self.assertEqual(float(route.get("data-seam-deg")), 10)
        self.assertEqual(float(route.get("data-longitude-span-deg")), 0)
        points = roles(route, "route-point")
        self.assertEqual(points[0].get("cx"), points[1].get("cx"))

    def test_route_segments_never_gain_a_connector_and_point_indices_restart(self):
        root = render(model([Point(0, 0), Point(0, 1)], [], [Point(40, 80), Point(41, 81)]))
        route = by_id(root, "route")
        self.assertEqual(len(roles(route, "route-line")), 2)
        for identifier in ("route-t1-s1", "route-t1-s3"):
            segment = by_id(root, identifier)
            circles = roles(segment, "route-point")
            self.assertEqual([node.get("data-point") for node in circles], ["1", "2"])
            self.assertEqual(path_points(roles(segment, "route-line")[0]),
                             [(float(node.get("cx")), float(node.get("cy"))) for node in circles])
        self.assertFalse(roles(by_id(root, "route-t1-s2"), "route-line"))

    def test_crossing_display_seam_splits_with_linear_latitude_interpolation(self):
        # Four equally spaced longitudes fix the seam at 55°, between 10° and 100°.
        root = render(model([Point(0, 10), Point(20, 100)], [Point(0, -170)], [Point(0, -80)]))
        route = by_id(root, "route")
        self.assertEqual(float(route.get("data-seam-deg")), 55)
        self.assertEqual(float(route.get("data-longitude-span-deg")), 360)
        lines = roles(by_id(root, "route-t1-s1"), "route-line")
        self.assertEqual(len(lines), 2)
        a, b = path_points(lines[0]), path_points(lines[1])
        self.assertAlmostEqual(a[-1][1], b[0][1], places=3)
        self.assertAlmostEqual(a[-1][1], (a[0][1] + b[-1][1]) / 2, places=3)
        whole_turn_width = a[-1][0] - b[0][0]
        self.assertGreater(whole_turn_width, 0)
        self.assertAlmostEqual((a[-1][0] - a[0][0]) * 8, whole_turn_width, delta=0.006)
        self.assertAlmostEqual((b[-1][0] - b[0][0]) * 8, whole_turn_width, delta=0.006)

    def test_exact_half_turn_always_uses_positive_180_and_splits_when_required(self):
        root = render(model([Point(0, 0), Point(10, -180)]))
        route = by_id(root, "route")
        self.assertEqual(float(route.get("data-seam-deg")), 90)
        self.assertEqual(float(route.get("data-longitude-span-deg")), 360)
        lines = roles(route, "route-line")
        self.assertEqual(len(lines), 2)
        first, second = map(path_points, lines)
        self.assertGreater(first[-1][0], first[0][0])
        self.assertGreater(second[-1][0], second[0][0])
        self.assertAlmostEqual(first[-1][1], (first[0][1] + second[-1][1]) / 2, places=3)

    def test_clipping_includes_endpoint_360_and_zero_length_boundary_part(self):
        parts = svg._route_parts((Point(0, 0), Point(20, 10)), 10.0)
        self.assertEqual(parts, [[(350.0, 0), (360.0, 20)], [(0.0, 20), (0.0, 20)]])
        starts_on_seam = svg._route_parts((Point(0, 10), Point(20, 0)), 10.0)
        self.assertEqual(starts_on_seam, [[(0.0, 0), (0.0, 0)], [(360.0, 0), (350.0, 20)]])

    def test_negative_crossing_interpolates_and_never_adds_interior_connector(self):
        parts = svg._route_parts((Point(0, 10), Point(20, -10)), 0.0)
        self.assertEqual(parts, [[(10.0, 0), (0.0, 10.0)], [(360.0, 10.0), (350.0, 20)]])
        for part in parts:
            self.assertTrue(all(abs(a[0] - b[0]) <= 180 for a, b in zip(part, part[1:])))

    def test_route_uses_equal_pixel_scale_for_latitude_and_longitude(self):
        root = render(model([Point(10, 20), Point(11, 21)]))
        a, b = roles(root, "route-point")
        dx = float(b.get("cx")) - float(a.get("cx"))
        dy = float(b.get("cy")) - float(a.get("cy"))
        self.assertAlmostEqual(dx, -dy, places=3)
        self.assertGreater(dx, 0)

    def test_subnormal_and_polar_coordinates_remain_finite_and_renderable(self):
        for points in ([Point(0, 0, 0), Point(5e-324, -5e-324, 5e-324)],
                       [Point(-90, -180, -12000), Point(90, math.nextafter(180.0, -math.inf), 100000)]):
            with self.subTest(points=points):
                root = render(model(points))
                for node in root.iter():
                    for key in ("x", "y", "cx", "cy", "x1", "x2", "y1", "y2", "r"):
                        if key in node.attrib:
                            self.assertTrue(math.isfinite(float(node.get(key))))
                for node in root.findall(".//s:path", NS):
                    path_points(node)

    def test_manual_model_validation_fails_closed_with_stable_error_codes(self):
        invalid = (None, GPX("", (), 0), model([Point(True, 0)]), model([Point(math.nan, 0)]),
                   model([Point(0, 180)]), model([Point(0, 0, math.inf)]),
                   GPX("Fictício", [Segment(1, 1, "", ())], 1))
        for value in invalid:
            with self.subTest(value=value):
                self.assert_error("MODEL_INVALID", lambda: svg.to_svg(value))

    def test_analysis_options_reuse_original_validation_and_precedence(self):
        for key, values in (("max_gap_seconds", (0, -1, 86401, True, "30", math.inf, math.nan)),
                            ("moving_threshold_kmh", (-1, 1001, False, "1", math.inf, math.nan))):
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assert_error("OPTION_INVALID", lambda: svg.to_svg(None, **{key: value}))
        self.assertTrue(svg.to_svg(model([]), max_gap_seconds=86400, moving_threshold_kmh=0))

    def test_full_fifty_thousand_point_model_and_next_point_limit(self):
        point = Point(0, 0, 10)
        gpx = model([point] * 50000)
        document = svg.to_svg(gpx)
        self.assertEqual(document.count('data-role="route-point"'), 50000)
        self.assertEqual(document.count('data-role="profile-point"'), 50000)
        self.assertLessEqual(len(document.encode("utf-8")), 32 * 1024 * 1024)
        self.assert_error("MODEL_INVALID", lambda: svg.to_svg(model([point] * 50001)))

    def test_output_limit_is_inclusive_and_counts_utf8_bytes(self):
        gpx = model([Point(0, 0, 2)])
        document = svg.to_svg(gpx)
        size = len(document.encode("utf-8"))
        self.assertGreater(size, len(document))
        with patch.object(svg, "MAX_SVG_BYTES", size):
            self.assertEqual(svg.to_svg(gpx), document)
        with patch.object(svg, "MAX_SVG_BYTES", size - 1):
            self.assert_error("LIMIT_EXCEEDED", lambda: svg.to_svg(gpx))

    def test_real_32_mib_utf8_limit_is_checked_after_full_serialization(self):
        # Fault injection adds a known, complete UTF-8 payload through the renderer.
        # Its character count is below 32 MiB, while its encoded document exceeds it.
        original = ET.tostring
        observed = []

        def inventory(root, _model):
            ET.SubElement(root, "text").text = "é" * (16 * 1024 * 1024)

        def serialized(*args, **kwargs):
            document = original(*args, **kwargs)
            observed.append((len(document), len(document.encode("utf-8"))))
            return document

        self.assertEqual(svg.MAX_SVG_BYTES, 32 * 1024 * 1024)
        with patch.object(svg, "_inventory", inventory), patch.object(ET, "tostring", serialized):
            self.assert_error("LIMIT_EXCEEDED", lambda: svg.to_svg(model([])))
        self.assertEqual(len(observed), 1)
        self.assertLess(observed[0][0], 32 * 1024 * 1024)
        self.assertGreater(observed[0][1], 32 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
