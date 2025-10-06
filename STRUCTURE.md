# Tempoy Code Structure

This document describes the restructured code organization for the Tempoy application.

## Directory Structure

```
tempoy/
├── models/              # Data models and dataclasses
│   ├── __init__.py
│   └── config.py       # AppConfig dataclass
│
├── api/                # API client implementations
│   ├── __init__.py
│   ├── jira_client.py  # Jira REST API client
│   └── tempo_client.py # Tempo REST API client
│
├── services/           # Business logic and services
│   ├── __init__.py
│   └── config_service.py # Configuration management
│
└── tempoy.py          # Main application (UI and application logic)
```

## Module Descriptions

### `models/config.py`
Contains the `AppConfig` dataclass which holds all application configuration:
- Jira and Tempo API credentials
- Window geometry and UI state
- Search history
- User preferences

**Key Classes:**
- `AppConfig`: Configuration data model with serialization support

### `api/jira_client.py`
Jira REST API client for interacting with Jira Cloud.

**Key Classes:**
- `JiraClient`: Handles Jira API operations

**Key Methods:**
- `get_myself()`: Get current user information
- `search_assigned()`: Search for issues assigned to current user
- `search(query)`: Search for issues by key or text
- `get_issue_id(issue_key)`: Get numeric issue ID from key
- `get_issue_worklogs()`: Retrieve worklogs for an issue
- `sum_worklog_times()`: Calculate today's and total time logged

### `api/tempo_client.py`
Tempo REST API client for time tracking operations.

**Key Classes:**
- `TempoClient`: Handles Tempo API operations

**Key Methods:**
- `create_worklog()`: Log time to an issue
- `sum_issue_times()`: Get time logged for an issue
- `get_user_daily_total()`: Get total time logged today
- `get_user_issue_time()`: Get time logged for specific issue
- `get_recent_worked_issues()`: Get recently worked issues
- `get_last_logged_date()`: Get last date time was logged
- `aggregate_issue_times()`: Bulk fetch times for multiple issues

### `services/config_service.py`
Configuration management service for loading and saving application settings.

**Key Classes:**
- `ConfigManager`: Handles config file operations

**Key Methods:**
- `load()`: Load configuration from disk (with migration support)
- `save(cfg)`: Save configuration to disk

**Constants:**
- `CONFIG_DIR`: New configuration directory (`~/.tempoy`)
- `CONFIG_PATH`: New configuration file path
- `OLD_CONFIG_DIR`: Legacy directory (`~/.tempo_floater`)
- `OLD_CONFIG_PATH`: Legacy config path (for migration)

### `tempoy.py`
Main application file containing:
- UI components (`SettingsDialog`, `IssueList`, `Floater`)
- Application initialization and event handling
- Integration of all services and API clients

## Import Examples

```python
# Import data models
from models import AppConfig

# Import API clients
from api import JiraClient, TempoClient

# Import services
from services import ConfigManager, CONFIG_DIR, CONFIG_PATH

# Use the classes
cfg = ConfigManager.load()
jira = JiraClient(cfg.jira_base_url, cfg.jira_email, cfg.jira_api_token)
tempo = TempoClient(cfg.tempo_api_token)
```

## Benefits of This Structure

1. **Separation of Concerns**: Each module has a clear, single responsibility
2. **Maintainability**: Easier to locate and modify specific functionality
3. **Testability**: Individual components can be tested in isolation
4. **Reusability**: API clients can be reused in other projects
5. **Reduced Coupling**: Clear interfaces between modules
6. **Better Organization**: ~900 lines removed from main file

## Backward Compatibility

All functionality from the original monolithic `tempoy.py` has been preserved:
- Same API surface for all classes
- Same configuration file format and location
- Automatic migration from legacy config location
- No changes required to existing config files

## Future Enhancements

The modular structure enables future improvements:
- Add unit tests for individual modules
- Implement caching layer in services
- Add error handling and retry logic in base API client
- Extract UI components into separate modules
- Add event system for loose coupling
- Implement plugin architecture
