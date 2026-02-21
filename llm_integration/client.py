import os
import abc
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

# Try to import LLM SDKs (optional)
try:
    from google import genai
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
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


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


class GeminiClient(LLMClient):
    """Google Gemini API client."""
    
    def __init__(self, api_key=None):
        """Initializes the Gemini Developer API Client."""
        if not GENAI_AVAILABLE:
            raise ImportError("❌ Google Generative AI SDK not installed. Run: pip install google-genai")

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
            print(f"📡 Sending request to {self.model_id}...")
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt
            )
            return response.text
        except Exception as e:
            return f"Error: {str(e)}"


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
        return '{"root_cause_service": "mock", "confidence": 0.9}'