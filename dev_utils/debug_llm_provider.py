from openai_provider import OpenAICompatibleProvider, load_openai_compatible_config


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
