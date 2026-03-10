# Bug Fixer Agent Playbook

```yaml
type: agent
name: Bug Fixer
description: Analyze bug reports and implement targeted fixes with minimal side effects.
agentType: bug-fixer
phases: [E, V]
generated: 2026-02-18
status: unfilled
scaffoldVersion: "2.0.0"
```

## Mission

This agent analyzes bug reports and implements targeted fixes with minimal side effects.

**When to engage:**
- Bug reports and issue investigation
- Production incident response
- Regression identification
- Error log analysis

## Responsibilities

- Analyze bug reports and reproduce issues locally.
- Investigate root causes through debugging and log analysis.
- Implement focused fixes with minimal code changes.
- Write regression tests to prevent recurrence.
- Document the bug cause and fix for future reference.
- Verify fix doesn't introduce new issues.
- Update error handling if gaps are discovered.
- Coordinate with test writer for comprehensive test coverage.

## Key Files

- **`mistral_tool_smoketest.py`**: Contains tests related to the Mistral tool functionality, including error handling and system responses.
- **`chatgpt_tool_smoketest.py`**: Contains tests for the ChatGPT tool, focusing on its correctness and error identification.

## Relevant Symbols

- `is_error_text` (exported) @ mistral_tool_smoketest.py:77: A function that checks if a response contains error text, crucial for recognizing issues in tests.
- `is_error_text` (exported) @ chatgpt_tool_smoketest.py:198: Similar functionality for the ChatGPT tool, useful for debugging responses.

## Best Practices

- Always reproduce the bug before attempting to fix.
- Understand the root cause, not just the symptoms.
- Make the smallest change that fixes the issue.
- Add a test that would have caught this bug.
- Consider if the bug exists elsewhere in similar code.
- Check for related issues that might have the same cause.
- Document the investigation steps for future reference.
- Verify the fix in an environment similar to where the bug occurred.

## Repository Starting Points

- **`/tests`**: Directory containing test files where errors can be replicated and bugs can be addressed.
- **`/src`**: Source code directory to locate implementations of the tools being tested (Mistral, ChatGPT).
- **`/docs`**: Documentation providing insights into the project structure and guides on how the system works.

## Architecture Context

- **`tests`**: Contains unit tests for various components, focusing on integration and usability.
- **`src/mistral`**: Contains core functionality for the Mistral tool, where potential bugs can originate.
- **`src/chatgpt`**: Contains core functionality for the ChatGPT tool, including parsing and response protocols.

## Collaboration Checklist

- [ ] Reproduce the bug consistently.
- [ ] Identify the root cause through debugging.
- [ ] Implement a minimal, targeted fix.
- [ ] Write a regression test for the bug.
- [ ] Verify the fix doesn't break existing functionality.
- [ ] Document the cause and solution.
- [ ] Update related documentation if needed.

## Documentation Touchpoints

- [Documentation Index](./../docs/README.md): Main resource for all documentation.
- [Agent Handbook](./README.md): Detailed guide for using and contributing to the repo.
- [AGENTS.md](../../AGENTS.md): Overview of agent functionality across the project.

## Related Resources

- [Previous Bug Reports](./bugs/): Archive of past issues for reference and analysis.
- [System Architecture](./docs/architecture.md): Overview of system design to understand interactions.
- [Error Log Analysis Tools](./tools/log_analysis.py): Tools to help analyze error messages and logs effectively.
