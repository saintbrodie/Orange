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

Accept the model terms at https://huggingface.co/Lightricks/LTX-2.5 and download
the five selected components using ComfyUI or your authenticated model manager.
The manifest lists exact filenames and official download URLs. Place the
transformer in `diffusion_models`, Gemma encoder in `text_encoders`, both VAEs in
`vae`, and the spatial upscaler in `latent_upscale_models`. In Orange, open the
Curated Library, inspect the backend, and add the pack; existing models are reused.
An unauthenticated download from the gated repository may be refused. Orange
neither accepts the model terms nor handles that account consent on your behalf.

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
