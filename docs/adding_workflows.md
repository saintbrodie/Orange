# Adding ComfyUI Workflows to Orange

Orange works by wrapping around ComfyUI "API Workflows". This allows you to build complex generation node trees in ComfyUI and expose them as a simple, single-click tool in the Orange interface.

## Before You Start: Keep the Complexity in the Workflow

Orange is intentionally opinionated about what reaches the end user.

When building a workflow for Orange, configure as much as possible inside ComfyUI itself: model choice, sampler, scheduler, steps, CFG, LoRA strengths, negative conditioning, node-specific values, and other technical settings should normally be decided by the workflow engineer rather than exposed in Orange.

Orange should expose only the decisions the user genuinely needs to make for a generation, such as a prompt, one or more required images, and an intentionally curated aspect ratio choice.

A good rule is:

> If the workflow engineer can make the decision once, the Orange user should not have to make it every time.

The mapping system is deliberately small. It is not intended to become a generic form builder for every ComfyUI node input.

Before asking for a new Orange mapping type, first try to solve the requirement inside the workflow. Add a new mapping only when the interaction is genuinely part of the user's creative intent rather than a technical tuning parameter.

## Step 1: Exporting an API Workflow from ComfyUI

By default, saving a workflow in ComfyUI saves the GUI structure (node positions, colors, etc.). Orange requires the **API format**, which strips the visuals and only leaves the execution graph.

1. Open your ComfyUI interface in your browser (usually `http://127.0.0.1:8188`).
2. Click the gear icon (`⚙️`) in the ComfyUI control panel to open the **Settings** menu.
3. Check the box for **"Enable Dev mode Options"**.
4. Close the settings. You will now see a new button on the control panel called **"Save (API format)"**.
5. Build and test your workflow completely in ComfyUI first. Resolve technical choices there whenever possible.
6. Once working, click **"Save (API format)"**.
7. Keep the resulting `.json` file handy.

## Step 2: Adding the Workflow via Tool Editor (Recommended)

The easiest way to add your workflow to Orange is by using the built-in Admin Dashboard Tool Editor.

1. Navigate to `http://localhost:7070/admin` in your browser.
2. Log in using your `adminKey` (default is `orangeadmin`).
3. Click on the **Tools** tab.
4. Click the **Upload Workflow** button or drag-and-drop your exported `.json` file onto the button.
5. Orange will automatically upload the file, parse your workflow, and attempt to automatically map the common semantic inputs (Prompt, Image, Resolution, Seed).

### Configuring Node Mappings

Orange UI dynamically renders its supported input fields based on the mappings you provide in the Tool Editor. If you map `prompt`, a text box will appear on the frontend. If you map `image`, a file uploader will appear.

* **Prompt**: Connects to a string/text input (e.g., `CLIPTextEncode`).
* **Image**: Connects to a `LoadImage` node. The Orange backend will automatically upload the user's file to ComfyUI and swap the filename into this node.
* **Image 2**: Provides a second reference image only for workflows that genuinely require a second user-supplied image.
* **Resolution**: Connects to width and height integers (e.g., in `EmptyLatentImage`). You can also configure tool-specific custom aspect ratios using the "Override Default Aspect Ratios" checkbox.
* **Seed**: Connects to the random seed generator (e.g., in `KSampler` or `KSamplerAdvanced`). In most tools this should remain automatic rather than becoming a user-facing choice. Make sure "Generate Random" is checked when Orange should inject a new seed each time.
* **Output Text**: Connects to a node that outputs text (like `PreviewText` or a custom Lyrics node). This displays the text in a clean, copyable results interface.

### What Not to Map

Do not add a frontend control simply because a workflow node has a configurable field.

Values such as these should normally remain inside the ComfyUI workflow:
- Checkpoint / model
- Sampler
- Scheduler
- Steps
- CFG / guidance
- Denoise
- LoRA selection or strength
- Negative prompt internals
- ControlNet strength
- Internal video settings
- Technical resolution transforms

If a future workflow truly requires a new type of user interaction, it should be considered as a deliberate first-class Orange concept rather than exposing arbitrary node parameters.

### Output Types

You can specify the **Output Type** for each tool:
* **Image**: Standard image output.
* **Video**: Uses a video player for playback (supports MP4, WebM, MKV, MOV). Compatible with nodes like `VHS_VideoCombine`.
* **Audio**: Uses a premium **WaveSurfer.js** player with a dynamic waveform visualization. Compatible with nodes like `SaveAudio`.

### Auto-Detection

The Tool Editor will attempt to automatically detect useful Orange mappings from your node fields when you type a **Node ID**. For example:
* Typing the ID of a `RandomNoise` or `KSampler` node can auto-fill the **Seed** mapping.
* Typing the ID of a `CLIPTextEncode` node can auto-fill the **Prompt** mapping.

Auto-detection is intended to reduce setup work for the engineer, not to expose more technical controls to the end user.

You can verify and adjust these mappings, as well as the tool's Display Name and ID, directly in the Tool Editor interface. Click "Save Tool Configuration" when finished.

## Workflow Design Checklist

Before publishing a tool to Orange, ask:

1. Does the workflow run correctly in ComfyUI by itself?
2. Are model, sampler, steps, CFG, LoRAs, and similar implementation details already resolved inside the workflow?
3. Is every Orange input something the user truly needs to choose per generation?
4. Can any exposed decision be automated or fixed inside ComfyUI instead?
5. Are the mapped node IDs and fields stable in the exported API workflow?
6. Does the tool produce one of Orange's intended output types cleanly?

The ideal Orange tool can be technically sophisticated underneath while feeling extremely simple to use.

## Advanced: Manual JSON Configuration

If you prefer configuring tools manually or need to edit the raw data, you can edit `workflows/workflows-config.json` in a text editor.

You will see an array of `tools`. To add yours, create a new object in the `tools` array. The structure looks like this:

```json
{
  "id": "my-custom-tool",
  "name": "Enhance Image",
  "workflowFile": "my_exported_api_workflow.json",
  "nodeMapping": {
    "prompt": {
      "nodeId": "6",
      "field": "text"
    },
    "width": {
      "nodeId": "10",
      "field": "width"
    },
    "height": {
      "nodeId": "10",
      "field": "height"
    },
    "seed": {
      "nodeId": "3",
      "field": "seed",
      "generateRandom": true
    },
    "image": {
      "nodeId": "12",
      "field": "image"
    }
  }
}
```

*Note: If you modify `workflows-config.json` manually, make sure to move your exported `.json` file into the `workflows/` directory first.*

## Step 3: Enjoy!

There is no need to restart the backend when creating or editing tools. Because the Orange server reads the config dynamically, simply **refresh your browser** at the main Orange URL. Your new tool will appear in the sidebar automatically.

## Default Workflows

Orange separates core default workflows from your user customizations.
- Tracked defaults live in `workflows/defaults/`.
- Your active settings and customized tools live in `workflows/workflows-config.json`.

If you ever accidentally delete a default tool, or if you want to restore the official default workflows provided with updates, you can copy the `.json` files from `workflows/defaults/` into `workflows/`, or use the **Restore Default Workflows** button in the Admin Dashboard Settings menu.
