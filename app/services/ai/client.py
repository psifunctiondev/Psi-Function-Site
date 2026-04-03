"""AI client for the prospect chat agent.

This module wraps the LLM interaction for the public-facing chat widget.
The agent helps prospective clients brainstorm how Psi Function can serve
their business.

Security considerations:
- System prompt constrains behavior to Psi Function topics
- Input length is capped
- Rate limiting should be applied at the route level
- No PII storage — conversations are ephemeral
"""

import os

SYSTEM_PROMPT = """You are a friendly, knowledgeable assistant on the Psi Function website.
Psi Function is a technology consulting firm that helps small and mid-size
businesses leverage modern technology — AI, cloud computing, automation,
data analytics, and custom software — to grow, compete, and operate more
efficiently.

Your role:
- Help visitors brainstorm how technology could improve their specific business
- Ask thoughtful questions about their challenges and goals
- Explain technical concepts in plain, accessible language
- Be warm, genuine, and curious — not salesy
- Suggest specific Psi Function services when relevant (Fractional CTO,
  Discovery, Blueprint, Construct, Realize, Project Management)

Boundaries:
- Stay on topic: business technology, consulting, Psi Function services
- If someone asks unrelated questions, gently redirect
- Never make up pricing, timelines, or guarantees
- Never share internal details about Psi Function's operations
- If someone is hostile or trolling, respond briefly and politely once,
  then disengage with: "I'd love to help when you have a business question.
  Feel free to reach out anytime at info@psifunction.com."

Keep responses concise — 2-4 sentences for most replies. This is a chat,
not an essay."""

MAX_INPUT_LENGTH = 2000
MAX_HISTORY_TURNS = 10


class AIClient:
    """Prospect chat AI client."""

    def __init__(self):
        self.api_key = os.getenv('OPENAI_API_KEY', '')
        self.model = os.getenv('CHAT_MODEL', 'gpt-4o-mini')

    def send_message(self, prompt: str, history: list | None = None) -> str:
        """Send a message and get a response.

        Args:
            prompt: The user's message.
            history: Optional list of prior messages as
                     [{"role": "user"|"assistant", "content": "..."}, ...]

        Returns:
            The assistant's reply text.
        """
        # Sanitize input
        prompt = prompt.strip()[:MAX_INPUT_LENGTH]
        if not prompt:
            return "I didn't catch that — could you try again?"

        # Build message list
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        if history:
            # Keep only recent turns
            for msg in history[-MAX_HISTORY_TURNS * 2:]:
                if msg.get("role") in ("user", "assistant"):
                    messages.append({
                        "role": msg["role"],
                        "content": str(msg["content"])[:MAX_INPUT_LENGTH],
                    })

        messages.append({"role": "user", "content": prompt})

        # If no API key configured, return a helpful placeholder
        if not self.api_key:
            return (
                "Thanks for your interest! Our chat assistant is being set up. "
                "In the meantime, feel free to reach out at info@psifunction.com "
                "— we'd love to hear about your business."
            )

        # Call LLM API
        try:
            import httpx

            resp = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 300,
                    "temperature": 0.7,
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            return (
                "I'm having a little trouble right now. Please try again in a moment, "
                "or reach out directly at info@psifunction.com."
            )
