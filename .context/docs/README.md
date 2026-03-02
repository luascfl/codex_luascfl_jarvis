# Documentation for Super MCP Servers

Welcome to the Super MCP Servers documentation. This guide provides an overview of the project, its structure, and how to engage with the codebase effectively.

## Project Overview

Super MCP Servers is a comprehensive backend solution designed to facilitate various server-side operations related to MCP (Multi-Channel Publishing). This project encompasses various functionalities such as authentication, event scheduling, and error handling, aimed at improving the publishing workflow.

## Key Features

- **Authentication:** Seamlessly integrate user authentication via Google Drive and Google Tasks.
- **Event Management:** Create, list, and manage events efficiently with Google Calendar integration.
- **SEO Auditing:** Tools to audit and analyze SEO performance.
- **Diagnostics and Error Resolution:** Automated diagnostics to troubleshoot and resolve issues within the system.

## Core Guides

- [Project Overview](./project-overview.md)
- [Development Workflow](./development-workflow.md)
- [Testing Strategy](./testing-strategy.md)
- [Tooling & Productivity Guide](./tooling.md)

## Public API

Super MCP Servers exposes a variety of functions to interact with its features. Here are some of the key functions available:

### Authentication Functions
- **`authenticate`**
  - **File:** `auth_with_drive.py`, `auth_google_tasks.py`
  - **Description:** Handles authentication processes with Google Drive and Tasks.

### Google Calendar Functions
- **`gcal_add_event`**
  - **File:** `jarvis.py`
  - **Description:** Adds a new event to Google Calendar.

- **`gcal_list_events`**
  - **File:** `jarvis.py`
  - **Description:** Retrieves a list of events from Google Calendar.

### SEO Functions
- **`audit_seo`**
  - **File:** `jarvis.py`
  - **Description:** Audits the SEO setup for compliance and effectiveness.

### Various Utility Functions
- **`fetch`**
  - **File:** `jarvis.py`
  - **Description:** Fetches data from external sources or APIs.
  
- **`clean_reqs`**
  - **File:** `install_super_venv.py`
  - **Description:** Cleans and sets up the required virtual environment for the project.

## Usage Examples

Here's a short example of how to authenticate a user and add an event to Google Calendar:

```python
from auth_with_drive import authenticate
from super_server_v6 import gcal_add_event

# Authenticate the user
credentials = authenticate()

# Add an event
event = {
    'summary': 'Test Event',
    'start': {'dateTime': '2023-10-10T10:00:00-07:00'},
    'end': {'dateTime': '2023-10-10T11:00:00-07:00'}
}
gcal_add_event(credentials, event)
```

## Dependencies

This project relies on various modules and libraries for its functionality, including:

- Google API Client Libraries
- Flask (for web handlers)
- Pytest (for testing)

## Repository Snapshot

The repository consists of the following notable files:

- `jarvis.py`: Core server functionalities.
- `auth_google_tasks.py`: Handles Google Tasks integration.
- `install_super_venv.py`: Setup scripts for virtual environments.
- `mistral_tool_smoketest.py`: Testing scripts for the Mistral tool.

## Testing Strategy

Unit tests and integration tests are crucial for maintaining code quality. Refer to the [Testing Strategy](./testing-strategy.md) for more detailed insights into the testing framework used, including configurations and known issues.

## Conclusion

This document serves as an introductory guide to the Super MCP Servers project. For more detailed information on specific aspects, refer to the respective core guides linked above. For further assistance, please feel free to reach out to the maintainers or contributors of the project.
