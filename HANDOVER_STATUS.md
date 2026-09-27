# Bid Factory handover status

Current on 27 September 2026.

## What is decided

- Sell one supervised service for simple civilian federal janitorial RFQs.
- Charge $1,500 USD for the first pilot.
- Collect a $750 deposit and a $750 balance.
- Pay the independent reviewer from available customer funds.
- Require the customer to provide and approve prices.
- Require evidence for every factual proposal claim.
- Create a question when a fact is missing.
- Keep mandatory requirements through extraction, drafting, and final audit.
- Require zero unresolved blockers before `SUBMISSION_READY`.
- Require a specialist review for each V0 pilot.
- Let the customer submit the final package.

## What is complete

- The local FastAPI and SQLite app covers the full proposal workflow.
- The app exports DOCX, PDF, XLSX, JSON, and a handoff ZIP.
- OpenRouter runs extraction, mapping, and a separate audit model.
- The repository contains 52 passing automated tests.
- A synthetic hostile test blocked an unsupported ISO 9001 claim.
- The launch kit contains the offer, scripts, order form, reviewer brief, and delivery process.
- The fictional sample supports a safe screen-share demonstration.
- The handover primer explains the business and operating process.

## What is blocked

- The OpenRouter key from the build session appeared in a chat and needs rotation.
- No real customer has paid for a pilot.
- No real RFQ package has specialist acceptance.
- No reviewer has a signed work order or reserved slot.
- Seller, tax, payment, mailbox, domain, and intake-folder details remain incomplete.
- Monid has no local API key or verified calling workflow.
- The app runs locally and has no tested private production deployment.
- The clean synthetic AI audit still produced conservative or false-positive findings.

## Current product evidence

- Branch: `codex/bid-factory-v0`
- Initial build commit: `5e91154`
- OpenRouter hardening commit: `e64cbfd`
- Verification records: `docs/verification.md` and `evidence/current-test-results.txt`
- Test count: 52 passed on 27 September 2026
- App state on 27 September 2026: stopped but runnable with `./run.sh`

## Next three milestones

### Milestone 1 Complete the handover controls

Done means all these conditions are true:

- Rotate the exposed OpenRouter key.
- Give the operator a separate capped key.
- Sign the contractor agreement.
- Grant named account access.
- Complete the access and decision-rights records.
- Run the app and all tests on the operator's computer.

### Milestone 2 Make the offer ready to accept money

Done means all these conditions are true:

- Complete the seller name, address, country, tax details, and payment method.
- Verify the business mailbox, sending records, postal address, and opt-out process.
- Create the private intake folder, consent record, and calendar link.
- Obtain at least two reviewer quotes.
- Select a primary and backup reviewer.
- Confirm that the $750 deposit covers committed direct costs.

### Milestone 3 Deliver one funded pilot

Done means all these conditions are true:

- Select one suitable live civilian janitorial RFQ.
- Contact approved prospects and close one accepted order.
- Receive available deposit funds.
- Complete intake and process every amendment.
- Obtain a source-based reviewer decision for the exact corrected package.
- Reach zero unresolved blockers.
- Obtain customer approval and the balance.
- Deliver the final package for customer submission.

## Do not claim

- Do not claim that the sample has expert acceptance.
- Do not claim that the app guarantees compliance, submission, or an award.
- Do not claim that public website facts prove eligibility.
- Do not claim that an AI audit replaces the independent reviewer.
- Do not claim that the local app is a customer portal.
