# Safety-gated YouTube publishing

This is an additive publishing subsystem. It does not change `config/channel.yaml`, existing production manifests, research outputs, or approval flags.

## Current project state

The supplied project archive has draft scripts but no rendered MP4 files. Its selected draft manifest has `production_approved=false`, `render_authorized=false`, and `upload_authorized=false`. The channel config also has YouTube publishing disabled and `require_human_approval=true`. The engine intentionally blocks until all existing gates are explicitly satisfied.

## Setup (Windows PowerShell)

```powershell
cd "G:\youtube automation"
python -m pip install -r requirements.txt
```

Place the Google OAuth Desktop client JSON at `client_secret.json` (or pass `--client-secret`). Do not commit OAuth secrets or token files. The first real upload opens a browser OAuth flow and stores the token in `credentials/youtube_token.json`.

Copy `publishing/metadata.example.json` to a per-video metadata JSON and edit it.

## Preflight (no upload)

```powershell
python -m publishing.engine --manifest "production\runs\<topic>\drafts\<draft>\draft_manifest.json" --metadata "publishing\metadata.json" --video "output\long_videos\final.mp4" --dry-run
```

Preflight checks config enablement, manifest gates, required human approval, MP4 audio/video streams, duration, metadata limits, and duplicate-safe hash preparation. `ffprobe` must be on PATH.

## Real upload

```powershell
python -m publishing.engine --manifest "<manifest.json>" --metadata "<metadata.json>" --video "<final.mp4>" --privacy private
```

Public or scheduled publishing requires `--confirm-public`. Scheduled videos are uploaded as private with a future UTC `publishAt` value. Example:

```powershell
python -m publishing.engine --manifest "<manifest.json>" --metadata "<metadata.json>" --video "<final.mp4>" --publish-at "2026-12-01T18:30:00+05:30" --confirm-public
```

## Safety behavior

- Requires `publishing.youtube: true` in `config/channel.yaml`.
- Requires `production_approved`, `render_authorized`, and `upload_authorized` to be exactly `true` in the manifest.
- Honors `require_human_approval`; if true, requires `human_approved: true` in manifest or its `safety` object.
- Duplicate SHA-256 values are blocked. Any upload exception after reservation is marked `UNCERTAIN` and cannot be blindly retried. Reconcile the YouTube Studio state before manually resolving the ledger.
- Reports are written to `reports/publishing/`; ledger to `data/publishing/upload_ledger.sqlite3`.
- Uploads are chunked/resumable during the running process. This is not a persisted cross-restart resumable session.

## Tests

```powershell
python -m unittest tests.test_publishing_engine -v
```

## n8n

`workflows/youtube_publish_n8n_contract.json` is an implementation contract, not an import-ready executable workflow. Build the nodes using the local Windows paths and credentials. Keep the engine's guards as the final authority.
