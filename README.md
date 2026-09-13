# AOP-Wiki API

A REST API for the [AOP-Wiki RDF](https://github.com/marvinm2/AOPWikiRDF) data: Adverse Outcome
Pathways, Key Events, Key Event Relationships, stressors, chemicals and genes, served as JSON or CSV.

It is the successor of the grlc-based AOP-Wiki API (built from
[AOPWikiQueries](https://github.com/marvinm2/AOPWikiQueries)). The old grlc URLs
(`/api-git/marvinm2/AOPWikiQueries/<query>`) keep working through a compatibility layer.

- Interactive documentation: `/docs` (OpenAPI at `/openapi.json`)
- Data source: the AOP-Wiki RDF SPARQL endpoint, refreshed weekly
- Data licence: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), as the AOP-Wiki itself

## Quick start

```bash
curl -s "https://aopwiki.api.bigcat-bioinformatics.org/v1/dataset"
curl -s -H "Accept: text/csv" "https://aopwiki.api.bigcat-bioinformatics.org/v1/aops?limit=10"
```

## Development

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/pytest                       # unit and API tests (mocked SPARQL endpoint)
.venv/bin/pytest -m live               # against the public endpoint
SPARQL_ENDPOINT=https://aopwiki.rdf.bigcat-bioinformatics.org/sparql \
  .venv/bin/uvicorn app.main:app --reload
```

Configuration is read from environment variables; see `app/config.py`. SPARQL queries live in
`queries/` as `.rq` templates (conventions in `queries/README.md`).

## Issues

Questions, bugs and requests: [GitHub Issues](https://github.com/marvinm2/AOP-Wiki-API/issues).
