import os
import httpx
from typing import Optional

async def call_llm(
    provider: str,
    base_url: Optional[str],
    api_key: Optional[str],
    model: str,
    system_prompt: str,
    prompt: str
) -> str:
    """
    Call the configured LLM provider asynchronously and return the text result.
    Supports OpenAI-compatible, Ollama, Gemini, and Anthropic.
    """
    provider = provider.lower()
    
    # 1. Resolve API Key (Environment Variable takes precedence)
    resolved_key = None
    if provider == "openai":
        resolved_key = os.environ.get("OPENAI_API_KEY")
    elif provider == "gemini":
        resolved_key = os.environ.get("GEMINI_API_KEY")
    elif provider == "anthropic":
        resolved_key = os.environ.get("ANTHROPIC_API_KEY")
        
    if not resolved_key and api_key:
        resolved_key = api_key

    # Check if a key is required for cloud endpoints
    is_local = False
    if base_url:
        is_local = "localhost" in base_url or "127.0.0.1" in base_url

    if not resolved_key and not is_local and provider in ["gemini", "anthropic"]:
        raise ValueError(f"API Key is missing for cloud provider: {provider.capitalize()}")
    if not resolved_key and not is_local and provider == "openai" and base_url and "api.openai.com" in base_url:
        raise ValueError("OpenAI API Key is missing.")

    # 2. Call the provider
    async with httpx.AsyncClient(timeout=30.0) as client:
        if provider == "openai":
            # Handles OpenAI, LM Studio, llama.cpp, OpenRouter, and Ollama-OpenAI compatibility
            target_url = f"{base_url.rstrip('/')}/chat/completions" if base_url else "https://api.openai.com/v1/chat/completions"
            headers = {}
            if resolved_key:
                headers["Authorization"] = f"Bearer {resolved_key}"
            
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ]
            }
            
            res = await client.post(target_url, json=payload, headers=headers)
            try:
                res.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ValueError(f"Provider returned error: {e.response.text}")
            res_json = res.json()
            return res_json["choices"][0]["message"]["content"].strip()

        elif provider == "ollama":
            # Native Ollama API
            target_url = f"{base_url.rstrip('/')}/api/chat" if base_url else "http://127.0.0.1:11434/api/chat"
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "stream": False
            }
            
            res = await client.post(target_url, json=payload)
            try:
                res.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ValueError(f"Provider returned error: {e.response.text}")
            res_json = res.json()
            return res_json["message"]["content"].strip()

        elif provider == "gemini":
            # Native Gemini API
            url_base = base_url.rstrip('/') if base_url else "https://generativelanguage.googleapis.com"
            target_url = f"{url_base}/v1beta/models/{model}:generateContent?key={resolved_key}"
            
            payload = {
                "contents": [
                    {
                        "parts": [{"text": prompt}]
                    }
                ],
                "systemInstruction": {
                    "parts": [{"text": system_prompt}]
                }
            }
            
            res = await client.post(target_url, json=payload)
            try:
                res.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ValueError(f"Provider returned error: {e.response.text}")
            res_json = res.json()
            return res_json["candidates"][0]["content"]["parts"][0]["text"].strip()

        elif provider == "anthropic":
            # Native Anthropic API
            target_url = f"{base_url.rstrip('/')}/v1/messages" if base_url else "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": resolved_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            payload = {
                "model": model,
                "max_tokens": 300,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            }
            
            res = await client.post(target_url, json=payload, headers=headers)
            try:
                res.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ValueError(f"Provider returned error: {e.response.text}")
            res_json = res.json()
            return res_json["content"][0]["text"].strip()

        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
