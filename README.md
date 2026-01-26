# FunctionGemma Selenium Controller

This project implements a natural language interface for Selenium WebDriver using the FunctionGemma model. It allows you to control a web browser and automate interactions using plain English commands.

## Overview

The system consists of two main components:
1.  **API Server (`api_server.py`)**: Hosts the locally running FunctionGemma model and translates natural language commands into structured function calls (e.g., `click_element`, `send_keys`).
2.  **Interactive Session (`interactive_session.py`)**: A command-line interface (CLI) that accepts user input, sends it to the API server for interpretation, and executes the resulting Selenium actions locally.

## Features

*   **Natural Language Control**: specific code is not needed; just say "Click the login button".
*   **Local Processing**: Uses a local instance of the FunctionGemma model (no external API keys required).
*   **Supported Actions**:
    *   **Navigation**: `Go to https://google.com` or `Go to links.html`
    *   **Clicking**: `Click the close_button` (by ID)
    *   **Typing**: `Type 'searching' in search-box` (supports IDs and Name attributes)
    *   **Dropdowns**: `Select "Dark Mode" in theme-select`
    *   **Radio Buttons**: `click 'Pro Tier' in plan-pro`

## Prerequisites

*   **Python 3.8+**
*   **Google Chrome** installed (the project uses `webdriver.Chrome()`).
*   **Git** (to clone the repository).

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd func-gemma
    ```

2.  **Install dependencies:**
    It is recommended to use a virtual environment.
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    pip install -r requirements.txt
    ```

3.  **Model Setup:**
    Ensure the FunctionGemma model files are located in the `models/` directory. The application expects the model to be loadable via `transformers.AutoModelForCausalLM.from_pretrained("./models")`.

## Usage

running the project requires two separate terminal windows.

### Step 1: Start the API Server

In the first terminal, start the API server. This process handles the LLM processing and must remain running.

```bash
python api_server.py
```
*Wait until you see the message `Press CTRL+C to quit` before proceeding.*

### Step 2: Start the Interactive Session

In a second terminal, start the interactive client. This opens the browser and accepts your commands.

```bash
python interactive_session.py
```

### Example Session

Once the interactive session is running, you can type commands like:

```text
> Go to links.html
🌐 Navigating to URL: links.html

> Type 'searching' in search-box
  ⌨️ Typing 'John Doe' into element: {'id': 'search-box', 'text': 'searching'}

> Click close_button
  🖱️ Clicking element: {'id': 'close_button'}
```

## Project Structure

*   **`api_server.py`**: Flask server that wraps the FunctionGemma model. It exposes endpoints to process text into function arguments.
*   **`interactive_session.py`**: The client application. It captures user input, queries the API server, and executes Selenium commands on the local browser instance.
*   **`models/`**: Directory containing the local FunctionGemma model weights and configuration.
*   **`user-registration/`**: Contains example HTML files (like `links.html`) for testing the tool.

## Troubleshooting

*   **"Could not connect to API server"**: Ensure `api_server.py` is running and accessible at `http://localhost:5000`.
*   **Selenium Errors**: Ensure you have a compatible version of Chrome installed.
*   **Model Loading Issues**: If the model fails to load, check that the `models` directory contains valid `config.json` and `model.safetensors` files compatible with the `transformers` library.
