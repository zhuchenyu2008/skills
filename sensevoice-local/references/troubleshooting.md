# Troubleshooting

## Common failures

### `Missing required command: docker`
The host does not have Docker in PATH. This skill assumes Docker is available.

### `Repository not found`
Expected runtime path is `<WORKSPACE>/sensevoice-local`.

### Model files missing
Run the wrapper once; it auto-downloads the pre-exported model through `scripts/prepare_model.sh`.

### Host under memory pressure
This workflow is intentionally capped to `2 CPU / 3GiB RAM / 256 PIDs`. If the server is under pressure, keep those limits or tighten them further via environment variables before running the wrapper.

### Recognition quality is weaker than cloud SOTA
This local model is the stable fallback. It can still drift on numbers, names, and math terms. Report that honestly instead of overclaiming quality.
