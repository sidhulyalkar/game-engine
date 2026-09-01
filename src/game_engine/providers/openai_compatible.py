from __future__ import annotations

import json
import os
import urllib.request


class OpenAICompatibleClient:
    """Tiny dependency-free adapter for OpenAI-compatible chat-completions endpoints."""

    def __init__(self, name: str, model: str, base_url: str, api_key_env: str, timeout: int = 120):
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.timeout = timeout

    def complete(self, system: str, prompt: str) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(f"Missing API key environment variable: {self.api_key_env}")
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0.9,
        }).encode()
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read())
        return data["choices"][0]["message"]["content"]
