import os
import abc
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

# Try to import Google Generative AI SDK (optional)
try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

class LLMClient(abc.ABC):
    @abc.abstractmethod
    def generate_content(self, prompt: str) -> str:
        pass

class GeminiClient(LLMClient):
    def __init__(self, api_key=None):
        """Initializes the Gemini Developer API Client."""
        if not GENAI_AVAILABLE:
            raise ImportError("❌ Google Generative AI SDK not installed. Run: pip install google-genai")

        self.key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.key:
            raise ValueError("❌ No Gemini API Key found. Check your .env file.")

        self.client = genai.Client(api_key=self.key)
        # Using 2.5 Flash as verified in previous tests
        self.model_id = "gemini-2.5-flash"

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

class MockClient(LLMClient):
    def generate_content(self, prompt: str) -> str:
        return '{"root_cause_service": "mock", "confidence": 0.9}'