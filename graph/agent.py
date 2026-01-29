import json
import os
from llm_integration.client import MockClient

class RCAAgent:
    def __init__(self, client=None):
        """
        Initializes the RootScout RCA Agent.
        If no client is provided, it defaults to a MockClient for safety.
        """
        self.client = client or MockClient()

    def analyze(self, context_packet):
        """
        Generates a professional Root Cause Analysis (RCA) report.
        """
        # 1. Construct the expert-level SRE prompt
        prompt = self._construct_prompt(context_packet)
        
        # 2. Call the LLM provider (Gemini/Vertex)
        print("\n" + "="*50)
        print("📝 DEBUG: PROMPT SENT TO LLM")
        print("="*50)
        print(prompt)
        print("="*50 + "\n")
        
        print("🤖 [Agent] Prompt constructed. Sending to LLM...")
        
        response_str = self.client.generate_content(prompt)
        
        # 3. Parse and clean the JSON response
        try:
            # Remove Markdown code blocks if the LLM includes them
            cleaned = response_str.replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned)
        except Exception as e:
             # Fallback if the LLM returns unstructured text
             return {
                 "raw_response": response_str,
                 "error": f"Failed to parse JSON: {str(e)}"
             }

    def _construct_prompt(self, context):
        """
        Builds a high-context prompt using an expert on-call SRE persona.
        """
        # Linearize the context nodes for the LLM to understand the topology
        service_lines = []
        for node in context["related_nodes"]:
            status_emoji = "🔴" if node["status"] == "error" else "🟢"
            line = f"- Service: {node['service']} {status_emoji}"
            
            # Include deployment history if available
            if node["events"]:
                for event in node["events"]:
                    line += f"\n  - Event: {event['type']} (Commit: {event['commit']}) at {event['timestamp']}"
            service_lines.append(line)
        
        context_str = "\n".join(service_lines)
        
        # Expert Persona Prompting
        prompt = f"""
### SYSTEM ROLE
You are the Lead On-Call Site Reliability Engineer (SRE) for RootScout.
Your goal is to investigate outages in distributed systems and identify "Patient Zero."
You are analytical, data-driven, and focused on minimizing Mean Time to Recovery (MTTR).

### INCIDENT CONTEXT
An alert has fired on the focus service: **{context['focus_service']}**.
The following dependency graph and recent events have been retrieved:

{context_str}

### INVESTIGATION TASK
Analyze the topology and event data to:
1. Identify the root cause service (where the failure originated).
2. Determine if a specific deployment (commit) is the likely trigger.
3. Provide a clear reasoning for how the failure propagated.
4. Suggest a specific remediation command (e.g., git revert or kubectl rollout undo).

### RESPONSE FORMAT
Return ONLY a valid JSON object with the following structure:
{{
  "root_cause_service": "<service_name>",
  "confidence": <float between 0.0 and 1.0>,
  "reasoning": "<professional SRE explanation>",
  "recommended_action": "<specific command to fix the issue>"
}}
"""
        return prompt

    def _mock_llm_call(self, prompt, context):
        """
        Simulates an LLM response based on heuristics for local testing.
        """
        suspect = None
        for node in context["related_nodes"]:
            if node["status"] == "error" and node["events"]:
                suspect = node
                break
        
        if suspect:
            return {
                "root_cause_service": suspect["service"],
                "confidence": 0.95,
                "reasoning": f"Service {suspect['service']} is reporting errors and correlates with a recent deployment.",
                "recommended_action": f"Rollback commit {suspect['events'][-1]['commit']}"
            }
        else:
             return {
                "root_cause_service": "unknown",
                "confidence": 0.1,
                "reasoning": "No clear dependency failures or recent changes detected.",
                "recommended_action": "Escalate to senior on-call engineer."
            }