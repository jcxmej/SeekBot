from ollama import generate


def main() -> None:
    response = generate(model="llama3.1:8b", prompt="Reply with OK only.", stream=False)
    text = response.get("response", "") if isinstance(response, dict) else getattr(response, "response", "")
    print(text.strip())


if __name__ == "__main__":
    main()
