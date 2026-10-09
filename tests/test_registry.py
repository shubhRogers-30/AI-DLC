from app.registry import AgentRegistry

def test_registry_loads_agents():
    agents = AgentRegistry(".github/agents").list_agents()
    assert "springboot-developer" in agents
    assert "security-remediation" in agents
