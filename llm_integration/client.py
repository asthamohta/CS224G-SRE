import os
import abc
from dotenv import load_dotenv
from google import genai

load_dotenv()

# Try to import LLM SDKs (optional)
# ---------------------------------------------------------------------------
# Optional SDK imports (each is only required if that provider is used)
# ---------------------------------------------------------------------------

try:
    from google import genai as _genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import anthropic
    import anthropic as _anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False



# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class LLMClient(abc.ABC):
    """Abstract base class for LLM clients."""
    
    @abc.abstractmethod
    def generate_content(self, prompt: str) -> str:
        """Generate content from the LLM."""
        pass
    
    @property
    def model_name(self) -> str:
        """Return the model being used."""
        pass


# ---------------------------------------------------------------------------
# Gemini (Google Generative AI)
# Docs: https://ai.google.dev/gemini-api/docs
# Install: pip install google-genai
# Key env var: GEMINI_API_KEY
# ---------------------------------------------------------------------------

class GeminiClient(LLMClient):
    def __init__(self, api_key: str = None, model: str = "gemini-2.5-flash"):
        if not GENAI_AVAILABLE:
            raise ImportError(
                "Google Generative AI SDK not installed. "
                "Run: pip install google-genai"
            )
        self.key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.key:
            raise ValueError("❌ No Gemini API Key found. Check your .env file.")

        self.client = genai.Client(api_key=self.key)
        self.model_id = "gemini-2.5-flash"

    @property
    def model_name(self) -> str:
        return self.model_id

    def generate_content(self, prompt: str) -> str:
        try:
            print(f"[LLM] Sending request to {self.model_id} (Gemini)...")
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt,
            )
            text = response.text
            if not text:
                raise ValueError(
                    f"Model {self.model_id} returned empty response. "
                    "If this is a thinking model (2.5-pro), it may require a paid quota tier."
                )
            return text
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                raise RuntimeError(
                    f"Gemini quota exhausted for {self.model_id}. "
                    "This model may not have a free tier. "
                    f"Original error: {e}"
                ) from e
            raise


# ---------------------------------------------------------------------------
# Claude (Anthropic)
# Docs: https://docs.anthropic.com/en/api
# Install: pip install anthropic
# Key env var: ANTHROPIC_API_KEY
# ---------------------------------------------------------------------------

class ClaudeClient(LLMClient):
    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-6"):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "Anthropic SDK not installed. "
                "Run: pip install anthropic"
            )
        self.key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.key:
            raise ValueError("No Anthropic API key found. Set ANTHROPIC_API_KEY in .env")
        self.client = _anthropic.Anthropic(api_key=self.key)
        self.model_id = model

    def generate_content(self, prompt: str, timeout: float = 120.0) -> str:
        try:
            print(f"[LLM] Sending request to {self.model_id} (Claude)...")
            message = self.client.messages.create(
                model=self.model_id,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                timeout=timeout,
            )
            return message.content[0].text
        except _anthropic.APITimeoutError:
            return f"Error: Request timed out after {timeout}s. Try a shorter prompt or increase timeout."
        except Exception as e:
            return f"Error: {e}"


# ---------------------------------------------------------------------------
# OpenAI (GPT)
# Docs: https://platform.openai.com/docs
# Install: pip install openai
# Key env var: OPENAI_API_KEY
# ---------------------------------------------------------------------------

class OpenAIClient(LLMClient):
    def __init__(self, api_key: str = None, model: str = "gpt-4o"):
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "OpenAI SDK not installed. "
                "Run: pip install openai"
            )
        self.key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.key:
            raise ValueError("No OpenAI API key found. Set OPENAI_API_KEY in .env")
        self.client = openai.OpenAI(api_key=self.key)
        self.model_id = model

    def generate_content(self, prompt: str) -> str:
        try:
            print(f"[LLM] Sending request to {self.model_id} (OpenAI)...")
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error: {e}"


# ---------------------------------------------------------------------------
# Mock (no API key needed — for CI / smoke testing)
# ---------------------------------------------------------------------------


class OpenAIClient(LLMClient):
    """OpenAI API client (GPT-4, GPT-3.5-turbo, etc.)."""
    
    def __init__(self, api_key=None, model=None):
        """Initializes the OpenAI API Client."""
        if not OPENAI_AVAILABLE:
            raise ImportError("❌ OpenAI SDK not installed. Run: pip install openai")

        self.key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.key:
            raise ValueError("❌ No OpenAI API Key found. Check your .env file.")

        self.model_id = model or os.getenv("OPENAI_MODEL", "gpt-4-turbo")
        self.client = openai.OpenAI(api_key=self.key)

    @property
    def model_name(self) -> str:
        return self.model_id

    def generate_content(self, prompt: str) -> str:
        try:
            print(f"📡 Sending request to {self.model_id}...")
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert SRE engineer specialized in root cause analysis."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                max_tokens=2048
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error: {str(e)}"


class AnthropicClient(LLMClient):
    """Anthropic Claude API client."""
    
    def __init__(self, api_key=None, model=None):
        """Initializes the Anthropic Claude API Client."""
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("❌ Anthropic SDK not installed. Run: pip install anthropic")

        self.key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.key:
            raise ValueError("❌ No Anthropic API Key found. Check your .env file.")

        self.model_id = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        self.client = anthropic.Anthropic(api_key=self.key)

    @property
    def model_name(self) -> str:
        return self.model_id

    def generate_content(self, prompt: str) -> str:
        try:
            print(f"📡 Sending request to {self.model_id}...")
            response = self.client.messages.create(
                model=self.model_id,
                max_tokens=2048,
                system="You are an expert SRE engineer specialized in root cause analysis.",
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            return response.content[0].text
        except Exception as e:
            return f"Error: {str(e)}"


class LLMClientFactory:
    """Factory for creating LLM clients based on provider configuration."""
    
    @staticmethod
    def create(provider=None, api_key=None, model=None):
        """
        Create an LLM client based on the provider.
        
        Args:
            provider: LLM provider (gemini, openai, anthropic). 
                     Defaults to LLM_PROVIDER env var or 'gemini'.
            api_key: API key for the provider (optional, reads from .env if not provided).
            model: Model name to use (optional, reads from env or uses default).
        
        Returns:
            LLMClient instance
        
        Raises:
            ValueError: If provider is unknown or API key is missing.
        """
        provider = provider or os.getenv("LLM_PROVIDER", "gemini").lower()
        
        if provider == "gemini":
            return GeminiClient(api_key=api_key)
        elif provider == "openai":
            return OpenAIClient(api_key=api_key, model=model)
        elif provider == "anthropic":
            return AnthropicClient(api_key=api_key, model=model)
        else:
            raise ValueError(
                f"❌ Unknown LLM provider: {provider}. "
                f"Supported: gemini, openai, anthropic"
            )


class MockClient(LLMClient):
    """Mock LLM client for testing (no API calls)."""
    
    def __init__(self):
        self.model_id = "mock"

    @property
    def model_name(self) -> str:
        return self.model_id

    def generate_content(self, prompt: str) -> str:
        return '{"root_cause_service": "mock", "confidence": 0.9, "reasoning": "mock response", "recommended_action": "none"}'


# ---------------------------------------------------------------------------
# Factory: build a client from a short provider string
# ---------------------------------------------------------------------------

_PROVIDER_MAP = {
    # Gemini variants
    "gemini":             lambda m: GeminiClient(model=m or "gemini-2.5-flash"),
    "gemini-2.5-flash":   lambda m: GeminiClient(model="gemini-2.5-flash"),
    "gemini-2.5-pro":     lambda m: GeminiClient(model="gemini-2.5-pro"),
    "gemini-1.5-pro":     lambda m: GeminiClient(model="gemini-1.5-pro"),
    # Claude variants
    "claude":             lambda m: ClaudeClient(model=m or "claude-sonnet-4-6"),
    "claude-opus":        lambda m: ClaudeClient(model="claude-opus-4-6"),
    "claude-sonnet":      lambda m: ClaudeClient(model="claude-sonnet-4-6"),
    "claude-haiku":       lambda m: ClaudeClient(model="claude-haiku-4-5-20251001"),
    # OpenAI variants
    "openai":             lambda m: OpenAIClient(model=m or "gpt-4o"),
    "gpt-4o":             lambda m: OpenAIClient(model="gpt-4o"),
    "gpt-4o-mini":        lambda m: OpenAIClient(model="gpt-4o-mini"),
    "gpt-4-turbo":        lambda m: OpenAIClient(model="gpt-4-turbo"),
    # Mock
    "mock":               lambda m: MockClient(),
}


def get_client(provider: str, model: str = None) -> LLMClient:
    """
    Build an LLM client from a short provider/model string.

    Examples:
        get_client("gemini")
        get_client("claude")
        get_client("openai", model="gpt-4o-mini")
        get_client("mock")

    The `provider` string is matched case-insensitively against the known
    aliases above. If `provider` contains a slash (e.g. "openai/gpt-4o-mini"),
    the part after the slash is used as the model name.
    """
    key = provider.lower()

    # Support "provider/model" shorthand  e.g. "gemini/gemini-1.5-pro"
    if "/" in key:
        key, model = key.split("/", 1)

    if key not in _PROVIDER_MAP:
        raise ValueError(
            f"Unknown provider '{provider}'. "
            f"Available: {', '.join(_PROVIDER_MAP)}"
        )
    return _PROVIDER_MAP[key](model)
