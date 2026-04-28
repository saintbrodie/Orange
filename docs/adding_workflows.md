# Adding ComfyUI Workflows to Orange

Orange works by wrapping around ComfyUI "API Workflows". This allows you to build complex generation node trees in ComfyUI and expose them as a simple, single-click tool in the Orange interface.

## Step 1: Exporting an API Workflow from ComfyUI

By default, saving a workflow in ComfyUI saves the GUI structure (node positions, colors, etc.). Orange requires the **API format**, which strips the visuals and only leaves the execution graph.

1. Open your ComfyUI interface in your browser (usually `http://127.0.0.1:8188`).
2. Click the gear icon (`⚙️`) in the ComfyUI control panel to open the **Settings** menu.
3. Check the box for **"Enable Dev mode Options"**.
4. Close the settings. You will now see a new button on the control panel called **"Save (API format)"**.
5. Build and test your workflow. Once working, click **"Save (API format)"**. 
6. Keep the resulting `.json` file handy.

## Step 2: Adding the Workflow via Tool Editor (Recommended)

The easiest way to add your workflow to Orange is by using the built-in Admin Dashboard Tool Editor.

1. Navigate to `http://localhost:7070/admin` in your browser.
2. Log in using your `adminKey` (default is `orangeadmin`).
3. Click on the **Tools** tab.
4. Click the **Upload Workflow** button or drag-and-drop your exported `.json` file onto the button.
5. Orange will automatically upload the file, parse your workflow, and attempt to automatically map the common inputs (Prompt, Image, Resolution, Seed).

### Configuring Node Mappings

Orange UI dynamically renders input fields based on the mappings you provide in the Tool Editor. If you map `prompt`, a text box will appear on the frontend. If you map `image`, a file uploader will appear.

*   **Prompt**: Connects to a string/text input (e.g., `CLIPTextEncode`).
*   **Image**: Connects to a `LoadImage` node. The Orange backend will automatically upload the user's file to ComfyUI and swap the filename into this node.
*   **Resolution**: Connects to the width and height integers (e.g., in `EmptyLatentImage`). You can also configure tool-specific custom aspect ratios here using the "Override Default Aspect Ratios" checkbox.
*   **Seed**: Connects to the random seed generator (e.g., in `KSampler` or `KSamplerAdvanced`). Make sure "Generate Random" is checked so Orange injects a new seed each time.
*   **Output Text**: (New) Connects to any node that outputs text (like `PreviewText` or a custom Lyrics node). This will display the text in a scrollable box in the results view.

### Output Types

You can specify the **Output Type** for each tool:
*   **Image**: Standard image output.
*   **Video**: Uses a video player for playback (supports MP4, WebM, MKV, MOV). Compatible with nodes like `VHS_VideoCombine`.
*   **Audio**: Uses a premium **WaveSurfer.js** player with a dynamic waveform visualization. Compatible with nodes like `SaveAudio`.

### Auto-Detection
The Tool Editor will attempt to automatically detect your node fields when you type a **Node ID**. For example:
*   Typing the ID of a `RandomNoise` or `KSampler` node will auto-fill the **Seed** mapping.
*   Typing the ID of a `CLIPTextEncode` node will auto-fill the **Prompt** mapping.


You can verify and adjust these mappings, as well as the tool's Display Name and ID, directly in the Tool Editor interface. Click "Save Tool Configuration" when finished.

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

There is no need to restart the backend when creating or editing tools! Because the Orange server reads the config dynamically, simply **refresh your browser** at the main Orange URL. Your new tool will appear in the sidebar automatically!
