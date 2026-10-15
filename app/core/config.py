from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "ai-dlc"
    environment: str = "dev"
    mock_mode: bool = True
    workspace_root: str = "./workspaces"
    default_branch: str = "main"
    copilot_model: str = "auto"

    github_token: str = ""
    github_api_url: str = "https://api.github.com"
    github_organization: str = "RogersCommunications"
    github_app_id: str = ""
    github_installation_id: str = ""
    github_private_key_path: str = ""
    api_token: str = ""
    command_timeout_seconds: int = 1800
    agent_timeout_seconds: int = 1800
    ci_timeout_seconds: int = 1800
    ci_poll_interval_seconds: int = 10

    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = "DEMO"
    jira_auth_type: Literal["basic", "bearer"] = "basic"
    jira_api_version: Literal["2", "3"] = "3"
    jira_default_page_size: int = 50

    sonar_url: str = ""
    sonar_token: str = ""
    codeql_workflow_file: str = "codeql.yml"
    codeql_ref: str = "main"
    max_remediation_attempts: int = 2

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
