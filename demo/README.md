# TRACER interactive demo

This zero-dependency webpage replays one sanitized, real two-round trajectory from
`published/research-six-arm-313f437f`. It does not call a model, simulate a new generation, or
claim a causal gain.

Run it locally:

```text
python demo/serve.py
```

The page also shows the release-wide descriptive conversion from the first candidate
(735/864) to success within at most three rounds (811/864). The source of truth remains the
published release and its audit contract.

The GitHub Pages workflow deploys this directory after changes reach `main`. Repository owners
must select **GitHub Actions** as the Pages source once in the repository settings.
