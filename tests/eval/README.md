# Real API Evaluation

This directory contains effectiveness evaluations for myCodingAgent. These tests are intentionally separate from normal unit tests because they can call real APIs, BGE embeddings, Milvus, Docker, and the full agent runtime.

Run order:

```bash
python3 -m tests.eval.dataset_generators
python3 -m tests.eval.runner precheck-bge
python3 -m tests.eval.runner run-skill-router
python3 -m tests.eval.runner report
```

The first version generates all planned datasets and implements the 500+ Skill routing evaluation plus BGE precheck. Other modules use the generated datasets as the contract for subsequent real-API runners.

