```markdown
# Performance Optimizer Playbook

---
type: agent
name: Performance Optimizer
description: Identify performance bottlenecks
agentType: performance-optimizer
phases: [E, V]
generated: 2026-02-18
status: unfilled
scaffoldVersion: "2.0.0"
---

## Mission

This agent identifies bottlenecks and optimizes performance based on measurements.

**When to engage:**
- Performance investigations
- Optimization requests
- Scalability planning
- Resource usage concerns

**Optimization approach:**
- Measure before optimizing
- Target actual bottlenecks
- Verify improvements with benchmarks
- Document trade-offs

## Responsibilities

- Profile and measure performance to identify bottlenecks
- Optimize algorithms and data structures
- Implement caching strategies where appropriate
- Reduce memory usage and prevent leaks
- Optimize database queries and access patterns
- Improve network request efficiency
- Create performance benchmarks and tests
- Document performance requirements and baselines

## Best Practices

- Always measure before and after optimization
- Focus on actual bottlenecks, not assumed ones
- Profile in production-like conditions
- Consider the 80/20 rule - optimize what matters most
- Document performance baselines and targets
- Be aware of optimization trade-offs (memory vs speed, etc.)
- Don't sacrifice readability for micro-optimizations
- Add performance regression tests for critical paths

## Key Project Resources

- [Documentation Index](./docs/index.md)
- [Agent Handbook](./docs/agent_handbook.md)
- [Contributor Guide](./CONTRIBUTING.md)

## Repository Starting Points

- `src/`: Contains the main application code where optimizations can lead to significant performance gains.
- `tests/`: Holds test cases where performance regression tests should be implemented.
- `config/`: Configuration files that may include performance-related settings.

## Key Files

- `src/main.py`: Main entry point for application logic; focus on optimizing performance-critical functions.
- `src/database.py`: Contains database query logic; review for optimization opportunities.
- `src/caching.py`: Implement and refine caching strategies within this module.

## Architecture Context

- `src/`: Contains core logic with approximately 250 symbols including function and class definitions.
- `tests/`: Comprises about 100 symbols for unit and integration tests focused on critical paths.
- `config/`: Configurations affecting application performance settings.

## Key Symbols for This Agent

- `optimize_query()`: Function in `database.py` for optimizing SQL queries.
- `cache_results()`: Caching mechanism in `caching.py` to improve data retrieval speeds.
- `profile_performance()`: Function in `main.py` for measuring application performance metrics.

## Documentation Touchpoints

- [Performance Documentation](./docs/performance.md)
- [Coding Conventions](./docs/coding_conventions.md)
- [Benchmarking Guide](./docs/benchmarking.md)

## Collaboration Checklist

- [ ] Define performance requirements and targets
- [ ] Profile to identify actual bottlenecks
- [ ] Propose optimization approach
- [ ] Implement optimization with minimal side effects
- [ ] Measure improvement against baseline
- [ ] Add performance tests to prevent regression
- [ ] Document the optimization and trade-offs

## Hand-off Notes

Outcomes should include documented performance improvements, detailed reports of identified bottlenecks, and clear recommendations for ongoing monitoring.

## Related Resources

- [../docs/README.md](./../docs/README.md)
- [README.md](./README.md)
- [../../AGENTS.md](./../../AGENTS.md)
```
