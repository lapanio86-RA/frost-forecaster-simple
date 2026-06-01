# Frost Forecaster Simple

Previsor simples de **risco de geada** para o Sul do Brasil, com interface desktop em Tkinter e saída em mapas PNG + tabelas CSV.

O projeto foi pensado para ser leve, fácil de rodar e fácil de compartilhar no GitHub. Ele não usa Streamlit, navegador, servidor local, Cartopy, GeoPandas ou Shapely.

## O que ele faz

- Consulta previsão horária da Open-Meteo ou usa dados demo offline.
- Calcula um **índice meteorológico de risco de geada** para noites futuras.
- Gera mapas PNG e arquivos CSV em uma pasta `outputs/`.
- Sobrepõe divisas estaduais do Brasil usando GeoJSON do IBGE, baixado e cacheado automaticamente.

O índice vai de `0` a `1`, mas **não é uma probabilidade estatística calibrada**. Ele é uma heurística baseada em:

- temperatura baixa;
- ponto de orvalho / umidade;
- vento fraco;
- pouca nebulosidade.

## Como rodar

Requer Python 3.10+.

```bash
pip install -r requirements.txt
python main.py
```

No Windows, também é possível usar:

```bat
run_dev_windows.bat
```

## Como gerar um `.exe` único no Windows

```bat
build_onefile_windows.bat
```

O executável será gerado em:

```text
dist\FrostForecasterSimple.exe
```

Esse arquivo pode ser enviado para amigos. Ao abrir, aparece a janela do app.

## Saídas geradas

Para cada noite processada, o programa cria arquivos como:

```text
outputs/
  geada_risco_YYYYMMDD.png
  temp_min_YYYYMMDD.png
  dew_min_YYYYMMDD.png
  rh_max_YYYYMMDD.png
  wind_min_YYYYMMDD.png
  cloud_mean_YYYYMMDD.png
  geada_dados_YYYYMMDD.csv
  resumo_geada.csv
```

## Configuração recomendada

Para começar:

- Região: `south_core`
- Resolução: `0.5°`
- Noites: `5`
- Fonte: `Demo offline` para testar sem internet; depois `Previsão real`

Para alta resolução na Serra SC/RS:

- Região: `serra`
- Resolução: `0.25°`

Evite usar resolução muito fina em uma área muito grande, porque APIs públicas podem limitar muitas consultas em sequência.

## Estrutura mínima do projeto

```text
main.py                         GUI Tkinter
main.pyw                        entrada sem console no Windows
frost_core.py                   coleta de dados e cálculo do risco
plot_output.py                  geração de PNGs e CSVs
map_boundaries.py               download/cache/desenho das divisas políticas
requirements.txt                dependências para rodar
requirements-build.txt          dependências para gerar .exe
run_dev_windows.bat             atalho para rodar no Windows
build_onefile_windows.bat       build do executável Windows
.gitignore
LICENSE
README.md
```

## Fonte dos dados

- Previsão meteorológica: Open-Meteo.
- Divisas políticas: API de Malhas Geográficas do IBGE.

## Licença

MIT.
