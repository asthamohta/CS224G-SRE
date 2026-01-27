import json

from llm_integration.client import MockClient

class RCAAgent:
    def __init__(self, client=None):
        self.client = client or MockClient()

    def analyze(self, context_packet):
        """
        Generates an RCA report based on the provided context packet.
        """
        # 1. Construct the Prompt
        prompt = self._construct_prompt(context_packet)
        
        # 2. Call LLM
        print("\n🤖 [Agent] Prompt constructed. Sending to LLM...")
        # print(prompt) # Debugging
        
        response_str = self.client.generate_content(prompt)
        
        # Try to parse JSON from the response
        try:
            # Often LLMs wrap JSON in ```json blocks
            cleaned = response_str.replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned)
        except:
             return {"raw_response": response_str}


    def _construct_prompt(self, context):
        """
        Builds the prompt for the LLM.
        """
        # Linearize the context for the LLM
        service_lines = []
        for node in context["related_nodes"]:
            status_emoji = "🔴" if node["status"] == "error" else "🟢"
            line = f"- Service: {node['service']} {status_emoji}"
            if node["events"]:
                for event in node["events"]:
                    line += f"\n  - Event: {event['type']} (Commit: {event['commit']}) at {event['timestamp']}"
            service_lines.append(line)
        
        context_str = "\n".join(service_lines)
        
        prompt = f"""
You are specific SRE Agent called RootScout.
You are investigating an alert on service: {context['focus_service']}.

Topology Context:
{context_str}

Task:
Identify the root cause of the failure. 
Look for recent changes (deployments, config changes) in dependencies that correlate with the error.
Return a JSON object with:
- root_cause_service: <name>
- confidence: <0-1>
- reasoning: <explanation>
- recommended_action: <action>
"""
        return prompt

    def _mock_llm_call(self, prompt, context):
        """
        Simulates an LLM response based on heuristics in the context.
        """
        # Simple heuristic to make the mock smart:
        # Find the first node with status 'error' and a recent event.
        suspect = None
        for node in context["related_nodes"]:
            if node["status"] == "error" and node["events"]:
                suspect = node
                break
        
        if suspect:
            return {
                "root_cause_service": suspect["service"],
                "confidence": 0.95,
                "reasoning": f"Service {suspect['service']} is reporting errors and had a deployment event recently.",
                "recommended_action": f"Rollback commit {suspect['events'][-1]['commit']}"
            }
        else:
             return {
                "root_cause_service": "unknown",
                "confidence": 0.1,
                "reasoning": "No obvious correlations found.",
                "recommended_action": "Escalate to human."
            }
