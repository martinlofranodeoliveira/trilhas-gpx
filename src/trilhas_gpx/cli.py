"""CLI local; saída exclusiva, sem modificar o GPX de entrada."""
from __future__ import annotations

import argparse
import errno
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile

from . import __version__
from .core import GPXError, analyze, parse_gpx, points_csv, to_geojson

MAX_INPUT = 8 << 20
MAX_OUTPUT = 32 << 20


class CommandError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CommandError('ARGUMENT_ERROR', 'Argumentos inválidos; consulte --help.')


def _number(value: str) -> float:
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise CommandError('OPTION_INVALID', 'Opção numérica inválida.') from None
    if not math.isfinite(result):
        raise CommandError('OPTION_INVALID', 'Opção numérica inválida.')
    return result


def _check_destination(path: Path):
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise CommandError('OUTPUT_EXISTS', 'O destino já existe; escolha outro arquivo.')


def _read(source: str) -> bytes:
    if source == '-':
        data = sys.stdin.buffer.read(MAX_INPUT + 1)
    else:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise CommandError('IO_ERROR', 'A entrada deve ser um arquivo regular sem link simbólico.')
            if info.st_size > MAX_INPUT:
                raise CommandError('LIMIT_EXCEEDED', 'Entrada acima do limite de tamanho.')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                data = stream.read(MAX_INPUT + 1)
        finally:
            os.close(fd)
    if len(data) > MAX_INPUT:
        raise CommandError('LIMIT_EXCEEDED', 'Entrada acima do limite de tamanho.')
    return data


def _publish(path: Path, data: bytes):
    """Link exclusivo torna o arquivo completo visível sem sobrescrever destino."""
    _check_destination(path)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.trilhas-gpx-', suffix='.tmp', dir=path.parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            raise CommandError('OUTPUT_EXISTS', 'O destino já existe; escolha outro arquivo.') from None
    finally:
        if temporary is not None:
            os.unlink(temporary)


def _summary(report: dict) -> str:
    s, t = report['source'], report['totals']
    speed = 'não disponível' if t['average_speed_kmh'] is None else f"{t['average_speed_kmh']:.2f} km/h"
    return '\n'.join([
        'Trilhas GPX · LOFRANO TECNOLOGIA',
        f"Trilhas: {s['track_count']} | segmentos: {s['segment_count']} | pontos: {s['point_count']}",
        f"Distância horizontal aproximada: {t['distance_m'] / 1000:.3f} km",
        f"Subida observada: {t['ascent_m']:.1f} m | descida observada: {t['descent_m']:.1f} m",
        f"Arestas com elevação: {t['elevation_edges']}/{t['edge_count']}",
        f"Tempo utilizável: {t['usable_time_s']:.3f} s | média nesse trecho: {speed}",
        f"Arestas temporais: {t['usable_time_edges']} utilizáveis, {t['invalid_time_edges']} inválidas/ausentes, {t['gap_time_edges']} com intervalo longo",
        f"Pontos avulsos ignorados: {s['ignored_waypoints']} | rotas ignoradas: {s['ignored_routes']}",
        'Modelo esférico aproximado; não conecta segmentos e não preenche dados ausentes.',
        'Não é ferramenta de navegação nem garantia de precisão do GPS.',
        '',
    ])


def main(argv=None) -> int:
    parser = Parser(description='Analise um GPX 1.1 local. Dados não são enviados a serviços externos.')
    parser.add_argument('input', metavar='INPUT', help='Arquivo regular GPX UTF-8, ou - para stdin explícito.')
    parser.add_argument('--version', action='version', version=f'trilhas-gpx {__version__}')
    parser.add_argument('--format', choices=['summary', 'json', 'csv', 'geojson'], default='summary', help='Formato da saída (padrão: summary).')
    parser.add_argument('--output', type=Path, help='Novo arquivo de saída; nunca sobrescreve existentes.')
    parser.add_argument('--max-gap-seconds', default='300', help='Intervalo máximo utilizável entre horários, em segundos (0, 86400].')
    parser.add_argument('--moving-threshold-kmh', default='1', help='Velocidade mínima para tempo em movimento, em km/h [0, 1000].')
    try:
        args = parser.parse_args(argv)
        max_gap, threshold = _number(args.max_gap_seconds), _number(args.moving_threshold_kmh)
        if not 0 < max_gap <= 86400 or not 0 <= threshold <= 1000:
            raise CommandError('OPTION_INVALID', 'Opção numérica fora dos limites.')
        if args.output is not None:
            _check_destination(args.output)
        book = parse_gpx(_read(args.input))
        report = analyze(book, max_gap_seconds=max_gap, moving_threshold_kmh=threshold)
        if args.format == 'summary':
            text = _summary(report)
        elif args.format == 'csv':
            text = points_csv(book)
        else:
            document = report if args.format == 'json' else to_geojson(book)
            text = json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
        data = text.encode('utf-8')
        if len(data) > MAX_OUTPUT:
            raise CommandError('LIMIT_EXCEEDED', 'Saída acima do limite de tamanho.')
        if args.output is None:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        else:
            _publish(args.output, data)
        return 0
    except (CommandError, GPXError) as exc:
        error = {'error': {'code': exc.code, 'message': str(exc)}}
    except OSError:
        # The interpreter flushes stdout again at shutdown, even after a failed
        # write/flush (EPIPE, ENOSPC...). Keep our documented JSON/exit2 result.
        try:
            null_fd = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(null_fd, sys.stdout.fileno())
            finally:
                os.close(null_fd)
        except (OSError, ValueError):
            pass
        error = {'error': {'code': 'IO_ERROR', 'message': 'Não foi possível ler a entrada ou publicar a saída.'}}
    sys.stderr.write(json.dumps(error, ensure_ascii=False) + '\n')
    return 2
