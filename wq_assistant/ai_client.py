import json
import os
import re

import requests
from urllib.parse import urlparse


class AIConfigError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(
        self,
        api_key=None,
        base_url="https://api.deepseek.com/chat/completions",
        model="deepseek-chat",
        timeout=120,
        temperature=0.2,
    ):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.base_url = normalize_chat_url(base_url)
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        if not self.api_key:
            raise AIConfigError(
                "DeepSeek API key is missing. Set DEEPSEEK_API_KEY or put ai_api_key in config.json."
            )

    def chat(self, system_prompt, user_prompt):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
        }
        response = requests.post(
            self.base_url,
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"AI request failed: {response.status_code} {response.text}")
        data = response.json()
        return data["choices"][0]["message"]["content"]


def normalize_chat_url(base_url):
    base_url = str(base_url).strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.path in {"", "/"}:
        return base_url + "/v1/chat/completions"
    if parsed.path.endswith("/v1"):
        return base_url + "/chat/completions"
    return base_url


def make_ai_client(config):
    return DeepSeekClient(
        api_key=config.get("ai_api_key") or os.environ.get("DEEPSEEK_API_KEY"),
        base_url=config.get("ai_base_url", "https://api.deepseek.com/chat/completions"),
        model=config.get("ai_model", "deepseek-chat"),
        timeout=int(config.get("ai_timeout_seconds", 120)),
        temperature=float(config.get("ai_temperature", 0.2)),
    )


def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", text)
        if not match:
            raise
        return json.loads(match.group(1))
