# API e formatos · 0.1.0

Importe de `trilhas_gpx`. Modelos `dataclass(frozen=True)` são imutáveis; coleções usam tuplas.

```python
Point(latitude, longitude, elevation_m=None, time=None)
Segment(track_index, segment_index, name, points)
GPX(creator, segments, track_count, ignored_waypoints=0, ignored_routes=0)
parse_gpx(data: bytes) -> GPX
analyze(gpx, *, max_gap_seconds=300.0, moving_threshold_kmh=1.0) -> dict
to_geojson(gpx) -> dict
points_csv(gpx) -> str
```

`parse_gpx` exige bytes UTF-8, BOM opcional. Coordenadas usam graus decimais, elevação metros e horários UTC conscientes de fuso. Horários de origem devem ter `Z` ou offset explícito; valores sem fuso, leap seconds e frações com mais de seis dígitos são recusados. Números GPX são decimais sem expoente, `NaN` ou infinito. A faixa é verificada em decimal antes de converter para float. Quando longitude decimal válida imediatamente abaixo de180 arredondaria para180, usa-se o float representável imediatamente abaixo do limite;180 exato continua inválido. Isso é representação aproximada, não preservação de todos os dígitos decimais originais.

Trilhas/segmentos e pontos conservam ordem de entrada. Os índices começam em **1** e o índice de segmento reinicia em cada trilha. Tracks sem segmentos são representados em `track_count`. Segmentos vazios permanecem no modelo. A API valida também modelos construídos manualmente: tipos, finitude, tuplas, índices e contagens coerentes; `bool` não substitui número/índice.

## JSON da análise

`schema_version=1`, `method` (raio da esfera e parâmetros), `source` (creator e contagens), `totals` e `segments`. Cada segmento acrescenta `track_index`, `segment_index` e `name` às estatísticas.

| Campo de estatística | Significado |
|---|---|
| `point_count`, `edge_count` | Pontos e pares adjacentes dentro de segmentos |
| `distance_m` | Distância horizontal aproximada de todas as arestas |
| `ascent_m`, `descent_m` | Soma de diferenças positivas/negativas de elevação disponível |
| `elevation_edges`, `missing_elevation_edges` | Arestas com dois extremos de elevação ou com ausência |
| `usable_time_edges`, `invalid_time_edges`, `gap_time_edges` | Partição das arestas segundo cobertura/ordem temporal e intervalo máximo |
| `usable_time_s`, `usable_distance_m` | Somas apenas nas arestas temporais utilizáveis |
| `moving_time_s`, `moving_distance_m` | Subconjunto com velocidade maior ou igual ao limiar |
| `average_speed_kmh`, `moving_speed_kmh` | Quociente das grandezas correspondentes; `null` sem denominador |
| `start_time`, `end_time`, `elapsed_span_s` | Mínimo/máximo dos horários conhecidos e diferença; `null` sem horários |
| `bounds` | `[minlon,minlat,maxlon,maxlat]`, ou `null` sem pontos |

`source`: `creator`, `track_count`, `segment_count`, `point_count`, `ignored_waypoints`, `ignored_routes`. Não lê nomes de arquivos, localizações externas ou dados do sistema.

`bounds` é uma caixa numérica, podendo ser muito ampla no antimeridiano. Os floats não são arredondados no JSON; isso não significa precisão real equivalente. Nenhum valor infinito/NaN é emitido.

## CSV

Cabeçalho fixo:

```csv
track,segment,point,latitude,longitude,elevation_m,time_utc,distance_m
```

Uma linha por ponto, na ordem original. Distância cumulativa reinicia em **0 em cada segmento**, latitude/longitude mantêm sua ordem nomeada no CSV e ausências são campos vazios. Horário é UTC com `Z`, quebra de linha LF. Nome/creator e outros textos livres não entram no CSV. Campos numéricos usam representação Python de float, sem arredondamento adicional.

## GeoJSON

FeatureCollection; um Feature por segmento, com ID `t1-s1` etc. Properties: `track_index`, `segment_index`, `name`, `point_count`. Geometria `null` para segmento vazio, Point com um ponto, LineString com dois ou mais, MultiLineString quando exige corte no antimeridiano. Posições são **`[longitude,latitude]`**, acrescentando elevação somente quando **todos** os pontos daquele segmento a possuem. Sem geometria de conexão entre segmentos.

O corte de antimeridiano interpola latitude/elevação linearmente em coordenadas, introduz pontos em `180` e `-180` e preserva os pontos originais. Não é uma interpolação geodésica. A geometria não contém horários/creator; properties podem conter o nome fornecido no GPX. Não há CRS alternativo ou tile de mapa.

## Limites inclusivos

| Item | Limite |
|---|---|
| Entrada | 8 MiB (sem descompressão automática) |
| XML | profundidade 32, 200.000 elementos, texto por elemento 4.096 caracteres |
| Trilhas / segmentos / pontos | 100 / 1.000 / 50.000 |
| Creator / nome de trilha | 256 caracteres |
| Número decimal GPX | 32 caracteres |
| Latitude / longitude | `[-90,90]` / `[-180,180)` |
| Elevação | `[-12000,100000]` metros |
| Saída da CLI | 32 MiB antes de publicar |

Campos extra/extensions são ignorados para análise, mas continuam sujeitos aos limites XML. DTD e entidades declaradas são rejeitadas; entidades XML predefinidas, como `&amp;`, são texto normal. XInclude não é executado. Não há processamento de links ou arquivos referidos pelo documento.

## Erros

`GPXError(ValueError)` tem `.code`. Mensagens não repetem coordenadas, texto ou caminhos de entrada. `XML_UNSAFE` para DTD/entidades; `XML_INVALID` para encoding/XML inválido; `GPX_FORMAT` para root/versão/creator/estrutura de campos inválidos; `COORD_INVALID`, `ELEVATION_INVALID`, `TIME_INVALID` para valores; `LIMIT_EXCEEDED`, `MODEL_INVALID`, `OPTION_INVALID` para limites/modelos/opções. Campo XML `time` duplicado é `GPX_FORMAT`, valor temporal inválido é `TIME_INVALID`.

Na CLI: sucesso exit0; falha exit2 com `{ "error": { "code": "...", "message": "..." } }` no stderr. Acrescenta `ARGUMENT_ERROR`, `IO_ERROR`, `OUTPUT_EXISTS`. Nenhuma saída de resultado é publicada se parsing/análise falhar. Destino existente também é recusado quando é symlink, inclusive quebrado. O protocolo exclusivo usa temporário no mesmo diretório e hard link; sistemas sem suporte podem retornar `IO_ERROR`.
