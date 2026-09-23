# TRACER interactive demo

This zero-dependency webpage lets readers explore all 24 frozen `repair24` failures and a
corresponding public proof that passed independent Lean recompilation. Filters cover five proof
domains and four diagnostic families. It also explains where TRACER changes the repair pipeline
and visualizes the audited release-wide first-to-final conversion.

The interaction is dynamic JavaScript, but the evidence is static: it does not call a model,
upload source code, make a network request, simulate a new generation, or claim a causal gain.

Run it locally:

```text
python demo/serve.py
```

Rebuild the browser data from the public release after changing the release contract:

```text
python demo/build_demo_data.py
```

The page shows the release-wide descriptive conversion from the first candidate
(735/864) to success within at most three rounds (811/864). The source of truth remains the
published release and its audit contract.

The GitHub Pages workflow deploys this directory after changes reach `main`. Repository owners
must select **GitHub Actions** as the Pages source once in the repository settings.
