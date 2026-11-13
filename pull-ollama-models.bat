for %%M in (qwen3.5:4b gemma4:e4b llama3.1:8b ministral-3:8b granite4.1:8b qllama/bge-small-en-v1.5:latest) do (
    echo --- %%M
    ollama pull %%M || echo [!] Failed to pull %%M
)