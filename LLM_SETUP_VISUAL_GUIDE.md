# 🎯 Your LLM Setup - Visual Guide

## Step 1: Install (30 seconds)
```bash
pip install google-genai openai anthropic
```

## Step 2: Copy Config Template (10 seconds)
```bash
cp .env.example .env
```

## Step 3: Choose Your LLM & Add Key (2 minutes)

### Option A: Gemini 🟢 (Recommended)
```
Open: https://aistudio.google.com/
Click: Get API Key
Copy: AIza...xxx
Paste to .env:

LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...xxx
```

### Option B: OpenAI 🔵
```
Open: https://platform.openai.com/api-keys
Click: Create new secret key
Copy: sk-...xxx
Paste to .env:

LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...xxx
OPENAI_MODEL=gpt-4-turbo
```

### Option C: Anthropic 🟣
```
Open: https://console.anthropic.com/
Click: API keys
Create: New API key
Copy: sk-ant-...xxx
Paste to .env:

LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...xxx
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```

## Step 4: Run
```bash
python demo.py
```

Expected output:
```
--- LLM SETUP ---
🔌 Connecting to GEMINI LLM API...
✅ Using model: gemini-2.5-flash
📡 Sending request to gemini-2.5-flash...
```

---

## .env File Examples

### Complete Gemini Setup
```env
# Only set ONE provider at a time!
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza_AbCdEfGhIjKlMnOpQrStUvWxYz

# GitHub settings (optional)
GITHUB_TOKEN=ghp_xxxxx
GITHUB_OUTPUT_PATH=./github_events.jsonl

# Server (optional)
HOST=0.0.0.0
PORT=8000
```

### Complete OpenAI Setup
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxx
OPENAI_MODEL=gpt-4-turbo

# Or use different models:
# OPENAI_MODEL=gpt-4
# OPENAI_MODEL=gpt-3.5-turbo
```

### Complete Anthropic Setup
```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxx
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

# Or use different models:
# ANTHROPIC_MODEL=claude-3-opus-20240229
# ANTHROPIC_MODEL=claude-3-haiku-20240307
```

---

## Quick Switch Between Providers

### From Gemini to OpenAI
```env
# Change this line:
LLM_PROVIDER=openai

# Then run:
python demo.py
```

### From OpenAI to Anthropic
```env
# Change this line:
LLM_PROVIDER=anthropic

# Then run:
python demo.py
```

---

## Cost Comparison (1M tokens = ~4,000 pages)

| Provider | Input Cost | Output Cost | Total for RCA |
|----------|-----------|------------|---------------|
| Gemini | $0.075 | $0.30 | ~$0.01 |
| Claude 3.5 | $3.00 | $15.00 | ~$0.50 |
| GPT-4 Turbo | $10.00 | $30.00 | ~$1.00 |

**💡 Tip**: Use Gemini for development/testing, GPT-4 for production

---

## Feature Matrix

```
                  │ Gemini │ GPT-4 │ Claude │ Mock
──────────────────┼────────┼───────┼────────┼─────
Speed             │  ⚡⚡⚡ │ ⚡⚡  │ ⚡    │ ⚡⚡⚡
Cost              │  $     │ $$$  │ $$   │ Free
Token Limit       │  32K   │ 128K │ 200K │ ∞
RCA Quality       │  ✅    │ ⭐⭐  │ ⭐   │ Mock
Free Tier         │  ✅    │ ⚠️   │ ❌   │ ✅
Setup Time        │  2min  │ 3min │ 3min │ 0min
──────────────────┼────────┼───────┼────────┼─────
Best For          │Testing │ Prod  │Cost   │Dev
```

---

## Troubleshooting Flow Chart

```
Running demo.py?
    │
    ├─ See "Using Gemini API" → ✅ Working!
    │
    ├─ See "SDK not installed" 
    │   └─ Run: pip install {provider}-sdk
    │
    ├─ See "No API Key found"
    │   └─ Add to .env:
    │       LLM_PROVIDER=gemini
    │       GEMINI_API_KEY=your_key_here
    │
    ├─ See "Invalid API key"
    │   └─ Check key is correct:
    │       Get new one from provider's console
    │       Paste exact value (no spaces)
    │
    ├─ See "Unknown provider"
    │   └─ Check LLM_PROVIDER value
    │       Must be: gemini, openai, or anthropic
    │
    └─ See "Using Mock Client"
        └─ All providers failed
           Try adding API key to .env
           Or run: python -c "from llm_integration.client import LLMClientFactory; LLMClientFactory.create()"
```

---

## Code Snippet: Use in Your Project

### Auto-Detect Provider
```python
from llm_integration.client import LLMClientFactory, MockClient

try:
    client = LLMClientFactory.create()
except Exception as e:
    print(f"Falling back to mock: {e}")
    client = MockClient()

response = client.generate_content(your_prompt)
print(f"Model: {client.model_name}")
print(f"Response: {response}")
```

### Specify Provider Directly
```python
from llm_integration.client import OpenAIClient

client = OpenAIClient(
    api_key="sk-...",  # Optional, reads from .env if not provided
    model="gpt-4-turbo"  # Optional, reads from .env if not provided
)
response = client.generate_content(your_prompt)
```

### Error Handling
```python
from llm_integration.client import LLMClientFactory, MockClient

providers = ["openai", "gemini", "anthropic"]
client = None

for provider in providers:
    try:
        client = LLMClientFactory.create(provider=provider)
        print(f"✅ Connected to {provider}")
        break
    except Exception as e:
        print(f"❌ {provider} failed: {e}")

if not client:
    client = MockClient()
    print("⚠️  Using mock client")

response = client.generate_content(your_prompt)
```

---

## Quick Reference Card

```
┌─────────────────────────────────────────┐
│  LLM Setup Checklist                    │
├─────────────────────────────────────────┤
│ ☐ pip install google-genai openai      │
│ ☐ cp .env.example .env                 │
│ ☐ Add API key from your provider       │
│ ☐ Set LLM_PROVIDER in .env             │
│ ☐ python demo.py                       │
│ ☐ See "Using {provider} API"           │
│ ☐ Success! 🎉                          │
└─────────────────────────────────────────┘
```

---

## API Key Format Cheat Sheet

| Provider | Key Starts With | Example |
|----------|----------------|---------|
| Gemini | `AIza` | `AIza_AbCdEfGhIjKlMn` |
| OpenAI | `sk-` | `sk-proj-xxxxx` |
| Anthropic | `sk-ant-` | `sk-ant-xxxxx` |

---

## Getting Help

1. **Quick Reference**: See [LLM_QUICK_REFERENCE.md](LLM_QUICK_REFERENCE.md)
2. **Full Documentation**: See [llm_integration/README.md](llm_integration/README.md)
3. **Implementation Details**: See [IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md)
4. **Code Changes**: See [IMPLEMENTATION_BEFORE_AND_AFTER.md](IMPLEMENTATION_BEFORE_AND_AFTER.md)

---

**You're all set! 🚀**

Just add your API key and run `python demo.py`
