---
status: unfilled
generated: 2026-05-26
agents:
  - type: "code-reviewer"
    role: "Review code changes for quality, style, and best practices"
  - type: "bug-fixer"
    role: "Analyze bug reports and error messages"
  - type: "feature-developer"
    role: "Implement new features according to specifications"
  - type: "refactoring-specialist"
    role: "Identify code smells and improvement opportunities"
  - type: "test-writer"
    role: "Write comprehensive unit and integration tests"
  - type: "documentation-writer"
    role: "Create clear, comprehensive documentation"
  - type: "performance-optimizer"
    role: "Identify performance bottlenecks"
  - type: "security-auditor"
    role: "Identify security vulnerabilities"
  - type: "backend-specialist"
    role: "Design and implement server-side architecture"
  - type: "frontend-specialist"
    role: "Design and implement user interfaces"
  - type: "architect-specialist"
    role: "Design overall system architecture and patterns"
  - type: "devops-specialist"
    role: "Design and maintain CI/CD pipelines"
  - type: "database-specialist"
    role: "Design and optimize database schemas"
  - type: "mobile-specialist"
    role: "Develop native and cross-platform mobile applications"
docs:
  - "project-overview.md"
  - "architecture.md"
  - "development-workflow.md"
  - "testing-strategy.md"
  - "glossary.md"
  - "data-flow.md"
  - "security.md"
  - "tooling.md"
phases:
  - id: "phase-1"
    name: "Discovery & Alignment"
    prevc: "P"
    agent: "TODO: assign-agent"
  - id: "phase-2"
    name: "Implementation & Iteration"
    prevc: "E"
    agent: "TODO: assign-agent"
  - id: "phase-3"
    name: "Validation & Handoff"
    prevc: "V"
    agent: "TODO: assign-agent"
---

# State of the Art API Integration Plan

> Transition from mock APIs to real Apify and Casa dos Dados endpoints with error handling and rate limiting.

## Task Snapshot
- **Primary goal:** Implement real HTTP clients for `pp` and `casadados`, including authentication, retries, and error handling to replace existing mocks.
- **Success signal:** The platform can successfully query the real Casa dos Dados API and trigger a real Apify actor, returning structured JSON.

- **Key references:**
  - [Documentation Index](../docs/README.md)
  - [Agent Handbook](../agents/README.md)
  - [Plans Index](./README.md)

## Codebase Context
- **Total files analyzed:** 11
- **Total symbols discovered:** 283

### Key Components
**Core Classes:**
- `SliceValue` — /home/lucas/Downloads/codex_luascfl_jarvis/go/src/runtime/runtime-gdb.py:77
- `StringTypePrinter` — /home/lucas/Downloads/codex_luascfl_jarvis/go/src/runtime/runtime-gdb.py:103
- `SliceTypePrinter` — /home/lucas/Downloads/codex_luascfl_jarvis/go/src/runtime/runtime-gdb.py:119
- `MapTypePrinter` — /home/lucas/Downloads/codex_luascfl_jarvis/go/src/runtime/runtime-gdb.py:144
- `ChanTypePrinter` — /home/lucas/Downloads/codex_luascfl_jarvis/go/src/runtime/runtime-gdb.py:307
## Agent Lineup
| Agent | Role in this plan | Playbook | First responsibility focus |
| --- | --- | --- | --- |
| Architect Specialist | Design resilience and API contracts | [Architect Specialist](../agents/architect-specialist.md) | Design robust HTTP client interfaces |
| Backend Specialist | Implement Go HTTP clients | [Backend Specialist](../agents/backend-specialist.md) | Write the Apify and Casa dos Dados client code |
| Security Auditor | Ensure secure credential management | [Security Auditor](../agents/security-auditor.md) | Audit API key handling via env vars |
| Code Reviewer | Review the implemented clients | [Code Reviewer](../agents/code-reviewer.md) | Review for performance and memory leaks |


## Documentation Touchpoints
| Guide | File | Primary Inputs |
| --- | --- | --- |
| Project Overview | [project-overview.md](../docs/project-overview.md) | Roadmap, README, stakeholder notes |
| Architecture Notes | [architecture.md](../docs/architecture.md) | ADRs, service boundaries, dependency graphs |
| Development Workflow | [development-workflow.md](../docs/development-workflow.md) | Branching rules, CI config, contributing guide |
| Testing Strategy | [testing-strategy.md](../docs/testing-strategy.md) | Test configs, CI gates, known flaky suites |
| Glossary & Domain Concepts | [glossary.md](../docs/glossary.md) | Business terminology, user personas, domain rules |
| Data Flow & Integrations | [data-flow.md](../docs/data-flow.md) | System diagrams, integration specs, queue topics |
| Security & Compliance Notes | [security.md](../docs/security.md) | Auth model, secrets management, compliance requirements |
| Tooling & Productivity Guide | [tooling.md](../docs/tooling.md) | CLI scripts, IDE configs, automation workflows |

## Risk Assessment
Identify potential blockers, dependencies, and mitigation strategies before beginning work.

### Identified Risks
| Risk | Probability | Impact | Mitigation Strategy | Owner (Agent) |
| --- | --- | --- | --- | --- |
| TODO: Dependency on external team | Medium | High | Early coordination meeting, clear requirements | `TODO: agent` |
| TODO: Insufficient test coverage | Low | Medium | Allocate time for test writing in Phase 2 | `test-writer` |

### Dependencies
- **Internal:** TODO: List dependencies on other teams, services, or infrastructure
- **External:** TODO: List dependencies on third-party services, vendors, or partners
- **Technical:** TODO: List technical prerequisites or required upgrades

### Assumptions
- TODO: Document key assumptions being made (e.g., "Assume current API schema remains stable")
- TODO: Note what happens if assumptions prove false

## Resource Estimation

### Time Allocation
| Phase | Estimated Effort | Calendar Time | Team Size |
| --- | --- | --- | --- |
| Phase 1 - Discovery | TODO: e.g., 2 person-days | 3-5 days | 1-2 people |
| Phase 2 - Implementation | TODO: e.g., 5 person-days | 1-2 weeks | 2-3 people |
| Phase 3 - Validation | TODO: e.g., 2 person-days | 3-5 days | 1-2 people |
| **Total** | **TODO: total** | **TODO: total** | **-** |

### Required Skills
- TODO: List required expertise (e.g., "React experience", "Database optimization", "Infrastructure knowledge")
- TODO: Identify skill gaps and training needs

### Resource Availability
- **Available:** TODO: List team members and their availability
- **Blocked:** TODO: Note any team members with conflicting priorities
- **Escalation:** TODO: Name of person to contact if resources are insufficient

## Working Phases

### Phase 1 — Discovery & Alignment
> **Primary Agent:** `architect-specialist` - [Playbook](../agents/architect-specialist.md)

**Objective:** Define the exact API schemas for Casa dos Dados and the specific Apify Actor to be used.

**Tasks**

| # | Task | Agent | Status | Deliverable |
|---|------|-------|--------|-------------|
| 1.1 | Identify Casa dos Dados API endpoint and payload | `architect-specialist` | pending | Updated architecture doc with API spec |
| 1.2 | Identify Apify Actor ID and input schema | `architect-specialist` | pending | Documented Actor ID and payload |

**Commit Checkpoint**
- `git commit -m "chore(plan): complete phase 1 discovery for state-of-the-art apis"`

---

### Phase 2 — Implementation & Iteration
> **Primary Agent:** `backend-specialist` - [Playbook](../agents/backend-specialist.md)

**Objective:** Replace mocks with real `net/http` clients, adding authentication from environment variables.

**Tasks**

| # | Task | Agent | Status | Deliverable |
|---|------|-------|--------|-------------|
| 2.1 | Implement real `SearchCompanyByName` using `net/http` | `backend-specialist` | pending | Functional Casa dos Dados client |
| 2.2 | Implement real `RunCompanyGoat` using Apify REST API | `backend-specialist` | pending | Functional Apify client triggering an Actor |
| 2.3 | Add context and timeout handling to requests | `backend-specialist` | pending | Resilient HTTP requests |

**Commit Checkpoint**
- `git commit -m "feat(backend): implement real HTTP clients for casadados and apify"`

---

### Phase 3 — Validation & Handoff
> **Primary Agent:** `test-writer` - [Playbook](../agents/test-writer.md)

**Objective:** Ensure the real APIs can be called successfully without regressions and handle errors gracefully.

**Tasks**

| # | Task | Agent | Status | Deliverable |
|---|------|-------|--------|-------------|
| 3.1 | Update tests to mock HTTP responses (httptest) | `test-writer` | pending | Updated `client_test.go` |
| 3.2 | Security audit of API key loading | `security-auditor` | pending | Approval of credential management |

**Commit Checkpoint**
- Record the validation evidence and create a commit signalling the handoff completion (for example, `git commit -m "chore(plan): complete phase 3 validation"`).

## Rollback Plan
Document how to revert changes if issues arise during or after implementation.

### Rollback Triggers
When to initiate rollback:
- Critical bugs affecting core functionality
- Performance degradation beyond acceptable thresholds
- Data integrity issues detected
- Security vulnerabilities introduced
- User-facing errors exceeding alert thresholds

### Rollback Procedures
#### Phase 1 Rollback
- Action: Discard discovery branch, restore previous documentation state
- Data Impact: None (no production changes)
- Estimated Time: < 1 hour

#### Phase 2 Rollback
- Action: TODO: Revert commits, restore database to pre-migration snapshot
- Data Impact: TODO: Describe any data loss or consistency concerns
- Estimated Time: TODO: e.g., 2-4 hours

#### Phase 3 Rollback
- Action: TODO: Full deployment rollback, restore previous version
- Data Impact: TODO: Document data synchronization requirements
- Estimated Time: TODO: e.g., 1-2 hours

### Post-Rollback Actions
1. Document reason for rollback in incident report
2. Notify stakeholders of rollback and impact
3. Schedule post-mortem to analyze failure
4. Update plan with lessons learned before retry

## Evidence & Follow-up

### Artifacts to Collect
- TODO: List artifacts (logs, PR links, test runs, design notes)

### Success Metrics
- TODO: Define measurable success criteria

### Follow-up Actions
| Action | Owner (Agent) | Due |
|--------|---------------|-----|
| TODO: Action description | `TODO: agent` | TODO: Date/milestone |
