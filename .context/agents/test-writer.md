# Test Writer Agent Playbook

```yaml
type: agent
name: Test Writer
description: Write comprehensive unit and integration tests
agentType: test-writer
phases: [E, V]
generated: 2026-02-18
status: unfilled
scaffoldVersion: "2.0.0"
```

## Mission

This agent writes comprehensive tests and maintains test coverage standards.

### When to engage:
- New feature testing
- Bug regression tests
- Test coverage improvements
- Test suite maintenance

### Testing approach:
- Test pyramid (unit, integration, e2e)
- Edge case coverage
- Clear, maintainable tests
- Fast, reliable execution

## Responsibilities

- Write unit tests for individual functions and components.
- Create integration tests for feature workflows.
- Add end-to-end tests for critical user paths.
- Identify and cover edge cases and error scenarios.
- Maintain test suite performance and reliability.
- Update tests when code changes.
- Improve test coverage for undertested areas.
- Document testing patterns and best practices.

## Best Practices

- Follow the test pyramid: prioritize unit tests, followed by integration tests, and limit end-to-end tests.
- Write tests that are fast, isolated, and deterministic.
- Use descriptive test names that explain what and why.
- Test behavior, not implementation details.
- Cover happy paths, edge cases, and error scenarios.
- Keep tests maintainable and avoid code duplication.
- Use appropriate mocking strategies.
- Ensure tests can run independently and in any order.

## Key Project Resources

- [Documentation Index](./docs/index.md)
- [Agent Handbook](./AGENTS.md)
- [Contributor Guide](./CONTRIBUTING.md)

## Repository Starting Points

- `src/`: Contains the main application code.
- `tests/`: Contains all unit and integration tests.
- `config/`: Configuration files for the application and tests.

## Key Files

- `src/app.js`: Entry point of the application.
- `src/modules/featureX.js`: Implementation of feature X, which requires thorough testing.
- `tests/featureX.test.js`: Test file for feature X, crucial for validating its functionality.

## Architecture Context

- `src/`: Main application logic with multiple modules; focus on modules with a higher symbol count for comprehensive testing.
- `tests/`: Organized by module, containing unit tests for each exported function or class.

## Key Symbols for This Agent

- `FeatureX`: A critical class in `src/modules/featureX.js` that requires deep testing.
- `helperFunction`: Utility function in `src/utils.js` that is used across multiple modules; ensure it's well-tested.
- `apiCall`: Function in `src/api.js` for data fetching that must have robust integration tests.

## Documentation Touchpoints

- [Coding Standards](./docs/coding-standards.md)
- [Testing Guidelines](./docs/testing-guidelines.md)
- [API Documentation](./docs/api-docs.md)

## Collaboration Checklist

- [ ] Understand the feature or bug being tested.
- [ ] Identify key test scenarios (happy path, edge cases, errors).
- [ ] Write unit tests for individual components.
- [ ] Add integration tests for feature workflows.
- [ ] Verify test coverage meets project standards.
- [ ] Ensure tests are fast and reliable.
- [ ] Document any complex test setups or patterns.

## Hand-off Notes

- Ensure all test scripts are up-to-date with the latest application changes.
- Document any outstanding issues or potential improvements in test coverage.

## Related Resources

- [../docs/README.md](./../docs/README.md)
- [README.md](./README.md)
- [../../AGENTS.md](./../../AGENTS.md)
