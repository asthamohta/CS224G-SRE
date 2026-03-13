# LLM Provider Quick Reference

## 🚀 Quick Setup (30 seconds)

### 1. Install SDK
```bash
pip install google-genai openai anthropic
```

### 2. Configure `.env`
```bash
cp .env.example .env
# Then edit and set ONE of these:
```

**Gemini (Recommended - Free)**
```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...your_key
```

**OpenAI (GPT-4)**
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...your_key
OPENAI_MODEL=gpt-4-turbo
```

**Anthropic (Claude)**
```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...your_key
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```

### 3. Run
```bash
python demo.py
# or
python graph/run_simulation.py
```

## 🔑 Get Your API Keys

| Provider | Link | Free? |
|----------|------|-------|
| **Gemini** | https://aistudio.google.com/ | ✅ Yes |
| **OpenAI** | https://platform.openai.com/api-keys | ⚠️ Limited |
| **Anthropic** | https://console.anthropic.com/ | ❌ No |

## 📊 Provider Models

### Gemini
- `gemini-2.5-flash` (default)

### OpenAI
- `gpt-4-turbo` (most capable)
- `gpt-4` (slower, more accurate)
- `gpt-3.5-turbo` (cheapest)

### Anthropic
- `claude-3-5-sonnet-20241022` (balanced)
- `claude-3-opus-20240229` (most capable)
- `claude-3-haiku-20240307` (fastest/cheapest)

## 💻 Code Usage

```python
# Auto-detect from .env (Recommended)
from llm_integration.client import LLMClientFactory
client = LLMClientFactory.create()

# Or specify provider explicitly
from llm_integration.client import OpenAIClient
client = OpenAIClient(model="gpt-4")

# Generate content
response = client.generate_content("Your prompt here")
print(response)
print(f"Model used: {client.model_name}")
```

## 🛠 Troubleshooting

| Issue | Solution |
|-------|----------|
| `❌ No Gemini API Key found` | Run `cp .env.example .env` and add key |
| `❌ SDK not installed` | Run `pip install openai` (or anthropic/google-genai) |
| `❌ Unknown LLM provider: xxx` | Check `LLM_PROVIDER` in `.env` |
| `Error: Invalid API key` | Verify key is correct and valid |

## 📝 Example Output

```
--- LLM SETUP ---
ℹ️  No GitHub events file at: ./github_events.jsonl
   To enable GitHub PR enrichment:
   1. Set GITHUB_OUTPUT_PATH in .env (see .env.example)
   2. Run RootScout ingestion service to collect PR data

🔌 Connecting to openai LLM API...
✅ Using model: gpt-4-turbo
📡 Sending request to gpt-4-turbo...
```

## 🔄 Environment Variables

```env
# Provider selection
LLM_PROVIDER=gemini|openai|anthropic

# Gemini
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.5-flash (optional)

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4-turbo (optional)

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022 (optional)
```

## 📚 Implementation Details

- **Abstract Base**: `LLMClient` with `generate_content()` method
- **Factory**: `LLMClientFactory.create()` - reads env and instantiates
- **Fallback**: Automatically uses `MockClient` if any provider fails
- **Model Names**: Each client has `client.model_name` property

## 🎯 Feature Comparison

| Feature | Gemini | OpenAI | Anthropic |
|---------|--------|--------|-----------|
| **Token Limit** | 32K | 128K (turbo) | 200K |
| **Speed** | ⚡⚡⚡ | ⚡⚡ | ⚡ |
| **Cost** | $ | $$$ | $$ |
| **RCA Quality** | ✅ | ⭐⭐ | ⭐ |
| **Free Tier** | ✅ | ⚠️ | ❌ |

**Recommendation**: Start with Gemini (free + fast), switch to GPT-4 if you need better reasoning.
