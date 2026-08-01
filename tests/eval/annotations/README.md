# Project graph manual annotations

Each public project may provide `<project_id>.json` with at least 30 symbols and 20 calls:

```json
{
  "symbols": [{"path": "src/example.py", "qualified_name": "Example.run"}],
  "calls": [{"path": "src/example.py", "caller": "Example.run", "callee_name": "helper"}]
}
```

Missing annotation files must produce `annotation_status=not_run`; structural counts must never be reported as precision or recall.
