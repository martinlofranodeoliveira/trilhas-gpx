# Método e limitações

## Distância horizontal

Cada par de pontos adjacentes do **mesmo segmento** contribui com a distância esférica Haversine, raio `R=6371008.8 m`:

`a = sin²((lat2-lat1)/2) + cos(lat1) cos(lat2) sin²((lon2-lon1)/2)`

`d = 2R asin(sqrt(a))`, com `a` limitado a `[0,1]` para estabilidade numérica. Ângulos internos são radianos. O caminho curto contempla o antimeridiano. Não se somam ligações entre segmentos ou trilhas, nem a distância vertical. Soma é em metros, com aritmética de ponto flutuante.

GPX usa coordenadas WGS84 e unidades métricas, mas esta implementação **não** calcula uma geodésica sobre o elipsoide WGS84. É aproximação esférica, não medição cadastral/topográfica. Frequência de amostragem, curvas entre pontos, ruído e falhas do aparelho alteram o resultado.

## Elevação

Somente pares com duas elevações contribuem. Diferença positiva soma subida, negativa soma descida em módulo. Não há suavização, limiar ou correção de altitude. Uma elevação ausente interrompe o cálculo; não é substituída por zero nem ligada à próxima conhecida. `elevation_edges` explicita a cobertura. Um percurso com ruído pode acumular subida artificialmente alta.

## Horários e velocidade

Normalize offsets para UTC e observe cada aresta:

1. Horário ausente, igual ou decrescente: inválida/ausente.
2. Diferença positiva maior que o máximo configurado: intervalo longo (`gap`).
3. Diferença positiva até o máximo, inclusive: utilizável.

As três contagens particionam `edge_count`. A velocidade média é `usable_distance_m / usable_time_s * 3.6`. Distância de arestas inválidas/gaps **não** entra nesse numerador. Para movimento, conservam-se apenas arestas utilizáveis com velocidade `>= moving_threshold_kmh`. Limiar zero inclui também arestas estacionárias com tempo utilizável. Médias sem tempo são `null`, não zero.

`elapsed_span_s` mede a diferença entre o maior e menor horário conhecido. Inclui pausas e intervalos entre segmentos; pode existir mesmo sem uma única aresta temporal utilizável. Não o confunda com tempo de gravação contínuo ou tempo em movimento. Reordenação de timestamps não reordena pontos.

## Interoperabilidade e privacidade

O parser lê o subconjunto de trilhas GPX 1.1 documentado; não valida toda a ordem/cobertura do XSD nem aceita GPX1.0 silenciosamente. Rotas/pontos avulsos não são trilhas. Extensões podem transportar outros sensores, mas não são interpretadas. Dados ausentes continuam ausentes.

GeoJSON preserva interrupções e usa corte linear de coordenadas no antimeridiano. `bounds` não é uma caixa geográfica mínima circular. Os exemplos são sintéticos. Não há upload automático; CSV, JSON e GeoJSON podem revelar coordenadas, horários e nomes conforme seu formato.

Não use estes números para afirmar segurança, dificuldade, esforço, aptidão, clima ou precisão de equipamento. Nenhum serviço externo ou modelo de IA é chamado pelo pacote.

## Referências primárias

- [GPX1.1, namespace, trilhas, coordenadas e unidades](https://www.topografix.com/GPX/1/1/).
- [RFC7946: coordenadas, geometrias e antimeridiano](https://datatracker.ietf.org/doc/html/rfc7946).
- [Python: cuidados com XML não confiável](https://docs.python.org/3/library/xml.html#xml-security).

O código e as fixtures são originais; as referências não constituem certificação deste parser.
