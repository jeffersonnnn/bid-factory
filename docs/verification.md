# Verification record

Date: 2026-09-23.

## Observed

- 38 automated tests passed with real SQLite databases and real LibreOffice rendering.
- Python modules imported and compiled. JavaScript syntax checks passed.
- The server responded on `http://127.0.0.1:8765` after restart. The fictional bid and its review history remained intact.
- The browser displayed eight atomic requirements with source locations. It showed missing UEI, pricing and a third reference.
- Browser customer-answer forms saved a fictional UEI, reference and price. Each requirement remained unresolved until its evidence mapping was approved.
- The file picker uploaded the fictional price sheet. The customer price answer linked to that exact attachment.
- The browser generated an evidence-only proposal. Its three references appeared in a stable order.
- The independent review form ran the deterministic checks. Final export stayed disabled until exact-version approval.
- The browser reached `SUBMISSION_READY` at revision 34 with zero blockers. The final-export button completed a download.
- The final export API returned a valid ZIP with a DOCX, PDF, original response attachment, XLSX matrix, PDF checklist and JSON provenance.
- The final PDF had one page. Its content included the approved statements and omitted the draft mark.
- The source ledger contained eight satisfied current requirements. The compliance matrix contained eight data rows.
- Review events recorded elapsed review time.
- The rendered draft PDF and checklist received visual inspection. Text was readable, with no visible clipping or overlapping elements.
- The browser reported no warning or error logs during the final checks.

All browser checks used a clearly labelled fictional company and synthetic RFQ. The recorded audit and approval were acceptance-test records. They do not approve a real contractor or authorize a real submission.

## Hostile cases covered

Missing UEI; absent and failed eligibility; company-document pricing without customer input; invented source quotes; known prompt-injection text; contradictory experience; missing third reference; missing attachments; absent certifications; expired evidence; elapsed deadline; actual page overflow; older amendments; amendment acknowledgment; lost claim coverage; stale browser approval; source tampering; malformed model output; cross-company mapping; retained red-team findings; invalid uploads; authentication; request origin and host checks.

## External limits

- Anthropic model listing succeeded. A live inference request returned an insufficient-credit error. No live AI extraction or red-team result was accepted.
- OpenAI integration has not received a live-account test in this environment.
- Production Docker deployment and a hosted TLS endpoint were not exercised. The server runs locally only.
- No real solicitation or customer package received a production acceptance review. The next deployment gate is a reviewed real RFQ with verified contractor evidence.
- The test dependencies emitted two deprecation warnings from Starlette/httpx and AnyIO. The tests completed successfully.

## Reproduce

```sh
.venv/bin/python -m pytest -q
node --check app/static/app.js
./run.sh
```

The automated tests use temporary databases and leave the local demonstration database unchanged.
