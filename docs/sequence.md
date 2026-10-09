# Sequence

```text
Jira -> FastAPI -> LangGraph -> architecture -> Human
                                      |
                                      | approve
                                      v
                                  Copilot SDK
                                      |
                                      v
                                  Git branch
                                      |
                                      v
                                     PR
                                      |
                           +----------+----------+
                           |                     |
                         Sonar                 CodeQL
                           |                     |
                           +----------+----------+
                                      |
                                 quality gate
                                /            \
                              pass            fail
                               |               |
                            Human         remediation
                               |               |
                              merge <-----------+
```
