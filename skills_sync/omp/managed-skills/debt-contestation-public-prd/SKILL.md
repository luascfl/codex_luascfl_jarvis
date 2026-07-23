---
name: debt-contestation-public-prd
description: "Use when planning, implementing, or updating a public privacy-safe debt contestation assistant, MCP, CLI, or skill for Brazilian administrative debt disputes."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/contestação_divida`


# Debt contestation public implementation workflow

Use this when the user wants to build or generalize a public tool, skill, MCP, CLI, or agent workflow for contesting debts.

## Core decision

Prefer this shape:

1. Core local library for schemas, redaction, calculations, evidence gaps, templates, protocol tracking, and exports.
2. CLI over the core for offline use and tests.
3. MCP server over the same core for agents and IDEs.
4. Skill wrapper that teaches the agent the safe workflow, when to call tools, and what not to claim.

Avoid making a skill the only implementation. Prompt alone does not guarantee deterministic calculations, schema validation, or reuse across clients. Avoid making MCP the only implementation. Tools without a behavioral guide can still leak data or overstate legal claims.

## Public safety rules

Public repos may contain schemas, code, templates, docs, tests, fictitious examples, and redacted real examples.

Public repos must not contain:

- CPF or other complete personal document.
- Full legal name attached to a real debt case.
- Full real contract number.
- Raw screenshots, receipts, invoices, boleto data, QR codes, Pix copy-paste codes, tokens, cookies, passwords, or browser sessions.

Use masked identifiers like `...181662723`. Keep real private cases outside the repo or in ignored directories such as `.private/`, `cases/private/`, or `evidence/private/`.

## Debt case workflow

1. Separate debts, products, and contracts before analysis.
2. Classify each item as proven fact, inference, hypothesis, or point to confirm.
3. Run redaction before saving or sharing.
4. Calculate financial alerts reproducibly, but do not turn alerts into legal conclusions.
5. Ask for a debt evolution statement or calculation memory before claiming abusiveness.
6. Generate channel-specific drafts for SAC, Ombudsman, credit bureau, Consumidor.gov.br, Procon, or Banco Central.
7. Keep human review before any filing or payment decision.
8. Track protocols, responses, deadlines, and next actions.

## Implementation checklist

- Create a public JSON schema for `DebtCase`, `DebtItem`, `EvidenceItem`, `CalculationReview`, and `ProtocolRecord`.
- Create a redacted seed example that validates against the schema.
- Implement redaction before any public output, with blockers for CPF, CNPJ, long numeric identifiers, payment codes, secrets, and JWTs.
- Implement calculation with integer cents or decimal arithmetic. Verify seed values with exact expected outputs.
- Implement missing-evidence reports by debt family and channel.
- Implement draft generation with sections for facts, points to confirm, requests, attachments, and caveats.
- Implement protocol classification: sufficient, partial, negative, missing calculation statement, no response, unknown.
- Expose CLI commands for validate, redact, calculate, missing evidence, calculation request, complaint draft, dossier export, and protocol update.
- Expose MCP tools over the same core: create_debt_case, add_debt_item, add_evidence_item, redact_sensitive_text, calculate_debt_review, list_missing_evidence, generate_calculation_statement_request, generate_channel_complaint, record_protocol_update, export_case_dossier.
- Create a skill wrapper with realistic eval prompts for bank/card, telecom/cancellation, and paid-agreement-followed-by-new-debt scenarios.

## Quality gates

- Validate PRD and examples as JSON when applicable.
- Validate sample cases against the schema.
- Recalculate seed-case financial values with decimal arithmetic.
- Run unit tests for calculations, privacy blockers, missing evidence, draft safety, protocol classification, and dossier export.
- Smoke test CLI behavior.
- Smoke test MCP with an SDK client when possible, at least list tools and call redaction.
- Search for CPF patterns, real names, full contracts, tokens, cookies, QR codes, Pix strings, and raw evidence before public release.
- Verify drafts ask for calculation memory and avoid promising legal outcomes.

## Recommended story order

1. Public debt-case schema.
2. Redacted seed example.
3. Calculation and missing-evidence core.
4. Draft generator for administrative channels.
5. Protocol tracker.
6. CLI.
7. MCP server.
8. Skill wrapper.
9. Privacy and legal-quality test suite.
10. README and release documentation.
