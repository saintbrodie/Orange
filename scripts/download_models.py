import urllib.request
import os
import sys
import shutil
import subprocess

# Define the models and their download URLs
# Note: Some URLs are placeholders since they were not specified in the README.
# Update the placeholders with actual URLs as needed.
MODELS = {
    "loras": [
        {
            "filename": "Qwen-Image-2512-Lightning-8steps-V1.0-fp32.safetensors",
            "url": "https://huggingface.co/lightx2v/Qwen-Image-2512-Lightning/resolve/main/Qwen-Image-2512-Lightning-8steps-V1.0-fp32.safetensors"
        },
        {
            "filename": "NiceGirls_UltraReal_-_v1-0_Z-Image_Turbo.safetensors",
            "url": "https://civitai.com/api/download/models/2465980" 
        }
    ],
    "diffusion_models": [
        {
            "filename": "qwen_image_2512_bf16.safetensors",
            "url": "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_2512_bf16.safetensors"
        },
        {
            "filename": "z_image_turbo_bf16.safetensors",
            "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors" 
        },
        {
            "filename": "flux-2-klein-9b-kv-fp8.safetensors",
            "url": "https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-kv-fp8/resolve/main/flux-2-klein-9b-kv-fp8.safetensors" 
        }
    ],
    "clip": [
        {
            "filename": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
            "url": "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" 
        },
        {
            "filename": "qwen_3_4b.safetensors",
            "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors" 
        },
        {
            "filename": "qwen_3_8b_fp8mixed.safetensors",
            "url": "https://huggingface.co/Comfy-Org/flux2-klein-9B/resolve/main/split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors" 
        }
    ],
    "vae": [
        {
            "filename": "qwen_image_vae.safetensors",
            "url": "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors" 
        },
        {
            "filename": "flux2-vae.safetensors",
            "url": "https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors" 
        },
        {
            "filename": "ae.safetensors",
            "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors" 
        }
    ]
}

def download_file(url, dest_path, use_hf=False):
    if os.path.exists(dest_path):
        print(f"Already exists: {dest_path}")
        return

    if use_hf and url.startswith("https://huggingface.co/"):
        parts = url.replace("https://huggingface.co/", "").split("/")
        if "resolve" in parts:
            repo_id = f"{parts[0]}/{parts[1]}"
            revision_idx = parts.index("resolve") + 1
            revision = parts[revision_idx]
            file_path = "/".join(parts[revision_idx + 1:])
            
            print(f"Downloading {file_path}\n -> {dest_path} using hf_transfer...")
            try:
                from huggingface_hub import hf_hub_download
                os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
                cached_path = hf_hub_download(
                    repo_id=repo_id,
                    filename=file_path,
                    revision=revision
                )
                shutil.copy2(cached_path, dest_path)
                print(f"Saved to {dest_path}\n")
                return
            except Exception as e:
                print(f"HF download failed: {e}. Falling back to standard download...")

    print(f"Downloading {url}\n -> {dest_path}...")
    try:
        # Create a custom opener to handle user-agent since some sites (like Civitai) block generic Python urllib agents
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req) as response, open(dest_path, 'wb') as out_file:
            total_size = int(response.getheader('Content-Length', -1))
            count = 0
            block_size = 1024 * 8
            while True:
                data = response.read(block_size)
                if not data:
                    break
                count += 1
                out_file.write(data)
                progress_bar(count, block_size, total_size)
        print() # Newline after progress bar
    except Exception as e:
        print(f"\nFailed to download {url}: {e}")

def progress_bar(count, block_size, total_size):
    if total_size == -1: return
    downloaded = count * block_size
    percent = int(downloaded * 100 / total_size)
    sys.stdout.write(f"\rDownloading... {percent}% ({downloaded / (1024*1024):.2f} MB / {total_size / (1024*1024):.2f} MB)")
    sys.stdout.flush()

def main():
    print("Welcome to the Orange Model Downloader")
    comfy_dir = input("Enter the path to your ComfyUI models directory (e.g., C:/ComfyUI/models) or press enter to download here: ").strip()
    
    if not comfy_dir:
        comfy_dir = "models"
        
    use_hf = input("Would you like to install and use hf_transfer for up to 10x faster HuggingFace downloads? (y/n): ").strip().lower() == 'y'
    if use_hf:
        print("Installing huggingface_hub and hf_transfer...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "huggingface_hub", "hf_transfer"])
        except Exception as e:
            print(f"Failed to install HF tools: {e}. Will use standard download.")
            use_hf = False
            
    for category, model_list in MODELS.items():
        category_dir = os.path.join(comfy_dir, category)
        os.makedirs(category_dir, exist_ok=True)
        
        for model in model_list:
            dest_path = os.path.join(category_dir, model["filename"])
            if "example" in model["url"]:
                print(f"Skipping {model['filename']} - Please update the placeholder URL in the script.")
                continue
            download_file(model["url"], dest_path, use_hf)
            
    print("\nDownload process complete!")

if __name__ == "__main__":
    main()
