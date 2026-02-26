import asyncio
import os

from langchain_core.messages import HumanMessage

from lib.providers.factory import ProviderFactory
from lib.utils.enums import Provider
from lib.utils.logging import setup_logging


async def main():
    setup_logging("DEBUG")
    print(
        f"--- Environment ---\nANTHROPIC_API_KEY: {'[SET]' if os.environ.get('ANTHROPIC_API_KEY') else '[MISSING]'}"
    )
    print(
        f"CLAUDE_CODE_OAUTH_TOKEN: {'[SET]' if os.environ.get('CLAUDE_CODE_OAUTH_TOKEN') else '[MISSING]'}"
    )
    print("-------------------")

    try:
        print("Testing Provider.CLAUDE instantiation...")
        model = ProviderFactory.create(Provider.CLAUDE)
        print(
            f"Success! Model: {model.__class__.__name__} ({getattr(model, 'model', 'unknown')})"
        )

        print("Executing live invoke...")
        res = await model.ainvoke([HumanMessage(content="Say the word 'Tracer'")])
        print(f"Response: {res.content}")

    except Exception as e:
        print(f"Error: {type(e).__name__}: {e!s}")


if __name__ == "__main__":
    asyncio.run(main())
