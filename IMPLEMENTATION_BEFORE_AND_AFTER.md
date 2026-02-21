# Implementation: Multi-LLM Support

## What Changed

### Before (Gemini-Only)
```python
# demo.py and run_simulation.py
from llm_integration.client import GeminiClient, MockClient

try:
    llm_client = GeminiClient()  # ❌ Hardcoded to Gemini
    print("✅ Using Gemini API (2.5 Flash)")
except Exception as e:
    llm_client = MockClient()

# No way to switch providers without code changes
```

### After (Multi-Provider)
```python
# demo.py and run_simulation.py
from llm_integration.client import LLMClientFactory, MockClient

try:
    llm_client = LLMClientFactory.create()  # ✅ Auto-selects from .env
    print(f"✅ Using {os.getenv('LLM_PROVIDER', 'gemini').upper()} API ({llm_client.model_name})")
except Exception as e:
    llm_client = MockClient()

# Switch providers just by changing LLM_PROVIDER in .env
```

## Architecture Improvements

### Provider Abstraction Layer

```python
# llm_integration/client.py

# Abstract Base
class LLMClient(abc.ABC):
    @abc.abstractmethod
    def generate_content(self, prompt: str) -> str:
        pass
    
    @property
    def model_name(self) -> str:
        pass

# Concrete Implementations
class GeminiClient(LLMClient):    # Google AI Studio
class OpenAIClient(LLMClient):    # ChatGPT / GPT-4
class AnthropicClient(LLMClient): # Claude
class MockClient(LLMClient):      # Testing

# Factory Pattern
class LLMClientFactory:
    @staticmethod
    def create(provider=None, api_key=None, model=None):
        # Automatically selects correct client
        # Reads from LLM_PROVIDER env variable
        # Handles configuration and error cases
```

## Files Modified

### 1. `llm_integration/client.py` - Enhanced
**Before**: ~45 lines (Gemini only + Mock)  
**After**: ~200 lines (3 providers + Factory)

**New Classes**:
- ✅ `OpenAIClient` - Full ChatGPT/GPT-4 support
- ✅ `AnthropicClient` - Full Claude support
- ✅ `LLMClientFactory` - Smart provider selection
- ✅ Enhanced `LLMClient` abstract base

**Features**:
- Dynamic SDK detection (graceful fallback if missing)
- Environment variable auto-loading
- Model selection per provider
- Consistent error messages

### 2. `.env.example` - Expanded
**Before**: Gemini-only config  
**After**: Multi-provider config with setup instructions

```env
# Provider selection (single line change to switch!)
LLM_PROVIDER=gemini|openai|anthropic

# All provider keys documented
GEMINI_API_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...

# Optional model overrides
OPENAI_MODEL=gpt-4-turbo
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```

### 3. `graph/run_simulation.py` - Simplified
**Before**:
```python
# Complex hardcoded logic
try:
    print("🔌 Connecting to Gemini API (2.5 Flash)...")
    real_client = GeminiClient()
    agent = RCAAgent(client=real_client, ...)
except Exception as e:
    print(f"⚠️ Gemini API Init Failed: {e}")
    agent = RCAAgent(client=MockClient(), ...)

if not agent:
    try:
        print(f"🔌 Connecting to Gemini API (Key: {api_key})...")
        real_client = GeminiClient(api_key=api_key)
        agent = RCAAgent(client=real_client, ...)
    except Exception as e:
        print(f"⚠️ Gemini API Init Failed: {e}")

if not agent:
    print("⚠️ Using Mock Client (No LLM connected).")
    agent = RCAAgent(client=MockClient(), ...)
```

**After**:
```python
# Clean factory pattern
try:
    llm_provider = os.getenv("LLM_PROVIDER", "gemini")
    print(f"🔌 Connecting to {llm_provider.upper()} LLM API...")
    client = LLMClientFactory.create()
    print(f"✅ Using model: {client.model_name}")
    agent = RCAAgent(client=client, github_output_path=github_output_path)
except Exception as e:
    print(f"⚠️  LLM Init Failed: {e}")
    print(f"   Falling back to Mock Client (no API calls)")
    agent = RCAAgent(client=MockClient(), github_output_path=github_output_path)
```

### 4. `demo.py` - Updated (Line 34, 508-516)
- Import statement updated: `GeminiClient` → `LLMClientFactory`
- Provider initialization using factory pattern
- Shows provider name and model in output

### 5. `llm_integration/README.md` - Complete Rewrite
**Before**: Basic scaffolding guide  
**After**: Complete implementation guide with:
- Quick start for all 3 providers
- Provider comparison table
- Usage examples (factory & direct)
- Troubleshooting guide
- Advanced features (future function calling)

## Benefits

| Aspect | Before | After |
|--------|--------|-------|
| **Providers** | 1 (Gemini) | 4 (Gemini, OpenAI, Anthropic, Mock) |
| **Lines of Code** | ~45 | ~200 (but more flexible) |
| **To Switch Providers** | Modify code | Change `.env` (1 line) |
| **Error Handling** | Basic try/catch | Graceful fallbacks + helpful messages |
| **SDK Detection** | Hardcoded import | Dynamic with informative errors |
| **Documentation** | Minimal | Comprehensive with examples |
| **Extensibility** | Hard | Easy (add new Client subclass) |

## How to Use Each Provider

### Switch to OpenAI
```bash
# Edit .env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-key
OPENAI_MODEL=gpt-4-turbo

# Run
python demo.py
# Output: ✅ Using openai API (gpt-4-turbo)
```

### Switch to Anthropic
```bash
# Edit .env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-your-key
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

# Run
python demo.py
# Output: ✅ Using anthropic API (claude-3-5-sonnet-20241022)
```

### Switch to Gemini
```bash
# Edit .env
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza-your-key

# Run
python demo.py
# Output: ✅ Using gemini API (gemini-2.5-flash)
```

## Code Examples

### Using the Factory (Recommended)
```python
from llm_integration.client import LLMClientFactory

# Automatically reads LLM_PROVIDER from .env
client = LLMClientFactory.create()
print(f"Using: {client.model_name}")
response = client.generate_content(prompt)
```

### Using a Specific Provider
```python
from llm_integration.client import OpenAIClient, AnthropicClient

# OpenAI
gpt = OpenAIClient(model="gpt-4-turbo")
response = gpt.generate_content(prompt)

# Claude
claude = AnthropicClient()
response = claude.generate_content(prompt)
```

### With Error Handling
```python
from llm_integration.client import LLMClientFactory, MockClient

try:
    client = LLMClientFactory.create()
except ValueError as e:
    print(f"Config error: {e}")
    client = MockClient()
except ImportError as e:
    print(f"SDK not installed: {e}")
    client = MockClient()

response = client.generate_content(prompt)
```

## Testing Strategy

### Test 1: Verify Gemini (Default)
```bash
# .env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key

python -c "from llm_integration.client import LLMClientFactory; c = LLMClientFactory.create(); print(c.model_name)"
# Output: gemini-2.5-flash
```

### Test 2: Verify OpenAI
```bash
# .env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-4-turbo

python -c "from llm_integration.client import LLMClientFactory; c = LLMClientFactory.create(); print(c.model_name)"
# Output: gpt-4-turbo
```

### Test 3: Verify Anthropic
```bash
# .env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_key

python -c "from llm_integration.client import LLMClientFactory; c = LLMClientFactory.create(); print(c.model_name)"
# Output: claude-3-5-sonnet-20241022
```

### Test 4: Verify Mock (No API needed)
```bash
python -c "from llm_integration.client import MockClient; c = MockClient(); print(c.generate_content('test'))"
# Output: {"root_cause_service": "mock", "confidence": 0.9}
```

## Performance Notes

| Provider | Latency | Cost/1M tokens | Recommended For |
|----------|---------|---|---|
| **Gemini** | 1-2s | $0.075 (input) | ✅ Free testing, demos |
| **GPT-4 Turbo** | 2-3s | $10 | ⭐ Production RCA |
| **Claude 3.5** | 1-2s | $3 (input) | 💰 Cost-sensitive |
| **Mock** | <1ms | $0 | 🧪 Testing |

## Next Steps

1. ✅ Multi-provider support implemented
2. ✅ Factory pattern in place
3. ✅ Documentation complete
4. 📋 Future: Function calling for multi-step RCA
5. 📋 Future: Streaming responses
6. 📋 Future: Token counting & cost tracking

## Files in This Implementation

- [llm_integration/client.py](llm_integration/client.py) - Core implementation
- [.env.example](.env.example) - Configuration template
- [graph/run_simulation.py](graph/run_simulation.py) - Updated usage
- [demo.py](demo.py) - Updated usage
- [llm_integration/README.md](llm_integration/README.md) - Detailed guide
- [LLM_QUICK_REFERENCE.md](LLM_QUICK_REFERENCE.md) - Quick reference
- [LLM_IMPLEMENTATION_SUMMARY.md](LLM_IMPLEMENTATION_SUMMARY.md) - Complete summary
