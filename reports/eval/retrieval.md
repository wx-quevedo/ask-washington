| Config | hit@3 | hit@6 | MRR | kw@6 | Latency mean (ms) | Latency p95 (ms) | Missing keywords in top 6 |
|---|---:|---:|---:|---:|---:|---:|---|
| vector | 0.889 | 1.000 | 0.914 | 0.981 | 26 | 31 | q20 |
| hybrid | 1.000 | 1.000 | 0.981 | 0.981 | 60 | 89 | q20 |
| rerank | 1.000 | 1.000 | 1.000 | 1.000 | 4030 | 4872 | - |
| rerank:cross-encoder/ms-marco-MiniLM-L-6-v2 | 1.000 | 1.000 | 0.963 | 0.981 | 683 | 787 | q20 |
