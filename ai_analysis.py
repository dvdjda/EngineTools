from openai import OpenAI

_client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

_SYSTEM = (
    "You are an engineering analysis assistant for a thermal-energy process simulator. "
    "All numbers are computed externally and given to you. Never invent, estimate, or "
    "recompute values. State only what the provided data supports. Be concise."
)

def analyze(results: str,
            question: str = "Summarize these results for an engineer.",
            model: str = "granite4.1:8b") -> str:
    resp = _client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"{question}\n\nComputed results:\n{results}"},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content
