# Production hardening

1. Replace InMemorySaver with a PostgreSQL-backed LangGraph checkpointer.
2. Run graph execution in a worker queue instead of inside the API request.
3. Add OIDC/SSO, RBAC and separation of requester/approver duties.
4. Use least-privilege GitHub/Jira/Sonar credentials.
5. Do not allow coding agents to merge protected branches or deploy production.
6. Treat GitHub Actions as the authoritative build/test/security gate.
7. Persist agent version, tool calls, changed files, approvals and findings.
8. Use stable Copilot session IDs for resumability.
9. Add OpenTelemetry/LangSmith.
10. Add rate limits, idempotency keys and retry policies.
