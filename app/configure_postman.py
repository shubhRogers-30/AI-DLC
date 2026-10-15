import json
import os
import tempfile
from pathlib import Path

from app.core.config import settings


def export_environment(destination=None):
    if not settings.api_token:
        raise ValueError("Set API_TOKEN in the local environment before configuring Postman")
    root = Path(__file__).resolve().parents[1]
    destination = Path(destination) if destination else root / "postman" / "AI-DLC.local.postman_environment.json"
    source = destination if destination.is_file() else root / "postman" / "AI-DLC.postman_environment.json"
    environment = json.loads(source.read_text(encoding="utf-8"))
    tokens = [item for item in environment["values"] if item["key"] == "api_token"]
    if len(tokens) != 1:
        raise ValueError("Postman environment must contain exactly one api_token variable")
    tokens[0].update(value=settings.api_token, type="secret", enabled=True)
    environment["name"] = "AI-DLC Local - private credentials"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, delete=False) as output:
        temporary = Path(output.name)
        json.dump(environment, output, indent=2)
        output.write("\n")
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


if __name__ == "__main__":
    export_environment()
    print("Local Postman bearer-token environment configured; secret value was not printed.")