from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")  # key is ignored

resp = client.chat.completions.create(
    model="granite4.1:8b",
    messages=[
        {"role": "system", "content": "You are an engineering analysis assistant. Be concise and state only what the input supports."},
        {"role": "user", "content": "In one sentence, what does a gas turbine recuperator do?"},
    ],
    temperature=0.2,
)
print(resp.choices[0].message.content)
