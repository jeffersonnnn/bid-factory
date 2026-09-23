# Bid Factory V0

A private, operator-run review desk for simple civilian federal service RFQs.

The app implements solicitation upload → atomic requirements → company evidence → evidence mapping → targeted questions → grounded proposal → independent audit → DOCX/PDF export.

## Run locally

Requirements: Python 3.11 or newer, and LibreOffice (`soffice`) for matching DOCX/PDF output. The current environment uses Python 3.14.

```sh
./run.sh
```

Open [the review desk](http://127.0.0.1:8765). The first run installs the pinned Python dependencies if `.venv` does not exist. The server listens on loopback only.

To install manually:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
# macOS, if LibreOffice is missing:
brew install --cask libreoffice
```

Set `LIBREOFFICE_BIN` to the full `soffice` path if it is not on `PATH`. On a standard macOS installation, use `/Applications/LibreOffice.app/Contents/MacOS/soffice`.

The data stays in `data/bid-factory.sqlite3`. Restarting the server preserves the work. Stop the server with Ctrl+C. Set `PORT` to change the local port.

## Fictional demonstration

```sh
.venv/bin/python scripts/seed_demo.py
```

This command creates one labelled fictional company and RFQ. It starts with missing UEI, pricing and one reference. It never resets or deletes existing data. The supplied documents are synthetic fixtures, not real solicitations or verified contractor records. The demo in this workspace also contains browser-test customer answers.

## Complete a bid

1. Add a company. Upload its capability statement, references, resumes and certificates.
2. Extract evidence. Check each source statement before approval. Reject false or stale statements with a reason.
3. Create a bid. Upload the solicitation, all source attachments and all amendments.
4. Extract requirements. Open each source file and compare every source block with the ledger.
5. Add omitted requirements. Split compound obligations. Correct requirements with a sourced replacement; never delete them.
6. Confirm source coverage. Record the deadline with its time zone, submission destination, page limit and package completeness.
7. Suggest evidence matches. Approve each mapping only after checking all required details and quantities.
8. Record the missing customer answers. Upload response attachments using the response-attachment role.
9. Link pricing or signed-form answers to the actual attachment. Pricing requires a named customer answer with a dollar amount.
10. Generate the proposal. Inspect its claims and the rendered PDF.
11. Complete an independent red-team review. Record unresolved findings. Correct and explicitly resolve those findings before a new audit.
12. Approve the exact version. Export the final package only when no blockers remain.

Any new source, evidence decision, answer, mapping or setting invalidates the prior approval. The app rechecks the deadline during final export.

## AI operation

The default `AI_PROVIDER=offline` uses a conservative local candidate extractor and human red-team review. It is a complete manual review workflow, not a simulated AI call. Candidate extraction does not establish completeness.

Copy `.env.example` to `.env` and choose one provider:

```dotenv
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key
AI_MODEL=claude-sonnet-5
```

Or:

```dotenv
AI_PROVIDER=openai
OPENAI_API_KEY=your-key
AI_MODEL=your-available-model
```

Restart the server after configuration changes. Keep `.env` private. The app never returns keys to the browser.

Online extraction sends source text to the selected provider. Online mapping sends requirements and evidence. The independent AI audit receives a new context containing original sources, requirements, evidence and the finished draft. It receives no writer conversation. Review the provider's data terms before using customer material.

AI can suggest extraction and matches or add audit findings. It cannot approve evidence, waive blockers, set final state or generate prices. All model-supplied source quotes must occur exactly in the cited source block. Schema or provider failures roll back the step.

The proposal assembler uses approved evidence verbatim with standard section headings. This deliberately avoids free-form factual paraphrases. Improve prose through a traceable customer answer or a corrected source, then regenerate.

**Current live-provider result:** the Anthropic account returned a credit-balance error. Model listing worked, but inference did not. Live AI extraction and audit remain unverified. Automated tests validate the AI boundaries with controlled responses. The human review workflow and actual file rendering passed end-to-end tests.

## Export contents

```text
Proposal.docx
Proposal.pdf
submission-files.txt
original-attachments/
internal/Compliance-Matrix.xlsx
internal/Submission-Checklist.pdf
internal/Provenance.json
```

The PDF comes from the DOCX through LibreOffice. The rule engine checks that rendered page count against the confirmed maximum. Internal files contain source text, evidence, requirement lineage, claims and review records. Do not send the internal folder to the contracting office unless specifically required.

Editing an exported DOCX cancels its reviewed status. The app cannot track edits outside its database. Re-upload changed content as evidence and repeat review before submission.

## Architecture and invariants

One FastAPI application, SQLite database, plain JavaScript UI and document renderer. No frontend build process, CRM, billing, prospecting, analytics or submission service.

| Record | Purpose |
| --- | --- |
| `organizations`, `companies`, `bids` | One operator organization and its contractor work |
| `documents` | Immutable bytes, content hash, source blocks and amendment order |
| `requirements` | Immutable atomic obligations and explicit replacement links |
| `evidence`, `mappings` | Exact source statements, customer confirmations and reviewed coverage |
| `questions`, `answers` | Bid-specific missing information and its named source |
| `proposal_sections`, `proposal_claims` | Versioned response and claim-level evidence links |
| `audit_runs`, `audit_findings` | Independent results bound to a draft hash and revision |
| `rules`, `workflow_runs`, `review_events` | Deterministic checks, completed workflow steps and review time |
| `exports` | Final/draft status, revision and package hash |

Compatibility views expose `company_documents`, `bid_documents`, `company_facts` and `solicitation_facts` without duplicating source data.

All writes run in SQLite transactions. Original document content and requirement records have database-level update/delete guards. Corrections append new records. Atomic source quotes, scoped company evidence, approved mappings, exact claim text, required evidence coverage, deadline validity, actual attachments, amendment acknowledgments, rendered pages, current audit and human approval all control readiness.

State changes follow the specification's workflow. `SUBMISSION_READY` is derived from current conditions and approval, never accepted from a request or model. The state falls back to review when time expires or records change.

## Initial scope and limits

- One trusted operator organization per deployment. This is an internal service console, not a multi-tenant customer portal.
- Ordinary unclassified, non-CUI civilian service RFQs. Maximum 30 proposal pages, 150 source PDF pages per file, 12 MB per upload.
- PDFs require readable source text. Scanned signed response attachments can remain original files and use a customer verification linked to the file.
- PDF provenance uses physical pages. DOCX provenance uses numbered body blocks, including tables. XLSX provenance uses sheet and row locations.
- DOCX headers, footers, drawings and text boxes need original-file review. No OCR service runs automatically.
- Page-limit and deadline amendments receive automatic lineage suggestions only when the source explicitly states a revision. Other changes need reviewer-linked replacements.
- Ambiguous or out-of-order instructions remain blockers. There is no legal interpretation engine, automatic certification registry check or SAM registration validation.
- The operator must check reference comparability, signatures, pricing arithmetic, full forms, formatting, source completeness and real-world truth. A traceable statement can still be false.
- Unsupported layout constraints need a different reviewed workflow. The app uses a fixed US Letter template and does not silently waive format rules.
- The initial version assembles one main proposal volume. It does not model complex cost proposals, multiple volume-specific page limits or submission portals.
- SAM.gov URL ingestion is deferred. Uploaded files are the supported source of truth.
- AI calls run synchronously. Use one server worker. Large packages need a future durable job queue.

## Private production deployment

The Dockerfile provides a non-root runtime with LibreOffice. The production process refuses to start without a password of at least 16 characters.

```sh
docker build -t bid-factory .
docker volume create bid-factory-data
docker run --rm --name bid-factory \
  -p 127.0.0.1:8765:8765 \
  --env-file .env.production \
  -v bid-factory-data:/data \
  bid-factory
```

Use these production settings:

```dotenv
APP_MODE=production
APP_USER=operator
APP_PASSWORD=replace-with-a-long-random-password
ALLOWED_HOSTS=your-private-host.example,127.0.0.1,localhost
AI_PROVIDER=offline
```

Put a TLS reverse proxy and access restrictions in front of the service. Configure a 13 MB request-body limit and a suitable request timeout. Use encrypted storage and encrypted backups for customer documents. Do not expose the local no-password mode publicly. The Docker deployment was prepared but was not run in this environment.

The local mode rejects non-loopback clients. The service also checks hosts and request origins, requires authentication in production, escapes document text in the UI, limits parsing, and prevents source text from becoming spreadsheet formulas.

For a consistent backup, use the SQLite backup API rather than copying only the main file while WAL writes are active. Test restoration before accepting customer work. The database includes original files and all review records. This V0 has no data retention or deletion interface.

## Tests

```sh
.venv/bin/python -m pytest -q
```

The suite uses isolated temporary databases. It covers a real DOCX/PDF/ZIP export plus hostile cases for absent UEI, eligibility failure, missing customer pricing, missing attachments, invented claims, prompt injection, contradictory experience, expired evidence, old amendments, page-count overrides, lost reference claims, stale approvals, deadline expiry, invalid AI output, cross-company evidence and source tampering.

See `docs/verification.md` for observed results. See `docs/api.md` for the API. The original product specification is retained in `docs/original-spec.md` as reference data.
