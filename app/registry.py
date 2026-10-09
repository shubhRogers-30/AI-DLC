from pathlib import Path

class AgentRegistry:
    def __init__(self, directory=".github/agents"):
        self.directory = Path(directory)

    def list_agents(self):
        agents = {}
        if not self.directory.exists():
            return agents
        for path in self.directory.glob("*.agent.md"):
            text = path.read_text(encoding="utf-8")
            frontmatter = {}
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) == 3:
                    for line in parts[1].splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            frontmatter[k.strip()] = v.strip().strip('"')
            agents[frontmatter.get("name", path.stem)] = {
                "file": str(path),
                "description": frontmatter.get("description", ""),
                "tools": frontmatter.get("tools", "")
            }
        return agents

    def get(self, name):
        return self.list_agents().get(name)
