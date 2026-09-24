import unittest
from pathlib import Path
class AdminReleasePolishTests(unittest.TestCase):
 def test_provider_ui(self):
  r=Path(__file__).resolve().parents[1]; h=(r/'static/admin.html').read_text(); j=(r/'static/admin.js').read_text()
  self.assertIn('External API — OpenAI, Ollama, LM Studio, llama.cpp, OpenRouter',h); self.assertNotIn('Ollama (Native)',h); self.assertIn("if (activeValue === '__custom__') activeValue = '';",j); self.assertIn("const legacyOllamaProvider = llm.provider === 'ollama';",j)
 def test_runtime_flat(self):
  j=(Path(__file__).resolve().parents[1]/'static/managed-comfyui.js').read_text(); self.assertIn('hidden mt-5 border-t border-zinc-800/70 pt-5',j)
 def test_canceled_is_history_only(self):
  j=(Path(__file__).resolve().parents[1]/'static/workflow-pack-library.js').read_text(); self.assertIn("if (job?.state === 'canceled') return;",j); self.assertNotIn("if (job?.state === 'canceled') return 'canceled';",j)
