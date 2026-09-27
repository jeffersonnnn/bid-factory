# Access and account handoff

Complete this record before the operator receives customer documents.

Use a separate account or key for the operator. Do not share a primary password.

| System | Owner | Operator access | Required control | Status |
|---|---|---|---|---|
| GitHub private repository | Jefferson | Named collaborator with write access | Require two-factor authentication. Protect the main branch. | Pending |
| Shared project chat | Jefferson | Read-only share link after key rotation | Treat the chat as background. Use the status page for current decisions. | Pending |
| OpenRouter | Jefferson | Separate key with a spending cap | Rotate the exposed key. Keep keys out of GitHub and chat. | Blocked |
| SAM.gov | Each person | Separate user account and API key if needed | Do not share a SAM.gov password. | Pending |
| Monid | Jefferson | Named account or separate API key | Set a small budget. Verify calling access before real use. | Blocked |
| Sending domain | Jefferson | Named mailbox or delegated access | Configure SPF, DKIM, DMARC, postal address, and opt-out handling. | Pending |
| Calendar | Jefferson | Named calendar or booking access | Limit customer details in event notes. | Pending |
| Payment account | Jefferson | No bank password. Use a supported staff role if needed. | Jefferson approves refunds, withdrawals, and account changes. | Pending |
| Customer intake folder | Jefferson | Named access to assigned folders | Use least access. Record retention and deletion dates. | Pending |
| Production host | Jefferson | Named technical access after deployment | Require authentication, TLS, encrypted storage, and backups. | Not deployed |

## Chat handoff

1. Rotate the OpenRouter key before you create the share link.
2. Create a read-only share link for the current project chat.
3. Send the link through the agreed private channel.
4. Tell the operator that older decisions may be stale.
5. Use `HANDOVER_STATUS.md` as the current source of truth.

## Credential handoff

1. Create each operator account with the operator's own email.
2. Enable multi-factor authentication where available.
3. Grant the smallest role that supports the work.
4. Store recovery codes with Jefferson.
5. Record the account owner and access date.
6. Revoke access at contract end.

## OpenRouter key rotation

1. Revoke the key that appeared in the chat.
2. Create a new owner key.
3. Create a separate operator key.
4. Set the operator spending cap.
5. Store the local key in the macOS Keychain.
6. Run one synthetic extraction and one synthetic audit.
7. Confirm that no key exists in GitHub, logs, or exported documents.
