
##Selected
#MODEL="qwen3.5:4b"
#MODEL="granite4:3b"
MODEL="llama3.1:8b"
#MODEL="gemma4:e4b"

##Rejected
#MODEL="nemotron-3-nano:4b"
#MODEL="phi4-mini:3.8b"
#MODEL="llama3.2:3b"


EMBEDDING_MODEL="qllama/bge-small-en-v1.5:latest"

# ============================================================
# RAG Configuration
# ============================================================

TOP_K = 5

# Minimum similarity score.
SIMILARITY_THRESHOLD = 0.25

# Maximum characters of retrieved context sent to the LLM.
MAX_CONTEXT_CHARS = 12000