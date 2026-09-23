# Managed Local Prompt Enhancement

Orange can run prompt enhancement locally without requiring Ollama, LM Studio, or a cloud API key.

## Default model

Managed Local uses Google's **Gemma 4 E2B Instruct** QAT GGUF:

- model: `google/gemma-4-E2B-it-qat-q4_0-gguf`
- file: `gemma-4-E2B_q4_0-it.gguf`
- quantization: Q4_0 QAT
- download size: about 3.35 GB
- model revision: `347eef722ec7f151f37d1ef0b5c7c77d8de4efcb`
- expected SHA-256: `fa401b55b07ee70a54c6dae3903c783a6e65064312529ea57175cb5f8dec6634`

Orange intentionally downloads only the text model. Gemma's multimodal projection file is not needed for prompt expansion.

## Runtime

Orange owns a private pinned **llama.cpp** runtime rather than installing a system-wide service. The initial runtime build is `b10964`, with platform-specific release archives and SHA-256 verification.

Managed files live under:

```text
workflows/.runtime/prompt-enhancer/
├── llama.cpp/
├── models/
│   └── gemma-4-E2B_q4_0-it.gguf
├── downloads/
├── state.json
└── llama-server.log
```

This directory is local deployment state and is ignored by Git.

Supported packaged platforms are:

- Windows x64 and ARM64
- Linux x64 and ARM64
- macOS Apple Silicon and Intel

Other platforms can continue using Orange's existing Ollama or OpenAI-compatible provider support.

## Resource policy

Managed Local is deliberately **CPU-first**. Orange starts `llama-server` with zero GPU layers so prompt expansion does not reserve VRAM needed by ComfyUI generation workflows.

The server binds only to `127.0.0.1:7071` and uses llama.cpp's idle sleeping support. After five minutes without prompt-enhancement work, llama.cpp unloads the model and KV cache from memory. The next enhancement request wakes/reloads it automatically.

Orange starts the local server on demand the first time Managed Local is actually used; installing the model does not leave a permanent inference process consuming resources.

## Installation and state

Managed Local can be selected during first-run setup or installed later from **Admin → General Settings → AI Prompt Enhancer**.

Installation is backgrounded and reports:

- current file/stage
- downloaded bytes and expected bytes
- percentage
- transfer speed
- checksum verification
- extraction/readiness errors

If Orange restarts during installation, the state is marked interrupted and the Admin UI offers Retry. Completed files are reused.

The **Remove local model** action stops the private llama.cpp process and deletes only Orange's managed prompt-enhancer runtime. It does not touch ComfyUI models, Ollama, LM Studio, or other local LLM installations.

## Provider behavior

The config provider is `managed` and the model ID is fixed internally as `gemma-4-e2b`.

When Managed Local is selected, Orange intentionally ignores stale per-tool model-name overrides. This prevents an old OpenAI or Ollama model name from being sent to the private Gemma server after changing the global provider.

All normal Orange system-prompt and per-tool prompt override behavior still applies.
