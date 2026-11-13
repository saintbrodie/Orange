# MOSS-Image

Simplified from ComfyUI's native `image_moss_image_t2i` template, using the SFT
checkpoint. Orange exposes a prompt and three aspect ratios: 1024x1024,
1344x768, and 768x1344. Seeds are randomized automatically.

The API graph keeps the template's 25-step `er_sde`/simple sampler, CFG 2.5,
full denoise, negative conditioning, Flux2 latent, and small Flux2 VAE.
The template defaults to skip-layer guidance off; this graph connects the
diffusion loader directly to the sampler and removes the unused SLG branch.
Prompt upsampling and preview nodes are removed. Optional enhancement runs
through Orange's configured provider using `workflows/defaults/prompts/moss-image.txt`.
The ComfyUI graph always receives the final prompt directly.

Three dependencies are declared: MOSS SFT diffusion, its Qwen3.5 W4A8 GPTQ text
encoder (still required for image conditioning), and `flux2-vae_small`.
Modern NVIDIA backends prefer the published INT8 ConvRot diffusion checkpoint;
other backends select BF16. Existing compatible variants and subfolders are reused.
Layout boxes, image editing, and the Base checkpoint are outside this pack's scope.

## Validation

Validated on 2026-11-12 against local ComfyUI 0.45.0 on an RTX 5000 Ada (32 GB).
ComfyUI validation and Orange Preflight passed with installed INT8 diffusion and
W4A8 text encoder models. The default graph completed a full 25-step 1024x1024
generation. The library thumbnail is a separate 1344x768 coastal travel poster
generated with the same workflow and sampling settings, including MOSS lettering. BF16 fallback
selection/materialization is covered by tests; a BF16 GPU render and fresh model
download were not exercised.

Sources:

- https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_moss_image_t2i.json
- https://huggingface.co/Comfy-Org/MOSS-Image
