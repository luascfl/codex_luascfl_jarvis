## Security & Compliance Notes

This workspace handles commercial and organizational information from a client-like lead conversation. It should avoid leaking raw transcripts, personal details beyond business relevance, or service-account credentials.

## Authentication & Authorization
Google Docs access is mediated through a service account with document scopes. The document must be shared with that account for write access to succeed.

## Secrets & Sensitive Data
- Do not commit service account files.
- Do not expose OAuth tokens in saved artifacts.
- Keep transcript handling limited to what is commercially necessary.

## Compliance & Policies
Treat the transcript as sensitive meeting material. Use only role-relevant facts, avoid unnecessary personal details, and ground all proposal claims in the documented conversation.
