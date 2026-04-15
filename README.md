# Orange 🍊

![Orange UI Screenshot](docs/Screenshot.png)

Orange is a minimalist, dynamic web frontend wrapper around **ComfyUI**. It replaces the complex node-graph interface with a user-friendly, responsive experience that allows anyone to generate, edit, and upscale media via your local ComfyUI instance without knowing the node-spaghetti underneath.

## Features
- **Idiot-Proof UI**: Minimalistic design focused on clear inputs rather than backend complexity.
- **Dynamic Capabilities**: Tool availability and frontend UI adapt dynamically based on your configured workflows.
- **Real-Time Feedback**: Progress bars, queue positions, and system status directly inherited from ComfyUI websockets.
- **Extensible**: Simply drop in ComfyUI API workflows to add new generation paths.
- **Auto-Installer**: Simple `run.bat` and `run.sh` scripts manage the environment on Windows/Mac/Linux.

## Requirements
- Python 3
- A running instance of [ComfyUI](https://github.com/comfyanonymous/ComfyUI)

## Installation & Running

1. **Clone this repository**
2. **Double click `run.bat` (Windows) or execute `./run.sh` (Linux/Mac)**
   The startup script will automatically check for Python, install it if missing, create a virtual environment, install requirements, and start the frontend server on port `7070`.
3. Open your browser and navigate to `http://localhost:7070/`.

## Configuration
See the [Adding Workflows](docs/adding_workflows.md) guide to learn how to export your own ComfyUI node graphs and use them as new generation tools in Orange.

## To Do
- [ ] LTX Video Support
- [ ] ACE Step Support
