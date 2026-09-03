# Credentials

**Nothing is required for the offline suite.** `uv sync && make validate-rupture` runs from a
fresh clone with no `.env` file, no network and no credentials. Every variable below is optional
and only affects online pulls, the DVC remote or the OpenQuake image tag.

No paid API is used anywhere in Prompt 1. ComCat, ISC, GCMT, GEM Global Active Faults and ESHM20
are all free public services or downloads; the OpenQuake engine image is public on Docker Hub.
The non-negotiable "ask before downloads > 5 GB or paid API calls" (CLAUDE.md) is not triggered
by anything in this phase; `docs/DATA_SOURCES.md` lists sizes.

## How `.env` is loaded

- Copy `.env.example` to `.env` and fill in what you need. `.env` is in `.gitignore` and is
  **never committed**; secrets do not go into `pyproject.toml`, `dvc.yaml`, job manifests or
  fixtures.
- rupture reads `.env` with `python-dotenv` at CLI start-up (`rupture.cli`), without overriding
  variables already present in the process environment. Adapters read configuration only through
  `os.environ`, never from a file directly, so the same variables work under Docker, CI and the
  job manifests in `infra/jobs/`.
- Unit tests run with sockets disabled and must not depend on any of these variables; a test
  that needs one is an integration test.

## Variables (`.env.example`)

| Variable | Required? | Purpose |
|---|---|---|
| `RUPTURE_DVC_REMOTE_URL` | no | DVC remote (S3 URL or local path). Leave empty to use the local placeholder remote `.dvc/local-remote` configured in `.dvc/config`. Production: `dvc remote modify local url s3://<bucket>/rupture`. |
| `AWS_PROFILE` | no | AWS named profile used by DVC for an S3 remote and by the `aws:` annotations in `infra/jobs/*.yaml`. Credentials themselves live in the AWS CLI's own store (`~/.aws/credentials`), not in `.env`. |
| `AWS_REGION` | no | Region for the S3 remote and job manifests. |
| `RUPTURE_CONTACT_EMAIL` | no | Contact e-mail placed in the `User-Agent` header of FDSN/ComCat requests. Polite identification requested by the services; it is not authentication and grants nothing. |
| `RUPTURE_ISC_GEM_CSV` | no | Path to a manually downloaded ISC-GEM catalogue CSV. The ISC-GEM download page is form-gated, so the adapter reads a local file rather than fetching; see `docs/DATA_SOURCES.md` and ADR-0005. |
| `RUPTURE_OPENQUAKE_IMAGE` | no | Override for the OpenQuake engine Docker image. Default is the pinned tag in the adapter (`openquake/engine:3.26.2`, ADR-0011). Use only to test an upgrade; the pin changes via ADR. |

## DVC remote credentials

The default remote is a local directory placeholder so a fresh clone works without any account.
To use S3:

```bash
dvc remote modify local url s3://<bucket>/rupture
export AWS_PROFILE=<profile>   # or set it in .env
dvc push
```

DVC picks up credentials through the standard AWS chain (profile, environment, instance role).
Nothing is stored in the repository. The `infra/jobs/*.yaml` manifests reference the same
profile/role names in their `aws:` block and never embed keys.

## Adding a credential later

If a future source or service needs a token (for example a rate-limit key), add the variable to
`.env.example` with an empty value and a one-line comment, document it in the table above, make
the adapter fail loudly with the variable name when it is missing, and confirm whether the
service is paid; if it is, the request goes through the "ask first" rule before any code is
written.
