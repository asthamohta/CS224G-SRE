import os
import abc
import json

class LLMClient(abc.ABC):
    @abc.abstractmethod
    def generate_content(self, prompt: str) -> str:
        pass

class MockClient(LLMClient):
    def generate_content(self, prompt: str) -> str:
        return json.dumps({
            "root_cause_service": "mock_service",
            "confidence": 0.9,
            "reasoning": "This is a mock response."
        })

class GeminiClient(LLMClient):
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found.")
        
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-2.0-flash')

    def generate_content(self, prompt: str) -> str:
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Error from Gemini: {e}"

class VertexClient(LLMClient):
    def __init__(self, project_id: str, location: str = "us-central1"):
        import vertexai
        from vertexai.generative_models import GenerativeModel
        
        # Initialize Vertex AI with the user's project
        vertexai.init(project=project_id, location=location)
        self.model = GenerativeModel("gemini-2.0-flash-exp")

    def generate_content(self, prompt: str) -> str:
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Error from Vertex AI: {e}"

class OpenAIClient(LLMClient):
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        # from openai import OpenAI
        # self.client = OpenAI(api_key=self.api_key)

    def generate_content(self, prompt: str) -> str:
        # response = self.client.chat.completions.create(
        #     model="gpt-4",
        #     messages=[{"role": "user", "content": prompt}]
        # )
        # return response.choices[0].message.content
        return "TODO: Uncomment imports and install openai"
