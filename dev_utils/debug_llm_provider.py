import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dev_utils.openai_provider import (
    OpenAICompatibleProvider,
    load_openai_compatible_config,
)


def main() -> None:
    config = load_openai_compatible_config()
    provider = OpenAICompatibleProvider(config)

    result = provider.chat(
        [{"role": "user", "content": "Reply with a short provider health check."}],
        temperature=0,
        max_tokens=80,
    )

    print(result.content)
    if result.usage:
        print(f"\nusage: {dict(result.usage)}")


if __name__ == "__main__":
    main()
