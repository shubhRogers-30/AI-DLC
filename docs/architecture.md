# AI-DLC architecture

```text
Jira / Teams / API
       |
       v
FastAPI Orchestrator
       |
       v
LangGraph state machine
       |
       +--> Requirements
       +--> Architecture
       |
       +--> HUMAN APPROVAL
       |
       +--> Planning
       |
       v
GitHub Copilot SDK
       |
       +--> Spring Boot developer
       +--> Test generator
       +--> Security remediation
       |
       v
GitHub branch / PR
       |
       +--> CI tests
       +--> SonarQube
       +--> CodeQL
       |
       v
Deterministic quality gate
       |
       +--> PASS -> HUMAN MERGE APPROVAL
       |
       +--> FAIL -> remediation -> tests -> quality
```

LLMs are used for analysis, planning and code work. Security, merge and deployment
gates remain deterministic and policy-controlled.
