# Feature Developer Agent Playbook

```yaml
title: Feature Developer Playbook
version: 1.0
description: A comprehensive guide for feature developers working on the super_mcp_servers repository.
```

## Codebase Overview
The `super_mcp_servers` repository is structured to support multiple features across various modules. The focus for feature developers should be on understanding existing features, identifying areas for enhancement, and implementing new functionalities while maintaining existing code quality.

### Key Directories and Files
- **src/**: Main source code directory containing functional components.
- **tests/**: Contains unit and integration tests for various modules.
- **config/**: Configuration files for different environments, including database and server configurations.
- **docs/**: Documentation related to the project and its architecture.

### Target Files and Areas
- Investigate the `src/` directory, focusing on:
  - Main modules and components where features are implemented.
  - Utilities or helper functions that can be reused across multiple features.
- Review `tests/` for:
  - Existing test coverage related to the features being developed.
  - Patterns for writing effective unit and integration tests.
- Check configuration files in `config/` for environment-specific setups affecting feature behavior.

## Specific Workflows and Steps
1. **Feature Specification Review**
   - Start by examining any existing documentation for the feature request.
   - Collaborate with stakeholders to clarify requirements and expected outcomes.

2. **Code Exploration**
   - Use `listFiles` and `analyzeSymbols` to discover related modules within the `src/` directory.
   - Identify entry points for feature implementation.

3. **Implementation**
   - Follow established coding conventions and style guides in the repository.
   - Implement the feature in a new branch named `feature/[feature-name]`.
   - Add documentation comments to the code to explain new functionalities.

4. **Testing**
   - Develop unit tests for new functions and integration tests for overall feature behavior.
   - Look at the `tests/` directory to identify testing patterns and existing tests.
   - Use the structure and naming conventions observed in existing test files for consistency.

5. **Code Review**
   - After completing the feature, submit a pull request for review.
   - Address feedback and make necessary adjustments before merging into the main branch.

## Best Practices
- **Code Quality**: Maintain high standards for code quality by adhering to the project's styling guides. Use linters if available.
- **Documentation**: Whenever you introduce a new feature, ensure to document its purpose and usage within the `docs/` directory.
- **Commit Messages**: Write clear and descriptive commit messages that explain what changes have been made and why.

## Key Files and Their Purposes
- `src/main.py`: Entry point for application logic.
- `src/utils.py`: Contains utility functions used throughout the codebase.
- `tests/test_main.py`: Unit tests for the main application functionality.
- `config/config.yml`: Central configuration file for setting environment variables and application settings.

With this playbook, feature developers can effectively navigate the codebase, implement new features, and ensure high-quality output in alignment with project goals.
