from fastapi import APIRouter


def create_jira_router(jira):
    router = APIRouter()

    @router.get("/api/jira/issues/{issue_key}")
    async def get_jira_issue(issue_key: str):
        return await jira.get_story(issue_key)

    return router
