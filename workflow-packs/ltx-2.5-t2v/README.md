# LTX 2.5 Video

Local text-to-video and optional first-frame generation with synchronized audio,
adapted from ComfyUI's official `video_ltx2_5_t2v` and `video_ltx2_5_i2v` templates. The bundled JSON is flattened API format for Orange.
It uses native ComfyUI nodes, the distilled 22B transformer, two sampling stages,
a 2x latent upscaler, and the lighter Conv video VAE. Prompt enhancement is
omitted because Orange already has its own optional enhancement flow.

- Default: 97 frames at 24 fps (about 4 seconds), final 768x512.
- Ratios: 3:2 (768x512), 16:9 (1024x576), 9:16 (576x1024).
- Prompt, random seed, ratio, and length (2, 4, 6, 8, 10, or 12 seconds) are exposed in Orange.
- Upload an optional first frame to guide both generation stages, or leave it empty for text-to-video.
- A shared frame-count node keeps audio and video in sync; counts are rounded to 8n+1 frames, so actual duration is about one frame longer than the selected length.
- MP4 uses H.264 video and the generated soundtrack.
- INT8 ConvRot transformer and text encoder are selected on supported NVIDIA
  backends. Other backends select BF16, which requires substantially more memory.
  Plan for 32 GB+ VRAM with the INT8 stack; compatibility is checked by Preflight.

## Setup

1. Accept the model terms at https://huggingface.co/Lightricks/LTX-2.5 using
   your own Hugging Face account.
2. Create a read token, or a fine-grained token that can read the model, at
   https://huggingface.co/settings/tokens.
3. In Orange, open **Admin > General Settings > Hugging Face downloads**,
   paste the token, and click **Save token**.
4. Inspect and add the pack in the Curated Library. Orange reuses existing model
   files and downloads only missing components using the configured token.

You can also set `HF_TOKEN` on the Orange server; it takes precedence over a
saved token. Saved tokens use the server user's native OS credential store:
Windows Credential Manager, macOS Keychain, or Linux Secret Service. Orange
does not write new token files, and never falls back to plaintext storage.
Install the updated requirements and ensure the native credential store is
available and unlocked; headless Linux servers can use `HF_TOKEN` instead.
Existing `runtime/secrets/huggingface-token` files migrate automatically when
token settings or a download first reads them: Orange verifies the native
credential before deleting the old plaintext file. A failed migration preserves
the old file and reports an error. Remove any older backups yourself.
Credentials belong to the OS account running Orange and this installation path;
changing accounts or moving Orange requires saving the token again.
Other programs running as that OS user may also access the credential store.
The admin API returns only whether a token is configured; it
never returns the saved token. Remove it with **Remove saved token** (an
`HF_TOKEN` environment setting remains active until removed from the environment).
The token field has its own save action; leaving it blank preserves the saved
value. Files can still be downloaded with ComfyUI or an authenticated model
manager and Orange will reuse them.

A token does not accept the model terms or grant access that its account lacks.
A 401/403 download error asks the user to check the token and model access.
Orange authenticates only HTTPS requests to the exact `huggingface.co` origin
and strips authorization from redirects to external file storage. The same
credentials apply to download-size checks and both model installer paths.

## Sources and validation

- Template: https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_ltx2_5_t2v.json
- Models: https://huggingface.co/Lightricks/LTX-2.5
- Guide: https://docs.ltx.io/open-source-model/usage-guides/two-stage-generation/

Validated locally on 2026-10-27: native nodes passed backend validation; the
bundled default workflow generated a 97-frame 768x512 MP4 with H.264 video and
AAC audio. The library thumbnail is frame 30 of that render. No model download
was required because the selected files were already installed. This test used
the existing local ComfyUI backend, not a fresh Pinokio installation.

## Length and first-frame controls

The main workflow handles text-only requests. The alternate
`video_ltx_2_5_i2v.json` is selected only when a first-frame image is uploaded.
The source image is resized/preprocessed and injected at strengths 0.7 and 1.0
into the first and second sampling stages, following the official template.
Both graphs share the same five model bindings and duration control; installation
materializes and preflights both, and scheduled verification exercises both modes.

The API accepts the selected length as `duration` in seconds. Supported values
come from the tool's duration options. Unknown lengths are rejected before a job
is queued. Other tools retain their existing required-image behavior.

Control validation on 2026-10-27 exercised Orange's multipart API in both modes:
text-only and an uploaded first frame each generated 49-frame (2.04-second)
768x512 MP4s with audio when a two-second length was requested. The browser form
also showed the optional upload and all six duration choices, and hid these
controls when switching to a normal image tool.
