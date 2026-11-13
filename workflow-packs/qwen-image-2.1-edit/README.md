# Qwen Image 2.1 Turbo Edit

Simplified from ComfyUI's native `image_qwen_image_2_1_turbo_image_edit` template.
Orange exposes a required source image, an optional second reference, and an edit
instruction. Seeds are randomized. Without a reference it uses the single-image
graph; uploading one selects `image_qwen_2_1_edit_reference.json` and feeds it to
`<image2>`. The source determines the output aspect ratio; native conditioning
resizes to approximately one megapixel at multiples of 32.

The API graphs use the Turbo diffusion checkpoint and the native template's
exact eight-step Euler schedule:
`1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0`.
Sampling uses `SamplerCustomAdvanced`, CFG 1, and automatic KV cache. The fixed
sigmas are intentional; replacing them with a generic scheduler is not equivalent.

Both graphs use `texture_fix_vae_for_qwen_image_2.1_bf16.safetensors` from
madebyollin for both reference encoding and output decoding. This is a deliberate
curated VAE choice instead of the upstream template's VAE.

Preview/comparison nodes, custom-canvas switches, unused references, and the
ComfyUI prompt-refiner model are omitted. Optional enhancement uses Orange's
configured provider and `workflows/defaults/prompts/qwen-image-2-1-edit.txt`.
This text-only enhancer rewrites instructions; it does not inspect the images.

The pack declares three dependencies: Turbo diffusion, Qwen3-VL text encoder,
and the texture-fix VAE. Modern NVIDIA backends prefer the published INT8
ConvRot diffusion/text encoder; other backends use their BF16 variants. Existing
compatible variants and backend subfolder paths are reused. Standard non-Turbo
diffusion weights and the original VAE are not considered substitutes. Stable pack
and tool IDs are retained so the switch does not create a duplicate library tool.

## Validation

Validated locally on 2026-11-12 against ComfyUI 0.45.0 on an RTX 5000 Ada (32 GB).
Both Turbo graphs passed native validation with installed INT8 models and the
texture-fix VAE. BF16 fallback selection/materialization is covered by tests;
a BF16 GPU render and fresh model downloads were not exercised.

Sources:

- https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_2_1_turbo_image_edit.json
- https://huggingface.co/Comfy-Org/Qwen-Image-2.1
- https://huggingface.co/madebyollin/texture-fix-vae-for-qwen-image-2.1

Single-image and two-image Turbo renders both completed at 1024x1024 using
the texture-fix VAE. The library thumbnail shows the actual single-image Turbo
result as a Before/After comparison: the mug becomes a moustached executive.
