## Testing Strategy

This document outlines the testing strategy for maintaining code quality throughout the codebase.

**Testing Philosophy**:
- Tests should be fast, isolated, and deterministic.
- Follow the test pyramid: many unit tests, fewer integration tests, and minimal end-to-end (E2E) tests.
- Focus on testing behavior rather than implementation details.
- Every bug fix should include a regression test.

## Test Types

- **Unit Tests**:
  - **Framework**: Jest / Vitest
  - **Location**: `__tests__/` or co-located `*.test.ts` files
  - **Purpose**: Test individual functions and components in isolation, using mocks for external dependencies.

- **Integration Tests**:
  - **Framework**: Jest / Vitest
  - **Location**: `tests/integration/` or `*.integration.test.ts`
  - **Purpose**: Validate feature workflows and component interactions, may require a test database or external services.

- **E2E Tests**:
  - **Framework**: Playwright / Cypress
  - **Location**: `e2e/` or `tests/e2e/`
  - **Purpose**: Test critical user paths end-to-end, requiring the full application stack.

## Running Tests

**Commands**:
```bash
# Run all tests
npm run test

# Run tests in watch mode (for development)
npm run test -- --watch

# Run tests with coverage report
npm run test -- --coverage

# Run a specific test file
npm run test -- path/to/file.test.ts

# Run tests matching a specific pattern
npm run test -- --testNamePattern="pattern"
```

## Quality Gates

**Coverage Requirements**:
- Minimum overall coverage: 80%.
- New code should maintain a higher coverage rate.
- Critical paths are expected to have 100% coverage.

**Pre-merge Checks**:
- [ ] All tests must pass.
- [ ] Coverage thresholds must be met.
- [ ] Linting checks must pass (`npm run lint`).
- [ ] Type checking must be verified (`npm run typecheck`).
- [ ] Build must succeed (`npm run build`).

**CI Pipeline**:
- Tests are executed automatically on every pull request (PR).
- Coverage reports are generated and compared to baseline metrics.
- Any failed checks will block the merge process.

## Troubleshooting

**Common Issues**:

*Tests timing out*:
- Increase the timeout for slow operations.
- Check for unresolved promises.
- Verify that mocks are properly configured.

*Flaky tests*:
- Avoid time-dependent assertions.
- Utilize proper async/await patterns.
- Ensure tests are isolated from external state.

*Environment issues*:
- Confirm that the Node version aligns with project requirements.
- Clear `node_modules` and reinstall if dependencies seem corrupted.
- Check for any conflicting global installations.

## Related Resources

- [development-workflow.md](./development-workflow.md)
