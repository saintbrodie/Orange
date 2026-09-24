from pathlib import Path

llm = Path("app/core/llm.py")
text = llm.read_text(encoding="utf-8")
old = '''        # Keep the UI provider list simple, but use Ollama's native chat API when
        # the configured OpenAI-compatible URL is clearly an Ollama server. The
        # native API lets Orange disable reasoning/thinking for this short task.
        if _is_ollama_endpoint(provider, base_url):
            url = _endpoint(_ollama_native_base(base_url), "http://127.0.0.1:11434", "api/chat")
            headers = {"Authorization": f"Bearer {resolved_key}"} if resolved_key else {}
            data = await _post_json(
                client,
                url,
                payload={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": _max_tokens()},
                },
                headers=headers,
                resolved_key=resolved_key,
            )
            try:
                return _clean_output(data["message"]["content"])
            except (KeyError, TypeError):
                raise LLMError(
                    "Prompt enhancement service returned an invalid response.",
                    "Ollama response was missing message.content.",
                )
'''
new = '''        # Keep the UI provider list simple, but use Ollama's native one-shot
        # generation API when the configured OpenAI-compatible URL is clearly
        # an Ollama server. Prompt enhancement is a transform, not a chat, and
        # /api/generate gives us direct system/prompt fields plus thinking control.
        if _is_ollama_endpoint(provider, base_url):
            url = _endpoint(_ollama_native_base(base_url), "http://127.0.0.1:11434", "api/generate")
            headers = {"Authorization": f"Bearer {resolved_key}"} if resolved_key else {}
            print(f"Prompt enhancement LLM route=ollama-generate model={model} url={url}")
            data = await _post_json(
                client,
                url,
                payload={
                    "model": model,
                    "system": system_prompt,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": _max_tokens()},
                },
                headers=headers,
                resolved_key=resolved_key,
            )
            try:
                return _clean_output(data["response"])
            except (KeyError, TypeError):
                raise LLMError(
                    "Prompt enhancement service returned an invalid response.",
                    "Ollama response was missing response text.",
                )
'''
if old not in text:
    raise SystemExit("expected Ollama chat block not found")
llm.write_text(text.replace(old, new), encoding="utf-8")

tests = Path("tests/test_llm.py")
text = tests.read_text(encoding="utf-8")
text = text.replace(
    "async def test_ollama_openai_url_uses_native_chat_without_thinking(self):",
    "async def test_ollama_openai_url_uses_native_generate_without_thinking(self):",
)
text = text.replace(
    'json_data={"message": {"content": "enhanced"}}',
    'json_data={"response": "enhanced"}',
    1,
)
text = text.replace(
    'self.assertEqual(url, "http://192.168.1.50:11434/api/chat")',
    'self.assertEqual(url, "http://192.168.1.50:11434/api/generate")',
)
needle = '''        self.assertFalse(kwargs["json"]["stream"])
        self.assertFalse(kwargs["json"]["think"])
        self.assertEqual(kwargs["json"]["options"]["num_predict"], 512)
'''
replacement = '''        self.assertEqual(kwargs["json"]["system"], "system")
        self.assertEqual(kwargs["json"]["prompt"], "prompt")
        self.assertFalse(kwargs["json"]["stream"])
        self.assertFalse(kwargs["json"]["think"])
        self.assertEqual(kwargs["json"]["options"]["num_predict"], 512)
'''
if needle not in text:
    raise SystemExit("expected Ollama assertions not found")
tests.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
