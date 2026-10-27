"""Connect Microsoft Agent Framework agents to the Foundry deployment configured in .env (never printed)."""
import os
from pathlib import Path

from agent_framework import Agent
from agent_framework.openai import OpenAIChatCompletionClient

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def make_client():
    load_env()
    missing = [k for k in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Set {', '.join(missing)} in {ENV_PATH}")
    base = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/") + "/openai/v1/"
    return OpenAIChatCompletionClient(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        base_url=base,
        default_headers={"api-key": os.environ["AZURE_OPENAI_API_KEY"]},
    )


def make_agent(name, instructions, client=None):
    return Agent(client or make_client(), instructions, name=name)
