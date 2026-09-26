# Retrieval Evaluation

The checked-in evaluator is `app/retrieval/evaluate.py`. It uses deterministic synthetic fixtures and rolls back its database transaction after evaluation.

## Metrics

**Precision@5** is calculated per fixture query as:

```text
number of returned external resource IDs in the expected relevant-ID set / 5
```

The evaluator averages that value across two queries. Because the denominator is always five even when fewer than five relevant fixtures exist, the score measures the configured top-five slot precision for this small fixture, not recall or broad production quality.

**Mean retrieval latency** averages `HybridWorkspaceSearch.duration_ms` for the fixture queries. This includes query embedding and database retrieval. Model cold-start effects can dominate; report whether a result is cold or warm when recording it.

**Tenant isolation** inserts a matching resource for a second user and passes only if that resource ID is absent from every first-user result.

## Fixture methodology and limitations

- Three owner resources cover Gmail, Drive, and Calendar.
- One second-user Gmail record deliberately contains matching terms.
- Two queries exercise an Acme proposal and a quantum-computing document.
- The fixture set is intentionally small and synthetic. It does not measure broad ranking quality, Google API latency, synchronization latency, concurrency, or production-scale pgvector behavior.
- Results depend on the configured local embedding model and running PostgreSQL/pgvector service.

## Checked-in results

Actual evaluator output is not stored in the checked-in repository yet.

| Metric | Result |
|---|---|
| Precision@5 | Not measured yet |
| Mean retrieval latency | Not measured yet |
| Tenant isolation | Not measured yet |

## Run the evaluator

After building, migrating, and starting PostgreSQL:

```bash
docker compose exec api python -m app.retrieval.evaluate
```

Copy the exact output into a dated evaluation record before making performance or quality claims. Run once for cold behavior and again for warm behavior if comparing latency.
