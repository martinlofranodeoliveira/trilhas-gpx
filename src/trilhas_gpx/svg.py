"""Relatório SVG estático, sem recursos externos ou metadados livres do GPX.

O trajeto usa graus de latitude/longitude e não constitui mapa de navegação.
Coordenadas e elevações continuam presentes: este exportador não anonimiza GPS.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .core import GPX, GPXError, _distance, _validated, analyze


MAX_SVG_BYTES = 32 * 1024 * 1024
_NAVY = "#163047"
_TEAL = "#007f80"
_MUTED = "#536777"
_GRID = "#e3e9ec"
_ROUTE_BOX = (100.0, 350.0, 1110.0, 482.0)
_PROFILE_BOX = (100.0, 643.0, 1110.0, 775.0)
_STAT_KEYS = (
    "distance_m", "ascent_m", "descent_m", "edge_count", "elevation_edges",
    "missing_elevation_edges", "usable_time_edges", "invalid_time_edges", "gap_time_edges",
)


def _node(parent, tag, *, text=None, **attributes):
    node = ET.SubElement(parent, tag, {
        key.replace("_", "-"): str(value) for key, value in attributes.items()
    })
    node.text = text
    return node


def _pixel(value):
    # Avoid a visually meaningless negative zero; retain three decimal places.
    return f"{0.0 if abs(value) < 0.0005 else value:.3f}"


def _label(value, digits=2):
    rounded = round(value, digits)
    return f"{0.0 if rounded == 0 else rounded:.{digits}f}".replace(".", ",")


def _tick_digits(step, minimum=1):
    digits = 1
    while 0 < abs(step) < 1 and digits < 8:
        digits += 1
        step *= 10
    return max(minimum, digits)


def _text(parent, x, y, value, *, size=14, fill=_NAVY, anchor="start", weight=None):
    attributes = dict(x=_pixel(x), y=_pixel(y), font_size=size, fill=fill, text_anchor=anchor)
    if weight is not None:
        attributes["font_weight"] = weight
    return _node(parent, "text", text=value, **attributes)


def _line(parent, x1, y1, x2, y2, **attributes):
    return _node(parent, "line", x1=_pixel(x1), y1=_pixel(y1),
                 x2=_pixel(x2), y2=_pixel(y2), **attributes)


def _path(parent, points, role, color):
    if len(points) >= 2:
        data = " ".join(("M" if index == 0 else "L") + _pixel(x) + " " + _pixel(y)
                        for index, (x, y) in enumerate(points))
        _node(parent, "path", d=data, data_role=role, fill="none", stroke=color,
              stroke_width="2", stroke_linecap="round", stroke_linejoin="round")


def _turn(longitude):
    # Python's floating modulo can round a tiny negative number to 360.0.
    return (longitude % 360.0) % 360.0


def _seam(points):
    """Middle of the largest empty circular gap; ties use its smallest start."""
    values = sorted({_turn(point.longitude) for point in points})
    if not values:
        return 0.0
    gaps = [(values[(index + 1) % len(values)] + (360.0 if index == len(values) - 1 else 0.0)
             - start, start) for index, start in enumerate(values)]
    gap, start = max(gaps, key=lambda item: (item[0], -item[1]))
    return _turn(start + gap / 2)


def _short_delta(a, b):
    delta = (b.longitude - a.longitude + 180.0) % 360.0 - 180.0
    return 180.0 if delta == -180.0 else delta


def _route_parts(points, seam):
    """Cut shortest wrapped edges at the display seam, interpolating latitude."""
    if not points:
        return []
    parts = [[(_turn(points[0].longitude - seam), points[0].latitude)]]
    for a, b in zip(points, points[1:]):
        a_x = _turn(a.longitude - seam)
        b_x = _turn(b.longitude - seam)
        delta = _short_delta(a, b)
        unwrapped = a_x + delta
        if unwrapped < 0.0 or unwrapped >= 360.0:
            boundary = 0.0 if unwrapped < 0.0 else 360.0
            fraction = (boundary - a_x) / delta
            latitude = (a.latitude if fraction == 0.0 else b.latitude if fraction == 1.0
                        else a.latitude + fraction * (b.latitude - a.latitude))
            parts[-1].append((boundary, latitude))
            parts.append([(360.0 - boundary, latitude), (b_x, b.latitude)])
        else:
            parts[-1].append((b_x, b.latitude))
    return parts


def _route_projection(parts):
    coordinates = [point for segment_parts in parts for part in segment_parts for point in part]
    xs = [point[0] for point in coordinates] or [0.0]
    ys = [point[1] for point in coordinates] or [0.0]
    x_low, x_high, y_low, y_high = min(xs), max(xs), min(ys), max(ys)
    x_span, y_span = x_high - x_low, y_high - y_low
    padding = max((max(x_span, y_span) or 1.0) * 0.06, 1e-9)
    left, top, right, bottom = _ROUTE_BOX
    scale = min((right - left) / (x_span + 2 * padding),
                (bottom - top) / (y_span + 2 * padding))
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    mid_x, mid_y = (x_low + x_high) / 2, (y_low + y_high) / 2

    def project(x, y):
        return center_x + (x - mid_x) * scale, center_y - (y - mid_y) * scale

    def inverse(x, y):
        return mid_x + (x - center_x) / scale, mid_y - (y - center_y) / scale

    return project, inverse, x_span, y_span


def _summary(root, report):
    totals = report["totals"]
    group = _node(root, "g", id="summary", data_segment_count=report["source"]["segment_count"],
                  data_point_count=totals["point_count"], **{
                      "data_stat_" + key: repr(totals[key]) for key in _STAT_KEYS
                  })
    _line(group, 50, 143, 1150, 143, stroke=_TEAL, stroke_width="2")
    _line(group, 50, 259, 1150, 259, stroke=_GRID, stroke_width="1")
    for x in (335, 617, 858):
        _line(group, x, 164, x, 237, stroke=_GRID, stroke_width="1")
    _text(group, 50, 174, "DISTÂNCIA APROXIMADA", size=12, fill=_MUTED, weight="600")
    _text(group, 50, 216, "≈ " + _label(totals["distance_m"] / 1000) + " km", size=32, weight="600")
    _text(group, 357, 174, "SUBIDA OBSERVADA", size=12, fill=_MUTED, weight="600")
    _text(group, 357, 207, "+" + _label(totals["ascent_m"], 1) + " m", size=24, weight="600")
    _text(group, 357, 232, "Descida: " + _label(totals["descent_m"], 1) + " m", size=14, fill=_MUTED)
    _text(group, 639, 174, "PONTOS / SEGMENTOS", size=12, fill=_MUTED, weight="600")
    _text(group, 639, 210, str(totals["point_count"]) + " / " + str(report["source"]["segment_count"]),
          size=28, weight="600")
    _text(group, 639, 232, str(totals["edge_count"]) + " arestas internas", size=13, fill=_MUTED)
    _text(group, 880, 174, "COBERTURA POR ARESTA", size=12, fill=_MUTED, weight="600")
    edges = str(totals["edge_count"])
    _text(group, 880, 204, "Elevação: " + str(totals["elevation_edges"]) + " / " + edges, size=15)
    _text(group, 880, 230, "Tempo utilizável: " + str(totals["usable_time_edges"]) + " / " + edges, size=15)
    _text(group, 880, 249, "Inválidas: " + str(totals["invalid_time_edges"]) + " · longas: " + str(totals["gap_time_edges"]), size=12, fill=_MUTED)


def _route(root, model):
    points = [point for segment in model.segments for point in segment.points]
    seam = _seam(points)
    parts = [_route_parts(segment.points, seam) for segment in model.segments]
    project, inverse, longitude_span, latitude_span = _route_projection(parts)
    group = _node(root, "g", id="route", data_seam_deg=repr(seam),
                  data_longitude_span_deg=repr(longitude_span), data_latitude_span_deg=repr(latitude_span))
    _text(group, 50, 299, "Trajeto esquemático · sem mapa base", size=23, weight="600")
    _text(group, 50, 323, "Latitude (°)", size=12, fill=_MUTED)
    left, top, right, bottom = _ROUTE_BOX
    start_longitude, start_latitude = inverse(left, bottom)
    end_longitude, end_latitude = inverse(right, top)
    longitude_digits = _tick_digits((end_longitude - start_longitude) / 4)
    latitude_digits = _tick_digits((end_latitude - start_latitude) / 4)
    for index in range(5):
        fraction = index / 4
        x, y = left + fraction * (right - left), bottom - fraction * (bottom - top)
        _line(group, x, top, x, bottom, stroke=_GRID, stroke_width="1")
        _line(group, left, y, right, y, stroke=_GRID, stroke_width="1")
        longitude, _ = inverse(x, bottom)
        _, latitude = inverse(left, y)
        _text(group, x, bottom + 20, _label((longitude + seam + 180) % 360 - 180, longitude_digits),
              size=11, fill=_MUTED, anchor="middle")
        _text(group, left - 12, y + 4, _label(latitude, latitude_digits), size=11, fill=_MUTED, anchor="end")
    _text(group, (left + right) / 2, 523, "Longitude (°; normalizada para exibição)",
          size=12, fill=_MUTED, anchor="middle")
    for segment, segment_parts in zip(model.segments, parts):
        child = _node(group, "g", id=f"route-t{segment.track_index}-s{segment.segment_index}",
                      data_track=segment.track_index, data_segment=segment.segment_index)
        for part in segment_parts:
            _path(child, [project(x, y) for x, y in part], "route-line", _NAVY)
        for index, point in enumerate(segment.points, 1):
            x, y = project(_turn(point.longitude - seam), point.latitude)
            _node(child, "circle", cx=_pixel(x), cy=_pixel(y), r="2.8", fill=_TEAL,
                  stroke="#ffffff", stroke_width="0.7", data_role="route-point", data_point=index,
                  data_longitude=repr(point.longitude), data_latitude=repr(point.latitude))
    if not points:
        _text(group, (left + right) / 2, (top + bottom) / 2, "Sem pontos de trilha",
              size=17, fill=_MUTED, anchor="middle")
    _text(group, 50, 551, "Projeção em graus; distorção em altas latitudes. Não usar para navegação.",
          size=12, fill=_MUTED)


def _profile(root, model, report):
    total_distance = report["totals"]["distance_m"]
    group = _node(root, "g", id="profile", data_distance_m=repr(total_distance))
    _line(group, 50, 572, 1150, 572, stroke=_GRID, stroke_width="1")
    _text(group, 50, 606, "Perfil altimétrico", size=23, weight="600")
    _text(group, 50, 630, "Elevação registrada (m)", size=12, fill=_MUTED)
    elevations = [point.elevation_m for segment in model.segments for point in segment.points
                  if point.elevation_m is not None]
    low, high = (min(elevations), max(elevations)) if elevations else (0.0, 0.0)
    padding = (high - low) * 0.08 if high > low else max(1.0, abs(low) * 0.05)
    low, high = low - padding, high + padding
    left, top, right, bottom = _PROFILE_BOX

    def project(distance, elevation):
        x = left + distance / total_distance * (right - left) if total_distance else (left + right) / 2
        return x, bottom - (elevation - low) / (high - low) * (bottom - top)

    for index in range(5):
        fraction = index / 4
        x, y = left + fraction * (right - left), bottom - fraction * (bottom - top)
        _line(group, x, top, x, bottom, stroke=_GRID, stroke_width="1")
        _line(group, left, y, right, y, stroke=_GRID, stroke_width="1")
        _text(group, x, bottom + 20, _label(total_distance * fraction / 1000,
                                         _tick_digits(total_distance / 4000, minimum=2)),
              size=11, fill=_MUTED, anchor="middle")
        if elevations:
            _text(group, left - 12, y + 4, _label(low + fraction * (high - low), 1),
                  size=11, fill=_MUTED, anchor="end")
    _text(group, (left + right) / 2, 819, "Distância acumulada (km)",
          size=12, fill=_MUTED, anchor="middle")
    offset = 0.0
    for segment in model.segments:
        child = _node(group, "g", id=f"profile-t{segment.track_index}-s{segment.segment_index}",
                      data_track=segment.track_index, data_segment=segment.segment_index)
        local_distance = 0.0
        run = []
        if segment.points:
            boundary_x = project(offset, low)[0]
            _line(child, boundary_x, top, boundary_x, bottom, stroke="#a3b6c1", stroke_width="1",
                  stroke_dasharray="3 4", data_role="segment-boundary")
        previous = None
        for index, point in enumerate(segment.points, 1):
            if previous is not None:
                local_distance += _distance(previous, point)
            distance = offset + local_distance
            if point.elevation_m is None:
                _path(child, run, "profile-line", _TEAL)
                run = []
            else:
                x, y = project(distance, point.elevation_m)
                run.append((x, y))
                _node(child, "circle", cx=_pixel(x), cy=_pixel(y), r="2.8", fill=_TEAL,
                      stroke="#ffffff", stroke_width="0.7", data_role="profile-point", data_point=index,
                      data_distance_m=repr(distance), data_elevation_m=repr(point.elevation_m))
            previous = point
        _path(child, run, "profile-line", _TEAL)
        offset += local_distance
    if not report["totals"]["point_count"]:
        message = "Sem pontos de trilha"
    elif not elevations:
        message = "Sem elevação registrada"
    else:
        message = None
    if message:
        _text(group, (left + right) / 2, (top + bottom) / 2, message,
              size=17, fill=_MUTED, anchor="middle")


def _inventory(root, model):
    group = _node(root, "g", id="inventory")
    _line(group, 50, 842, 1150, 842, stroke=_GRID, stroke_width="1")
    _text(group, 50, 871, "SEGMENTOS", size=12, fill=_MUTED, weight="600")
    identifiers = [f"t{segment.track_index}-s{segment.segment_index}" for segment in model.segments[:8]]
    _text(group, 50, 898, " · ".join(identifiers) if identifiers else "Nenhum segmento", size=14)
    _text(group, 1150, 898, str(max(0, len(model.segments) - 8)) + " segmentos omitidos do inventário",
          size=12, fill=_MUTED, anchor="end")
    _text(group, 50, 940, "Ausências interrompem o perfil; segmentos não são conectados. Coordenadas e elevações permanecem expostas.",
          size=12, fill=_MUTED)


def to_svg(gpx: GPX, *, max_gap_seconds=300.0, moving_threshold_kmh=1.0) -> str:
    """Crie um relatório passivo e determinístico; limite UTF-8 de 32 MiB.

    As opções e os modelos usam a validação de ``analyze``. Elevações ausentes
    interrompem o perfil. O trajeto circular é esquemático, sem escala métrica.
    Nenhum texto livre, nome, criador ou horário do GPX é incluído no documento.
    """
    report = analyze(gpx, max_gap_seconds=max_gap_seconds, moving_threshold_kmh=moving_threshold_kmh)
    model = _validated(gpx)
    root = ET.Element("svg", {
        "xmlns": "http://www.w3.org/2000/svg", "width": "1200", "height": "960",
        "viewBox": "0 0 1200 960", "role": "img", "aria-labelledby": "report-title report-description",
        "font-family": "sans-serif",
    })
    _node(root, "title", id="report-title", text="Relatório de trilha GPX")
    _node(root, "desc", id="report-description", text=(
        "Resumo, trajeto esquemático, perfil altimétrico e inventário de segmentos. "
        "Medições ausentes não são interpoladas. Coordenadas e elevações permanecem expostas."
    ))
    _node(root, "rect", x="0", y="0", width="1200", height="960", fill="#ffffff")
    _text(root, 50, 45, "TRILHAS GPX / RELATÓRIO LOCAL", size=12, fill=_TEAL, weight="600")
    _text(root, 50, 95, "Leitura do percurso", size=39, weight="600")
    _text(root, 50, 122, "Distâncias aproximadas · medições observadas · segmentos preservados", size=15, fill=_MUTED)
    _summary(root, report)
    _route(root, model)
    _profile(root, model, report)
    _inventory(root, model)
    document = ET.tostring(root, encoding="unicode", short_empty_elements=True) + "\n"
    if len(document.encode("utf-8")) > MAX_SVG_BYTES:
        raise GPXError("LIMIT_EXCEEDED")
    return document
