# SPARQL query templates

Every API endpoint is backed by one or more `.rq` files in this directory. A template is addressed by
its path without extension, e.g. `aops/list` for `aops/list.rq`.

## Conventions

```sparql
# summary: One-line description of what the query returns
# param: limit int
# param: status literal optional
PREFIX aopo: <http://aopkb.org/aop_ontology#>
SELECT ?aop
FROM <urn:aopwiki:graph>
WHERE {
  ?aop a aopo:AdverseOutcomePathway .
  # if: status
  ?aop <http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#C25688> ?__status .
  # endif
}
LIMIT ?__limit
```

- `# param: <name> <type> [optional]` declares a placeholder. Types: `int`, `literal`, `iri`,
  `iri_list`, `literal_list`. Placeholders are written `?__name`.
- Values are passed as typed terms (`app/sparql/terms.py`), which validate and escape them. Raw user
  input is never concatenated into a query.
- `# if: <name>` … `# endif` keeps the enclosed lines only when that optional parameter is given.
  Blocks do not nest, and an optional parameter may only be used inside its block.
- `<urn:aopwiki:graph>` is replaced with the configured data graph (`DATA_GRAPH`,
  default `http://aopwiki.org/`). Always query `FROM` it.
- Queries must stay under the endpoint's 10,000-row result cap: page subjects first, then fetch
  their properties with `VALUES`.

Templates are validated when the app starts, and `tests/unit/test_queries.py` renders every template
with sample values and parses the result.
