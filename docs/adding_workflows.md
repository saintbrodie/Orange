# Adding ComfyUI Workflows to Orange

Orange works by wrapping around ComfyUI "API Workflows". This allows you to build complex generation node trees in ComfyUI and expose them as a simple, single-click tool in the Orange interface.

## Step 1: Exporting an API Workflow from ComfyUI

By default, saving a workflow in ComfyUI saves the GUI structure (node positions, colors, etc.). Orange requires the **API format**, which strips the visuals and only leaves the execution graph.

1. Open your ComfyUI interface in your browser (usually `http://127.0.0.1:8188`).
2. Click the gear icon (`⚙️`) in the ComfyUI control panel to open the **Settings** menu.
3. Check the box for **"Enable Dev mode Options"**.
4. Close the settings. You will now see a new button on the control panel called **"Save (API format)"**.
5. Build and test your workflow. Once working, click **"Save (API format)"**. 
6. Move the resulting `.json` file into the `Orange/workflows/` directory.

## Step 2: Mapping Nodes to the Orange UI

Now that Orange has the workflow file, you need to tell it which nodes represent the text prompt, the output dimensions, the random seed, and reference images.

Open `workflows/workflows-config.json` in a text editor.

You will see an array of `tools`. To add yours, create a new object in the `tools` array.

### Tool Object Structure

Here is a basic example of adding a new "Enhance Image" tool:

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

### Finding Your Node IDs

If you open your API workflow `.json` file (e.g., `my_exported_api_workflow.json`) in a text editor, you'll see a series of numbered keys (like `"3"`, `"6"`, `"10"`). These are your **Node IDs**. 

For example, if your node `"6"` is a `CLIPTextEncode` node, it will look like this:
```json
"6": {
  "inputs": {
    "text": "Your prompt goes here",
    "clip": [ "4", 1 ]
  },
  "class_type": "CLIPTextEncode"
}
```
In `workflows-config.json`, you map Orange's `prompt` input to this text node by declaring:
```json
"prompt": {
  "nodeId": "6",
  "field": "text"
}
```

### Supported Mappings

Orange UI dynamically renders input fields based on the mappings you provide. If you map `prompt`, a text box will appear. If you map `image`, a file uploader will appear.

*   `prompt`: Connects to a string/text input (e.g., `CLIPTextEncode`).
*   `width`: Connects to the width integer (e.g., in `EmptyLatentImage`).
*   `height`: Connects to the height integer (e.g., in `EmptyLatentImage`).
*   `seed` or `noise_seed` (or whatever the target field is named): Connects to the random seed generator (e.g., in `KSampler`). Ensure `"generateRandom": true` is included so Orange generates a new seed each time.
*   `image`: Connects to a `LoadImage` node. The Orange backend will automatically upload the user's file to ComfyUI and swap the filename into this node.

## Step 3: Enjoy!

Whenever you modify `workflows-config.json`, you shouldn't need to restart the backend. Because the Orange server reads the config dynamically, simply **refresh your browser**. Your new tool will appear in the sidebar automatically!
