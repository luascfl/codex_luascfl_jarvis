## Tooling & Productivity Guide

This guide covers the tools, scripts, and configurations that make development efficient. Following these setup recommendations ensures a consistent development experience across the team.

## Required Tooling

**Runtime**:
- **Node.js**: v18+ recommended
- **Package Managers**: npm / yarn / pnpm

**Version Management** (recommended):
- **nvm**: [Node Version Manager](https://github.com/nvm-sh/nvm) for Node.js version management.
- The project uses an `.nvmrc` file to specify the Node version required for the project.

**Installation**:
```bash
# Using nvm (recommended)
nvm install
nvm use

# Install dependencies
npm install
```

## Recommended Automation

**Pre-commit Hooks**:
The project utilizes [husky](https://typicode.github.io/husky/) for implementing git hooks:
- **Pre-commit**: This hook runs linting and type checking to ensure code quality.
- **Commit message hook**: Validates the commit message format to maintain consistency across commits.

**Code Quality Commands**:
These commands help maintain code quality throughout the development process:
```bash
npm run lint          # Check code style and report issues
npm run lint:fix      # Automatically fix linting style issues
npm run format        # Format code using Prettier
npm run typecheck     # TypeScript type checking to catch type errors
```

**Watch Mode**:
During development, you can run your commands in watch mode to see live changes:
```bash
npm run dev           # Starts the development server with hot reload
npm run test:watch    # Runs tests in watch mode for ongoing feedback
```

## IDE / Editor Setup

**VS Code Recommended Extensions**:
To enhance your development experience in VS Code, the following extensions are recommended:
- **ESLint**: Provides inline linting feedback.
- **Prettier**: Automatically formats code according to specified styles.
- **TypeScript + JavaScript Language Features**: Offers IntelliSense support for better coding experience.
- **Error Lens**: Highlights errors inline for immediate visibility.

**Workspace Settings**:
In the `.vscode/` folder, shared workspace settings are provided:
- **settings.json**: Contains editor configuration settings for the project.
- **extensions.json**: Lists recommended extensions for the project team.
- **launch.json**: Contains debug configurations for effective debugging.

## Productivity Tips

**Useful Aliases**:
To speed up command execution in the terminal, consider adding these aliases to your shell configuration:
```bash
alias nr='npm run'          # Shortcuts for npm run commands
alias nrd='npm run dev'     # Shortcut to start development server
alias nrt='npm run test'    # Shortcut to run tests
```

**Quick Commands**:
Utilize these quick commands for routine operations:
- `npm run build && npm run test` — This command ensures a full verification process prior to pull requests.
- `npm run clean` — This command clears build artifacts and caches to maintain a clean working environment.

## Related Resources

For further reading and cross-navigation:
- [development-workflow.md](./development-workflow.md)
