"""Análise local de GPX 1.1, sem interpolar medições ausentes.

As distâncias usam uma esfera de raio fixo; são aproximações de cálculo,
não uma declaração de precisão de um receptor GPS.
"""

from __future__ import annotations

import codecs
import csv
import io
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from xml.parsers import expat


EARTH_RADIUS_M = 6_371_008.8
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 32
MAX_ELEMENTS = 200_000
MAX_POINTS = 50_000
MAX_TRACKS = 100
MAX_SEGMENTS = 1_000
MAX_TEXT = 4_096
MAX_LABEL = 256
MAX_NUMBER = 32
_NS = "http://www.topografix.com/GPX/1/1}"
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")
_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)
_MESSAGES = {
    "XML_UNSAFE": "Construção XML não permitida.",
    "XML_INVALID": "XML ou codificação inválidos.",
    "GPX_FORMAT": "Estrutura GPX 1.1 inválida.",
    "LIMIT_EXCEEDED": "Limite de processamento excedido.",
    "COORD_INVALID": "Coordenada inválida.",
    "ELEVATION_INVALID": "Elevação inválida.",
    "TIME_INVALID": "Horário inválido.",
    "MODEL_INVALID": "Modelo GPX inválido.",
    "OPTION_INVALID": "Opção de análise inválida.",
}


class GPXError(ValueError):
    """Erro previsível, com código estável e mensagem sem dados de entrada."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(_MESSAGES.get(code, "Erro GPX."))


@dataclass(frozen=True)
class Point:
    latitude: float
    longitude: float
    elevation_m: float | None = None
    time: datetime | None = None


@dataclass(frozen=True)
class Segment:
    track_index: int
    segment_index: int
    name: str
    points: tuple[Point, ...]


@dataclass(frozen=True)
class GPX:
    creator: str
    segments: tuple[Segment, ...]
    track_count: int
    ignored_waypoints: int = 0
    ignored_routes: int = 0


def _number(text: str | None, low: float, high: float, code: str, *, upper_open=False) -> float:
    if text is None:
        raise GPXError(code)
    value = text.strip()
    if len(value) > MAX_NUMBER:
        raise GPXError("LIMIT_EXCEEDED")
    if not _DECIMAL.fullmatch(value):
        raise GPXError(code)
    exact = Decimal(value)
    if exact < low or exact > high or (upper_open and exact == high):
        raise GPXError(code)
    number = float(value)
    if upper_open and number == high:
        # The exact decimal is inside the domain; preserve that fact when its
        # nearest binary float lands on the excluded upper endpoint.
        number = math.nextafter(float(high), -math.inf)
    if not math.isfinite(number) or number < low or number > high:
        raise GPXError(code)
    return number


def _utc(value: datetime, code: str) -> datetime:
    try:
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise GPXError(code)
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError, TypeError):
        raise GPXError(code) from None


def _time(text: str) -> datetime:
    value = text.strip()
    if not _TIME.fullmatch(value):
        raise GPXError("TIME_INVALID")
    if int(value[11:13]) > 23 or int(value[14:16]) > 59 or int(value[17:19]) > 59:
        raise GPXError("TIME_INVALID")
    # datetime accepts offsets with minute overflow; RFC3339 does not.
    if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise GPXError("TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        raise GPXError("TIME_INVALID") from None
    return _utc(parsed, "TIME_INVALID")


@dataclass
class _Track:
    index: int
    name: str = ""
    name_seen: bool = False
    segments: list = field(default_factory=list)


@dataclass
class _Segment:
    index: int
    points: list = field(default_factory=list)


@dataclass
class _Point:
    latitude: float
    longitude: float
    elevation: float | None = None
    time: datetime | None = None
    seen: set = field(default_factory=set)


@dataclass
class _Frame:
    kind: str
    value: object = None
    text_count: int = 0
    chunks: list | None = None


def parse_gpx(data: bytes) -> GPX:
    """Leia apenas bytes UTF-8, com limites inclusivos e sem I/O externo.

    Expat processa blocos e os callbacks conservam apenas o modelo necessário.
    Metadados ignorados também passam pelos limites de elementos/texto/profundidade.
    """
    if type(data) is not bytes:
        raise GPXError("GPX_FORMAT")
    if len(data) > MAX_INPUT_BYTES:
        raise GPXError("LIMIT_EXCEEDED")
    frames: list[_Frame] = []
    segments: list[Segment] = []
    counts = {"elements": 0, "tracks": 0, "segments": 0, "points": 0, "wpt": 0, "rte": 0}
    creator = ""
    root_format_error = False
    # Bytes are independently checked as strict UTF-8 below. Fixing Expat's
    # protocol encoding also accepts the contract's UTF8 declaration alias.
    parser = expat.ParserCreate(encoding="UTF-8", namespace_separator="}")

    def unsafe(*_args):
        raise GPXError("XML_UNSAFE")

    def declaration(version, encoding, standalone):
        if version != "1.0" or (encoding is not None and encoding.lower() not in ("utf-8", "utf8")):
            raise GPXError("XML_INVALID")

    def start(tag, attrs):
        nonlocal creator, root_format_error
        counts["elements"] += 1
        if counts["elements"] > MAX_ELEMENTS or len(frames) >= MAX_DEPTH:
            raise GPXError("LIMIT_EXCEEDED")
        frame = _Frame("ignored")
        if not frames:
            creator = attrs.get("creator", "")
            if len(creator) > MAX_LABEL:
                raise GPXError("LIMIT_EXCEEDED")
            root_format_error = (tag != _NS + "gpx" or attrs.get("version") != "1.1"
                                 or not creator.strip())
            # A truncated/non-XML document remains XML_INVALID even when its
            # root is also unsupported. Retain resource limits while ignoring
            # unsupported root contents until Expat confirms well-formedness.
            frame = _Frame("ignored" if root_format_error else "root")
        else:
            parent = frames[-1]
            if parent.kind in ("name", "ele", "time"):
                raise GPXError("GPX_FORMAT")
            if parent.kind == "root":
                if tag == _NS + "trk":
                    counts["tracks"] += 1
                    if counts["tracks"] > MAX_TRACKS:
                        raise GPXError("LIMIT_EXCEEDED")
                    frame = _Frame("track", _Track(counts["tracks"]))
                elif tag == _NS + "wpt":
                    counts["wpt"] += 1
                elif tag == _NS + "rte":
                    counts["rte"] += 1
            elif parent.kind == "track":
                track = parent.value
                if tag == _NS + "name":
                    if track.name_seen:
                        raise GPXError("GPX_FORMAT")
                    track.name_seen = True
                    frame = _Frame("name", track, chunks=[])
                elif tag == _NS + "trkseg":
                    counts["segments"] += 1
                    if counts["segments"] > MAX_SEGMENTS:
                        raise GPXError("LIMIT_EXCEEDED")
                    segment = _Segment(len(track.segments) + 1)
                    track.segments.append(segment)
                    frame = _Frame("segment", segment)
            elif parent.kind == "segment" and tag == _NS + "trkpt":
                counts["points"] += 1
                if counts["points"] > MAX_POINTS:
                    raise GPXError("LIMIT_EXCEEDED")
                frame = _Frame("point", _Point(
                    _number(attrs.get("lat"), -90, 90, "COORD_INVALID"),
                    _number(attrs.get("lon"), -180, 180, "COORD_INVALID", upper_open=True),
                ))
            elif parent.kind == "point" and tag in (_NS + "ele", _NS + "time"):
                kind = tag[len(_NS):]
                if kind in parent.value.seen:
                    raise GPXError("GPX_FORMAT")
                parent.value.seen.add(kind)
                frame = _Frame(kind, parent.value, chunks=[])
        frames.append(frame)

    def chars(text):
        if not frames:
            return
        frame = frames[-1]
        frame.text_count += len(text)
        if frame.text_count > MAX_TEXT:
            raise GPXError("LIMIT_EXCEEDED")
        if frame.chunks is not None:
            frame.chunks.append(text)

    def end(tag):
        frame = frames.pop()
        if frame.kind == "name":
            name = "".join(frame.chunks).strip()
            if len(name) > MAX_LABEL:
                raise GPXError("LIMIT_EXCEEDED")
            frame.value.name = name
        elif frame.kind == "ele":
            frame.value.elevation = _number("".join(frame.chunks), -12000, 100000, "ELEVATION_INVALID")
        elif frame.kind == "time":
            frame.value.time = _time("".join(frame.chunks))
        elif frame.kind == "point":
            point = frame.value
            frames[-1].value.points.append(Point(point.latitude, point.longitude, point.elevation, point.time))
        elif frame.kind == "track":
            track = frame.value
            segments.extend(Segment(track.index, seg.index, track.name, tuple(seg.points)) for seg in track.segments)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    parser.XmlDeclHandler = declaration
    parser.StartDoctypeDeclHandler = unsafe
    parser.EntityDeclHandler = unsafe
    parser.ExternalEntityRefHandler = unsafe
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    try:
        for offset in range(0, len(data), 65536):
            chunk = data[offset:offset + 65536]
            decoder.decode(chunk, final=False)
            parser.Parse(chunk, False)
        decoder.decode(b"", final=True)
        parser.Parse(b"", True)
    except UnicodeError:
        raise GPXError("XML_INVALID") from None
    except expat.ExpatError:
        # Expat does not dispatch EntityDeclHandler for a declaration outside
        # a DTD. Classify only the token at its actual syntax-error offset;
        # harmless ENTITY text in comments/CDATA must remain inert text.
        at = parser.ErrorByteIndex
        # In element content Expat points at E (after <!); at document level
        # it points at <. Both offsets are bytes, including across UTF-8 chunks.
        for start in (at, at - 2):
            token = data[start:start + 9] if start >= 0 else b""
            if token.startswith(b"<!ENTITY") and token[8:9] in (b" ", b"\t", b"\n", b"\r"):
                raise GPXError("XML_UNSAFE") from None
        raise GPXError("XML_INVALID") from None
    if root_format_error:
        raise GPXError("GPX_FORMAT")
    return GPX(creator, tuple(segments), counts["tracks"], counts["wpt"], counts["rte"])


def _finite(value, low, high, *, upper_open=False) -> float:
    if type(value) not in (int, float):
        raise GPXError("MODEL_INVALID")
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise GPXError("MODEL_INVALID") from None
    if not math.isfinite(number) or not low <= number <= high or (upper_open and number == high):
        raise GPXError("MODEL_INVALID")
    return number


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise GPXError("MODEL_INVALID")


def _validated(gpx: GPX) -> GPX:
    """Valide também modelos manuais; devolva uma cópia canônica sem mutação."""
    if type(gpx) is not GPX or type(gpx.segments) is not tuple:
        raise GPXError("MODEL_INVALID")
    if type(gpx.creator) is not str or not gpx.creator.strip() or len(gpx.creator) > MAX_LABEL:
        raise GPXError("MODEL_INVALID")
    _integer(gpx.track_count, 0, MAX_TRACKS)
    _integer(gpx.ignored_waypoints, 0, MAX_ELEMENTS)
    _integer(gpx.ignored_routes, 0, MAX_ELEMENTS)
    if len(gpx.segments) > MAX_SEGMENTS:
        raise GPXError("MODEL_INVALID")
    result = []
    point_count = 0
    field_nodes = 0
    named_tracks = set()
    previous_track = previous_segment = 0
    for segment in gpx.segments:
        if type(segment) is not Segment or type(segment.points) is not tuple:
            raise GPXError("MODEL_INVALID")
        _integer(segment.track_index, 1, gpx.track_count)
        _integer(segment.segment_index, 1, MAX_SEGMENTS)
        if (segment.track_index < previous_track or
                segment.segment_index != (previous_segment + 1 if segment.track_index == previous_track else 1)):
            raise GPXError("MODEL_INVALID")
        previous_track, previous_segment = segment.track_index, segment.segment_index
        if type(segment.name) is not str or len(segment.name) > MAX_LABEL:
            raise GPXError("MODEL_INVALID")
        if segment.name:
            named_tracks.add(segment.track_index)
        point_count += len(segment.points)
        if point_count > MAX_POINTS:
            raise GPXError("MODEL_INVALID")
        points = []
        for point in segment.points:
            if type(point) is not Point:
                raise GPXError("MODEL_INVALID")
            latitude = _finite(point.latitude, -90, 90)
            longitude = _finite(point.longitude, -180, 180, upper_open=True)
            elevation = None if point.elevation_m is None else _finite(point.elevation_m, -12000, 100000)
            time = None if point.time is None else _utc(point.time, "MODEL_INVALID")
            field_nodes += int(elevation is not None) + int(time is not None)
            points.append(Point(latitude, longitude, elevation, time))
        result.append(Segment(segment.track_index, segment.segment_index, segment.name, tuple(points)))
    # Even a model without retained metadata must fit its minimum XML node count.
    if (1 + gpx.track_count + len(result) + point_count + field_nodes + len(named_tracks)
            + gpx.ignored_waypoints + gpx.ignored_routes > MAX_ELEMENTS):
        raise GPXError("MODEL_INVALID")
    return GPX(gpx.creator, tuple(result), gpx.track_count, gpx.ignored_waypoints, gpx.ignored_routes)


def _option(value, low, high, *, lower_open=False) -> float:
    if type(value) not in (int, float):
        raise GPXError("OPTION_INVALID")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise GPXError("OPTION_INVALID") from None
    if not math.isfinite(result) or not low <= result <= high or (lower_open and result == low):
        raise GPXError("OPTION_INVALID")
    return result


def _distance(a: Point, b: Point) -> float:
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians((b.longitude - a.longitude + 180) % 360 - 180)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


_SUM_FIELDS = (
    "point_count", "edge_count", "distance_m", "ascent_m", "descent_m", "elevation_edges",
    "missing_elevation_edges", "usable_time_edges", "invalid_time_edges", "gap_time_edges",
    "usable_time_s", "usable_distance_m", "moving_time_s", "moving_distance_m",
)


def _empty_stats() -> dict:
    return {
        "point_count": 0, "edge_count": 0, "distance_m": 0.0, "ascent_m": 0.0,
        "descent_m": 0.0, "elevation_edges": 0, "missing_elevation_edges": 0,
        "usable_time_edges": 0, "invalid_time_edges": 0, "gap_time_edges": 0,
        "usable_time_s": 0.0, "usable_distance_m": 0.0, "moving_time_s": 0.0,
        "moving_distance_m": 0.0, "average_speed_kmh": None, "moving_speed_kmh": None,
        "start_time": None, "end_time": None, "elapsed_span_s": None, "bounds": None,
    }


def _finish(stats: dict, start: datetime | None, end: datetime | None):
    if stats["usable_time_s"]:
        stats["average_speed_kmh"] = stats["usable_distance_m"] / stats["usable_time_s"] * 3.6
    if stats["moving_time_s"]:
        stats["moving_speed_kmh"] = stats["moving_distance_m"] / stats["moving_time_s"] * 3.6
    stats["start_time"], stats["end_time"] = _iso(start), _iso(end)
    stats["elapsed_span_s"] = None if start is None else (end - start).total_seconds()


def analyze(gpx: GPX, *, max_gap_seconds=300.0, moving_threshold_kmh=1.0) -> dict:
    """Calcule estatísticas por aresta, sem ligar segmentos ou inferir campos."""
    gap = _option(max_gap_seconds, 0, 86400, lower_open=True)
    threshold = _option(moving_threshold_kmh, 0, 1000)
    model = _validated(gpx)
    totals = _empty_stats()
    segment_stats = []
    all_start = all_end = None
    for segment in model.segments:
        stats = _empty_stats()
        points = segment.points
        stats["point_count"], stats["edge_count"] = len(points), max(0, len(points) - 1)
        times = [p.time for p in points if p.time is not None]
        start, end = (min(times), max(times)) if times else (None, None)
        if start is not None:
            all_start = start if all_start is None else min(all_start, start)
            all_end = end if all_end is None else max(all_end, end)
        if points:
            stats["bounds"] = [min(p.longitude for p in points), min(p.latitude for p in points),
                               max(p.longitude for p in points), max(p.latitude for p in points)]
        for a, b in zip(points, points[1:]):
            distance = _distance(a, b)
            stats["distance_m"] += distance
            if a.elevation_m is None or b.elevation_m is None:
                stats["missing_elevation_edges"] += 1
            else:
                stats["elevation_edges"] += 1
                delta = b.elevation_m - a.elevation_m
                stats["ascent_m"] += max(0.0, delta)
                stats["descent_m"] += max(0.0, -delta)
            dt = None if a.time is None or b.time is None else (b.time - a.time).total_seconds()
            if dt is None or dt <= 0:
                stats["invalid_time_edges"] += 1
            elif dt > gap:
                stats["gap_time_edges"] += 1
            else:
                stats["usable_time_edges"] += 1
                stats["usable_time_s"] += dt
                stats["usable_distance_m"] += distance
                if distance / dt * 3.6 >= threshold:
                    stats["moving_time_s"] += dt
                    stats["moving_distance_m"] += distance
        _finish(stats, start, end)
        for key in _SUM_FIELDS:
            totals[key] += stats[key]
        bounds = stats["bounds"]
        if bounds is not None:
            old = totals["bounds"]
            totals["bounds"] = list(bounds) if old is None else [min(old[0], bounds[0]), min(old[1], bounds[1]),
                                                               max(old[2], bounds[2]), max(old[3], bounds[3])]
        segment_stats.append({"track_index": segment.track_index, "segment_index": segment.segment_index,
                              "name": segment.name, **stats})
    _finish(totals, all_start, all_end)
    return {"schema_version": 1,
            "method": {"earth_radius_m": EARTH_RADIUS_M, "max_gap_seconds": gap, "moving_threshold_kmh": threshold},
            "source": {"creator": model.creator, "track_count": model.track_count,
                       "segment_count": len(model.segments), "point_count": totals["point_count"],
                       "ignored_waypoints": model.ignored_waypoints, "ignored_routes": model.ignored_routes},
            "totals": totals, "segments": segment_stats}


def _geometry(points: tuple[Point, ...]) -> dict | None:
    if not points:
        return None
    use_ele = all(point.elevation_m is not None for point in points)
    positions = [[point.longitude, point.latitude] + ([point.elevation_m] if use_ele else []) for point in points]
    if len(positions) == 1:
        return {"type": "Point", "coordinates": positions[0]}
    parts = [[positions[0]]]
    crossed = False
    for a, b in zip(positions, positions[1:]):
        delta = b[0] - a[0]
        if abs(delta) <= 180:
            parts[-1].append(b)
            continue
        crossed = True
        boundary = 180.0 if delta < -180 else -180.0
        wrapped_lon = b[0] + (360 if delta < -180 else -360)
        ratio = (boundary - a[0]) / (wrapped_lon - a[0])
        # Endpoints keep their exact values, including an existing -180 seam.
        rest = list(a[1:]) if ratio == 0 else list(b[1:]) if ratio == 1 else [
            a[i] + ratio * (b[i] - a[i]) for i in range(1, len(a))
        ]
        parts[-1].append([boundary, *rest])
        parts.append([[-boundary, *rest], b])
    if crossed:
        return {"type": "MultiLineString", "coordinates": parts}
    return {"type": "LineString", "coordinates": positions}


def to_geojson(gpx: GPX) -> dict:
    """Exporte um Feature por segmento e corte arestas no antimeridiano."""
    model = _validated(gpx)
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": f"t{seg.track_index}-s{seg.segment_index}",
         "properties": {"track_index": seg.track_index, "segment_index": seg.segment_index,
                        "name": seg.name, "point_count": len(seg.points)},
         "geometry": _geometry(seg.points)} for seg in model.segments
    ]}


def points_csv(gpx: GPX) -> str:
    """Exporte os pontos em CSV LF, com distância reiniciada por segmento."""
    model = _validated(gpx)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("track", "segment", "point", "latitude", "longitude", "elevation_m", "time_utc", "distance_m"))
    for segment in model.segments:
        distance = 0.0
        previous = None
        for index, point in enumerate(segment.points, 1):
            if previous is not None:
                distance += _distance(previous, point)
            writer.writerow((segment.track_index, segment.segment_index, index,
                             repr(point.latitude), repr(point.longitude),
                             "" if point.elevation_m is None else repr(point.elevation_m),
                             _iso(point.time) or "", repr(distance)))
            previous = point
    return output.getvalue()
