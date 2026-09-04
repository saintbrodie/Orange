import os
import shutil
import subprocess
import sys
import urllib.request

# Define the models and their download URLs.
MODELS = {
    "loras": [
        {
            "filename": "Qwen-Image-2512-Lightning-8steps-V1.0-fp32.safetensors",
            "url": "https://huggingface.co/lightx2v/Qwen-Image-2512-Lightning/resolve/main/Qwen-Image-2512-Lightning-8steps-V1.0-fp32.safetensors",
        },
        {
            "filename": "NiceGirls_UltraReal_-_v1-0_Z-Image_Turbo.safetensors",
            "url": "https://civitai.com/api/download/models/2465980",
        },
    ],
    "diffusion_models": [
        {
            "filename": "qwen_image_2512_bf16.safetensors",
            "url": "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_2512_bf16.safetensors",
        },
        {
            "filename": "z_image_turbo_bf16.safetensors",
            "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors",
        },
        {
            "filename": "flux-2-klein-9b-kv-fp8.safetensors",
            "url": "https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-kv-fp8/resolve/main/flux-2-klein-9b-kv-fp8.safetensors",
        },
    ],
    "clip": [
        {
            "filename": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
            "url": "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
        },
        {
            "filename": "qwen_3_4b.safetensors",
            "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors",
        },
        {
            "filename": "qwen_3_8b_fp8mixed.safetensors",
            "url": "https://huggingface.co/Comfy-Org/flux2-klein-9B/resolve/main/split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors",
        },
    ],
    "vae": [
        {
            "filename": "qwen_image_vae.safetensors",
            "url": "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors",
        },
        {
            "filename": "flux2-vae.safetensors",
            "url": "https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors",
        },
        {
            "filename": "ae.safetensors",
            "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors",
        },
    ],
}


def download_file(url, dest_path, use_hf=False):
    if os.path.exists(dest_path):
        print(f"Already exists: {dest_path}")
        return True

    part_path = dest_path + ".part"
    try:
        if os.path.exists(part_path):
            os.remove(part_path)
    except OSError:
        pass

    if use_hf and url.startswith("https://huggingface.co/"):
        parts = url.replace("https://huggingface.co/", "").split("/")
        if "resolve" in parts:
            repo_id = f"{parts[0]}/{parts[1]}"
            revision_idx = parts.index("resolve") + 1
            revision = parts[revision_idx]
            file_path = "/".join(parts[revision_idx + 1 :])

            print(f"Downloading {file_path}\n -> {dest_path} using Hugging Face Hub...")
            try:
                from huggingface_hub import hf_hub_download

                cached_path = hf_hub_download(repo_id=repo_id, filename=file_path, revision=revision)
                shutil.copy2(cached_path, part_path)
                os.replace(part_path, dest_path)
                print(f"Saved to {dest_path}\n")
                return True
            except Exception as exc:
                print(f"HF download failed: {exc}. Falling back to standard download...")
                try:
                    if os.path.exists(part_path):
                        os.remove(part_path)
                except OSError:
                    pass

    print(f"Downloading {url}\n -> {dest_path}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response, open(part_path, "wb") as out_file:
            total_size = int(response.getheader("Content-Length", -1))
            downloaded = 0
            block_size = 1024 * 1024
            while True:
                data = response.read(block_size)
                if not data:
                    break
                out_file.write(data)
                downloaded += len(data)
                progress_bar(downloaded, total_size)
            out_file.flush()
            os.fsync(out_file.fileno())

        if total_size > 0 and os.path.getsize(part_path) != total_size:
            raise IOError(
                f"Download size mismatch: expected {total_size} bytes, got {os.path.getsize(part_path)} bytes"
            )

        os.replace(part_path, dest_path)
        print()
        return True
    except Exception as exc:
        print(f"\nFailed to download {url}: {exc}")
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except OSError:
            pass
        return False


def progress_bar(downloaded, total_size):
    if total_size <= 0:
        sys.stdout.write(f"\rDownloading... {downloaded / (1024 * 1024):.2f} MB")
        sys.stdout.flush()
        return

    percent = min(100, int(downloaded * 100 / total_size))
    sys.stdout.write(
        f"\rDownloading... {percent}% ({downloaded / (1024 * 1024):.2f} MB / {total_size / (1024 * 1024):.2f} MB)"
    )
    sys.stdout.flush()


def main():
    print("Welcome to the Orange Model Downloader")
    comfy_dir = input(
        "Enter the path to your ComfyUI models directory (e.g., C:/ComfyUI/models) or press enter to download here: "
    ).strip()

    if not comfy_dir:
        comfy_dir = "models"

    use_hf = input("Would you like to use huggingface_hub for Hugging Face downloads? (y/n): ").strip().lower() == "y"
    if use_hf:
        print("Installing huggingface_hub...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "huggingface_hub"])
        except Exception as exc:
            print(f"Failed to install Hugging Face tools: {exc}. Will use standard downloads.")
            use_hf = False

    failures = []
    for category, model_list in MODELS.items():
        category_dir = os.path.join(comfy_dir, category)
        os.makedirs(category_dir, exist_ok=True)

        for model in model_list:
            dest_path = os.path.join(category_dir, model["filename"])
            if not download_file(model["url"], dest_path, use_hf):
                failures.append(model["filename"])

    if failures:
        print("\nDownload process completed with failures:")
        for filename in failures:
            print(f" - {filename}")
        sys.exit(1)

    print("\nDownload process complete!")


if __name__ == "__main__":
    main()
