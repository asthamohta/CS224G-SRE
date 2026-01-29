import os
import abc
from google import genai
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

class LLMClient(abc.ABC):
    @abc.abstractmethod
    def generate_content(self, prompt: str) -> str:
        pass

class GeminiClient(LLMClient):
    def __init__(self, api_key=None):
        """Initializes the Gemini Developer API Client."""
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