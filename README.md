# Trilhas GPX

**Entenda o que seu registro de GPS realmente contém, sem enviá-lo para um serviço.**

Biblioteca e ferramenta de terminal da [LOFRANO TECNOLOGIA](https://lofranotecnologia.com.br) para arquivos **GPX 1.1**: distância horizontal aproximada, subida/descida observadas, cobertura de horários e exportações CSV/GeoJSON. Código aberto **MIT**, documentação em português e nenhuma dependência de execução além do Python.

## Um problema concreto

Uma gravação pode ter paradas, horários ausentes, elevações incompletas ou vários segmentos. Somar tudo como uma linha contínua pode inventar distância e velocidade. O Trilhas GPX mantém essas interrupções e separa a distância total das arestas que possuem tempo utilizável.

- Conserva trilhas e segmentos separados, inclusive segmentos vazios e com um ponto.
- Informa quantas arestas têm elevação, horários utilizáveis, horários inválidos/ausentes ou intervalo longo.
- Exporta pontos em CSV e segmentos em GeoJSON, cortando linhas no antimeridiano.
- Processa somente o arquivo fornecido; não captura GPS, não envia arquivos e não acessa mapas.
- Lê sem alterar o original e publica saídas completas **sem sobrescrever** arquivos existentes.

## Instalação local

Python **3.11–3.14**. A biblioteca usa a biblioteca padrão; a CLI e a publicação exclusiva de arquivos são voltadas a **Linux/macOS**. O verificador isolado e o CI requerem Linux.

```sh
git clone https://github.com/martinlofranodeoliveira/trilhas-gpx.git
cd trilhas-gpx
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

Não há pacote deste projeto publicado no PyPI. `setuptools` e `wheel` são ferramentas de construção, não dependências da análise. Para construção sem rede, prepare-as previamente e use `pip install --no-build-isolation .`.

## Primeiro uso com o exemplo fictício

```sh
trilhas-gpx examples/percurso-ficticio.gpx
trilhas-gpx examples/percurso-ficticio.gpx --format json
trilhas-gpx examples/percurso-ficticio.gpx --format csv --output pontos.csv
trilhas-gpx examples/percurso-ficticio.gpx --format geojson --output percurso.geojson
```

O exemplo tem dois segmentos de registro separados: **não** existe uma linha entre eles. O trajeto é sintético, não uma sugestão de rota real. O resultado completo de referência fica em [examples/resultado.json](examples/resultado.json).

Para usar stdin explicitamente:

```sh
cat examples/percurso-ficticio.gpx | python -m trilhas_gpx - --format json
```

### Opções

| Opção | Padrão | Significado |
|---|---|---|
| `--format` | `summary` | `summary`, `json`, `csv` ou `geojson` |
| `--output` | stdout | Arquivo novo; destino existente, inclusive symlink, é recusado |
| `--max-gap-seconds` | `300` | Arestas com intervalo maior são excluídas do cálculo de velocidade; intervalo permitido `(0,86400]` |
| `--moving-threshold-kmh` | `1` | Limiar inclusivo para classificar tempo em movimento, em `[0,1000]` km/h |
| `--version` / `--help` | — | Versão e ajuda |

A distância total continua incluindo arestas com intervalo longo ou horário ausente. **Velocidade média** utiliza somente distância e tempo das arestas temporais elegíveis. O tempo entre o primeiro e último horário é outro indicador, não o denominador dessa média. Veja [o método e suas limitações](docs/METODO.md).

## Usar como biblioteca

```python
from pathlib import Path
from trilhas_gpx import analyze, parse_gpx, to_geojson

registro = parse_gpx(Path("examples/percurso-ficticio.gpx").read_bytes())
resultado = analyze(registro, max_gap_seconds=300, moving_threshold_kmh=1)
print(resultado["totals"]["distance_m"])
print(resultado["totals"]["usable_time_edges"])
geojson = to_geojson(registro)
```

A API pura aceita bytes/modelos e devolve dados; não abre caminhos nem faz chamadas de rede. Consulte [API e formatos](docs/API.md) para modelos, campos, índices, códigos de erro e limites.

## Testes e distribuição

O CI testa Python 3.11, 3.12, 3.13 e 3.14. Constrói um **sdist**, constrói um wheel a partir dele, instala o wheel em ambiente separado e exercita a API/CLI instalada, fora do checkout no `PYTHONPATH`.

Em Linux com `bubblewrap`, `setpriv`, `pip`, `setuptools==78.1.1` e `wheel==0.46.3` preparados:

```sh
python3 -B scripts/check.py
```

O check usa namespace sem rede/home/credenciais, fonte e testes somente leitura, `CapEff=0`, `NoNewPrivs=1` e hashes de entrada antes/depois. Constrói apenas em diretórios temporários. O `sudo` utilizado nos runners GitHub efêmeros não deve ser copiado para o PC local. Os testes independentes privados da preparação não acompanham o repositório nem são contados como testes do CI.

## Limites honestos

- Distância por esfera de raio fixo: é uma aproximação, **não** geodésia elipsoidal ou medição topográfica.
- Subida/descida somam as diferenças disponíveis sem filtrar ruído do GPS. Não preenchem elevações ausentes.
- Não estima calorias, esforço, dificuldade, segurança, condições da trilha ou tempo futuro.
- Metadados extras, extensões, pontos avulsos (`wpt`) e rotas (`rte`) não entram nas trilhas; as duas últimas categorias são contabilizadas como ignoradas.
- Suporte a um subconjunto GPX 1.1, não validação XSD integral nem todos os arquivos exportados por todos os aparelhos.
- A CLI evita sobrescrita e arquivos parciais; não promete proteção contra um diretório de saída modificado por um adversário durante a operação.
- Exportações contêm coordenadas e podem revelar deslocamentos. O próprio usuário decide se as compartilha; não há upload neste projeto.

## Contribuição e licença

[Como contribuir](CONTRIBUTING.md) · [Mudanças](CHANGELOG.md) · [Fontes e atribuições](THIRD_PARTY_NOTICES.md) · [MIT](LICENSE).

Melhorias úteis devem incluir exemplos reproduzíveis fictícios e testes do comportamento. Compatibilidade com mais variantes GPX e relatórios visuais podem ser discutidos sem alterar silenciosamente o significado das métricas existentes.
