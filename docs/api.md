# API

All `/api` routes use the same local/production authentication policy. There is no public customer API. IDs are opaque strings. JSON bodies reject unknown fields.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/workspace` | Companies, bids and provider status |
| POST | `/api/companies` | Create an operator-supplied company identity |
| GET | `/api/companies/{id}` | Company sources and evidence |
| POST | `/api/companies/{id}/documents` | Upload a company source |
| POST | `/api/companies/{id}/extract` | Propose source evidence |
| POST | `/api/companies/{id}/evidence` | Add an exact sourced quote |
| POST | `/api/evidence/{id}/review` | Approve/reject evidence with a reason |
| POST | `/api/bids` | Create a bid for a company |
| GET | `/api/bids/{id}` | Current review workspace and blockers |
| POST | `/api/bids/{id}/documents` | Upload solicitation, amendment or response attachment |
| GET | `/api/documents/{id}` | Source blocks and metadata |
| GET | `/api/documents/{id}/download` | Immutable original file |
| POST | `/api/documents/{id}/review` | Confirm extraction coverage |
| POST | `/api/documents/{id}/acknowledge` | Record amendment acknowledgment |
| POST | `/api/documents/{id}/extract-evidence` | Propose evidence from a response attachment |
| POST | `/api/bids/{id}/extract` | Extract atomic requirements |
| POST | `/api/bids/{id}/requirements` | Append a sourced requirement or replacement |
| POST | `/api/bids/{id}/controls` | Confirm sourced deadline, method, page limit and scope |
| POST | `/api/bids/{id}/qualify` | Deterministic GO / REVIEW / NO-GO |
| POST | `/api/bids/{id}/map-evidence` | Suggest evidence matches |
| POST | `/api/requirements/{id}/mapping` | Review complete evidence coverage |
| POST | `/api/bids/{id}/questions` | Refresh targeted questions |
| POST | `/api/bids/{id}/answers` | Record a named customer confirmation |
| POST | `/api/bids/{id}/generate` | Assemble an evidence-only proposal |
| GET | `/api/bids/{id}/preview.pdf` | Render a marked draft PDF |
| POST | `/api/bids/{id}/audit` | Run separate-context AI or human red-team audit plus deterministic checks |
| POST | `/api/findings/{id}/resolve` | Record the correction of a red-team finding |
| POST | `/api/bids/{id}/approve` | Human final approval for the exact current version |
| POST | `/api/bids/{id}/export` | Download draft/final ZIP after fresh checks |

## Common bodies

Every review requires:

```json
{"reviewer":"Named operator","reason":"Specific review decision and supporting checks.","duration_seconds":45}
```

Audit and final approval also require `expected_revision`, matching the bid revision shown to the reviewer. A stale browser cannot approve an unseen version.

A customer answer requires:

```json
{
  "requirement_id":"REQ-id",
  "text":"The exact customer-confirmed statement for the proposal.",
  "customer_name":"Named customer",
  "confirmed":true,
  "fact_key":"project-alpha",
  "supersedes":null,
  "attachment_document_id":null
}
```

Use a distinct `fact_key` for each project reference. Use the same key for competing values of one fact. `supersedes` creates an explicit evidence correction. It does not erase the old statement.

Upload with multipart fields `file`, `kind`, and `sequence`. Company uploads use only `file`. Bid `kind` is `solicitation`, `amendment`, or `response_attachment`. Only amendments have a positive sequence number.

The export body is `{"final":true}` or `{"final":false}`. A final-export failure returns HTTP 409 with the current blockers. Invalid provenance returns 422. Provider failures return 502 or 503 without leaking credentials or provider response bodies.

## Integration references

- [FastAPI file uploads](https://fastapi.tiangolo.com/tutorial/request-files/)
- [Anthropic Messages API](https://platform.claude.com/docs/en/api/messages)
- [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses)

Model IDs are configuration, not part of the compliance contract. Update the provider setting after verifying account availability.
