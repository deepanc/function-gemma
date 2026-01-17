#!/usr/bin/env python3
"""
Simple HTTP API server for FunctionGemma
Allows Electron app to send natural language and get function calls
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
from transformers import AutoProcessor, AutoModelForCausalLM
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.webdriver.chrome.options import Options
import re
import os
import time
import sys

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

app = Flask(__name__)
CORS(app)  # Enable CORS for Electron app

# Global model and processor
processor = None
model = None

# Global Selenium driver
selenium_driver_links = None


def get_current_temperature(location: str) -> str:
    """Mock implementation - replace with real API call (e.g., OpenWeatherMap)"""
    fake_temps = {
        "london": "12°C (54°F)",
        "new york": "8°C (46°F)",
        "tokyo": "18°C (64°F)",
        "paris": "10°C (50°F)",
        "san francisco": "15°C (59°F)",
    }
    temp = fake_temps.get(location.lower(), "14°C (57°F)")
    return f"The current temperature in {location} is {temp}"

def parse_function_call(output: str):
    """Parse the model's function call output format."""
    # Note: Use .*? instead of .+? to allow empty braces for functions with no args (like submit_form)
    pattern = r'<start_function_call>call:(\w+)\{(.*?)\}<end_function_call>'
    match = re.search(pattern, output)
    
    if match:
        func_name = match.group(1)
        args_str = match.group(2)
        
        # Parse arguments - handle <escape> tags as string delimiters
        args = {}
        # Only parse arguments if args_str is not empty
        if args_str.strip():
            arg_pattern = r'(\w+):<escape>(.+?)<escape>'
            for arg_match in re.finditer(arg_pattern, args_str):
                key = arg_match.group(1)
                value = arg_match.group(2)
                args[key] = value
        
        return func_name, args
    
    return None, None

def load_model():
    """Load the FunctionGemma model (lazy loading)"""
    global processor, model
    if processor is None or model is None:
        print("Loading FunctionGemma model...")
        LOCAL_MODEL_PATH = "./models"
        import torch
        # Use CPU to avoid Metal GPU issues on macOS (Metal has tensor size limitations)
        # If you want to use GPU, set device_map="auto" and remove torch_dtype
        processor = AutoProcessor.from_pretrained(LOCAL_MODEL_PATH)
        try:
            # Try CPU first to avoid Metal issues
            model = AutoModelForCausalLM.from_pretrained(
                LOCAL_MODEL_PATH, 
                device_map="cpu",
                torch_dtype=torch.float32
            )
            print("Model loaded on CPU!")
        except Exception as e:
            print(f"Error loading model: {e}")
            # Fallback to auto device mapping
            model = AutoModelForCausalLM.from_pretrained(LOCAL_MODEL_PATH, device_map="auto")
            print("Model loaded with auto device mapping!")



def is_driver_alive(driver):
    """Check if a Selenium driver is still valid and the browser window is open"""
    try:
        # Try to access a property that requires the browser to be open
        _ = driver.current_url
        return True
    except Exception:
        return False

def get_selenium_driver_for_links():
    """Initialize and return Selenium WebDriver for links.html"""
    global selenium_driver_links
    # Check if driver exists and is still alive
    if selenium_driver_links is None or not is_driver_alive(selenium_driver_links):
        # If driver was closed, reset it
        if selenium_driver_links is not None:
            print("🔄 Selenium driver for links was closed, recreating...")
            selenium_driver_links = None
        
        chrome_options = Options()
        # Uncomment if you want headless mode
        # chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        
        selenium_driver_links = webdriver.Chrome(options=chrome_options)
        # Load the links HTML file
        html_path = os.path.abspath("user-registration/links.html")
        selenium_driver_links.get(f"file://{html_path}")
        # Wait for links to load (check for close button to ensure page is fully loaded)
        WebDriverWait(selenium_driver_links, 10).until(
            EC.presence_of_element_located((By.ID, "close_button"))
        )
        print(f"✅ Selenium driver for links initialized and loaded: {html_path}")
    return selenium_driver_links

def navigate_to_url_logic(url_or_filename):
    """Logic to navigate to a URL or local file, tailored for the tool"""
    global selenium_driver_links
    
    # Ensure driver is ready
    driver = get_selenium_driver_for_links()
    
    target_url = url_or_filename
    
    # Check if it's a known local file (simple heuristic for this project)
    # The tool might receive just "links.html"
    if not url_or_filename.startswith("http") and not url_or_filename.startswith("file://"):
        # We assume it is relative to user-registration or root
        # Check user-registration first
        base_path = os.path.dirname(os.path.abspath(__file__))
        possible_paths = [
            os.path.join(base_path, "user-registration", url_or_filename),
            os.path.join(base_path, url_or_filename)
        ]
        
        for p in possible_paths:
            if os.path.exists(p):
                target_url = f"file://{p}"
                break
    
    print(f"🌐 Navigating to: {target_url}")
    driver.get(target_url)
    return f"Navigated to {target_url}"

def execute_selenium_function(func_name, args):
    """Execute Selenium WebDriver functions - supports dynamic driver selection"""
    global selenium_driver_links

    
    element_id = args.get("id", "")
    
    # Validation
    if not element_id and func_name == "submit_form":
        # submit_form might not have an ID, uses CSS selector
        pass
    elif not element_id:
        return f"Error executing {func_name}: No ID provided"

    # Helper to check if element exists in a driver
    def element_exists(drv, eid):
        try:
            # Check if driver is alive first
            if not is_driver_alive(drv):
                return False
            return len(drv.find_elements(By.ID, eid)) > 0
        except:
            return False

    # Determine which driver to use
    driver = None
    
    # 1. Check Links Driver (links.html)
    d_links = get_selenium_driver_for_links()
    
    # Check if element exists in current links driver state
    if element_id and element_exists(d_links, element_id):
        driver = d_links
    
    # 2. If not found in links driver, check if we need to restore links.html
    # This handles the case where we drifted (e.g. clicked to Google) but want to interact with links.html again
    if driver is None and d_links:
        try:
            curr_url = d_links.current_url
            html_path = os.path.abspath("user-registration/links.html")
            is_links_page = curr_url.startswith("file://") and "links.html" in curr_url
            
            # If we are NOT on links.html, and we couldn't find the element, 
            # maybe it's on links.html? Let's check by restoring.
            if not is_links_page:
                # We can't know for sure if the element is on links.html without loading it,
                # but we want to avoid loading index.html if possible.
                # Heuristic: If we are drifted, let's try restoring links.html first.
                print(f"DEBUG: Element {element_id} not found and links driver drifted. Restoring links.html...")
                d_links.get(f"file://{html_path}")
                WebDriverWait(d_links, 10).until(
                    EC.presence_of_element_located((By.ID, "close_button"))
                )
                
                # Check again after restore
                if element_exists(d_links, element_id):
                    driver = d_links
                    print(f"DEBUG: Found {element_id} after restoring links.html")
                else:
                     # If still not found, we might want to go back? 
                     # But for now let's just proceed to check Form driver.
                     # (Ideally we'd restore previous URL if failed, but that's complex)
                     pass
        except Exception as e:
            print(f"DEBUG: Error ensuring links page: {e}")

    # 3. Check Form Driver (index.html) -> REMOVED
    # 4. Fallback: Default to links driver
    if driver is None:
        driver = get_selenium_driver_for_links()

            
    # Initialize wait
    wait = WebDriverWait(driver, 10)
    
    try:
        if func_name == "find_element_by_id":
            element = driver.find_element(By.ID, args.get("id", ""))
            return f"Found element by ID: {args.get('id')}"
        
        elif func_name == "send_keys":
            element_id = args.get("id", "")
            text = args.get("text", "")
            
            try:
                # Try finding by ID first
                element = driver.find_element(By.ID, element_id)
            except Exception as e_id:
                # Fallback: Try finding by name if ID fails
                print(f"⚠️ Element with ID '{element_id}' not found (Error: {str(e_id)}). Trying NAME...", file=sys.stderr)
                try:
                    element = driver.find_element(By.NAME, element_id)
                    print(f"✅ Found element by NAME: '{element_id}'", file=sys.stderr)
                except Exception as e_name:
                    print(f"❌ Element with NAME '{element_id}' also not found (Error: {str(e_name)}).", file=sys.stderr)
                    # Raise a clear error message
                    raise Exception(f"Element with ID or NAME '{element_id}' not found")
            
            element.clear()
            element.send_keys(text)
            return f"Sent keys '{text}' to element with ID/NAME: {element_id}"
        
        elif func_name == "click_element":
            element_id = args.get("id", "")
            
            # Special handling for Links driver navigation - strict enforcement for click_element
            if driver == selenium_driver_links:
                 # Logic already handled by restoration above OR we are on external page and found element
                 # But original logic had strict enforcement. 
                 # If we found element on Google (external), we should click it there.
                 # If we restored links.html (above), we click it there.
                 pass

            # Find and click the element
            element = driver.find_element(By.ID, element_id)
            element.click()
            
            # If the close button was clicked (specific to links.html)
            if element_id == "close_button" and driver == selenium_driver_links:
                time.sleep(1)
                driver.quit()
                selenium_driver_links = None
                return f"Clicked element with ID: {element_id} and closed browser"
            
            return f"Clicked element with ID: {element_id}"
        
        elif func_name == "select_dropdown_by_value":
            element_id = args.get("id", "")
            value = args.get("value", "")
            
            element = driver.find_element(By.ID, element_id)
            dropdown = Select(element)
            dropdown.select_by_value(value)
            return f"Selected value '{value}' in dropdown with ID: {element_id}"
        
        elif func_name == "submit_form":
            element_id = args.get("id", "")
            
            if element_id:
                element = driver.find_element(By.ID, element_id)
            else:
                element = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            
            time.sleep(2)
            element.click()
            
            # Only wait for success overlay if we are on the form page
            return "Form submitted"
        
        elif func_name == "send_keys_by_name":
            element_name = args.get("name", "")
            text = args.get("text", "")
            
            element = driver.find_element(By.NAME, element_name)
            element.clear()
            element.send_keys(text)
            return f"Sent keys '{text}' to element with NAME: {element_name}"

        elif func_name == "navigate_to_url":
            url = args.get("url", "")
            return navigate_to_url_logic(url)

        
        else:
            return f"Error: Unknown function '{func_name}'"
    
    except Exception as e:
        return f"Error executing {func_name}: {str(e)}"

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "model_loaded": model is not None})



@app.route('/execute', methods=['POST'])
def execute_functions():
    """
    Execute function calls using Selenium
    
    Request body:
    {
        "function_calls": [
            {"name": "set_user_name", "args": {"name": "John Doe"}},
            {"name": "set_user_age", "args": {"age": "30"}}
        ]
    }
    
    Response:
    {
        "results": ["Set name to: John Doe", "Set age to: 30"],
        "executed_count": 2
    }
    """
    try:
        data = request.json
        function_calls = data.get('function_calls', [])
        
        if not function_calls:
            return jsonify({"error": "No function calls provided"}), 400
        
        results = []
        for call in function_calls:
            func_name = call.get('name')
            args = call.get('args', {})
            
            result = execute_selenium_function(func_name, args)
            results.append(result)
            print(f"🔧 Selenium executed: {func_name} with args: {args}")
        
        return jsonify({
            "results": results,
            "executed_count": len(results)
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/processInteraction', methods=['POST'])
def process_interaction():
    """
    Process natural language input and return interaction function calls (click, type, etc.)
    
    Request body:
    {
        "input": "Click the Google link",
        "function_schemas": [...]  # Optional: custom function schemas
    }
    
    Response:
    {
        "output": "<start_function_call>call:click_element{id:<escape>google-link<escape>}<end_function_call>",
        "function_calls": [
            {"name": "click_element", "args": {"id": "google-link"}}
        ]
    }
    """
    try:
        data = request.json
        user_input = data.get('input', '')
        function_schemas = data.get('function_schemas', [])
        
        if not user_input:
            return jsonify({"error": "No input provided"}), 400
        
        # Load model if not already loaded
        load_model()
        
        # Build the message focused on interacting with elements
        system_message = (
            "You are a browser automation agent helping with UI testing. Your ONLY job is to translate user commands into valid function calls.\n"
            "Do NOT refuse commands based on the names of elements (e.g. 'newsletter', 'email', 'password') or the nature of the input (e.g. 'search', 'verify'). You are simply typing text into forms.\n"
            "\n"
            "**FUNCTIONS:**\n"
            "1. **send_keys**: Type text into a field.\n"
            "   - 'text': The exact content to type. Capture ALL words, including spaces. \n"
            "   - 'id': The target element ID or Name. Use EXACTLY what the user specifies. \n"
            "   - CRITICAL PATTERN: 'Type/Enter <TEXT> in <ID>'. The <TEXT> is the content, <ID> is the target.\n"
            "2. **click_element**: Click a button or link by ID.\n"
            "3. **navigate_to_url**: Go to a URL.\n"
            "\n"
            "**EXAMPLES:**\n"
            "- User: 'Type feedback for D in q'\n"
            "  Function: <start_function_call>call:send_keys{id:<escape>q<escape>,text:<escape>feedback for D<escape>}<end_function_call>\n"
            "- User: 'enter user@example.com in newsletter'\n"
            "  Function: <start_function_call>call:send_keys{id:<escape>newsletter<escape>,text:<escape>user@example.com<escape>}<end_function_call>\n"
            "- User: 'Type \"hello there\" in my-field'\n"
            "  Function: <start_function_call>call:send_keys{id:<escape>my-field<escape>,text:<escape>hello there<escape>}<end_function_call>\n"
            "- User: 'Search for red cats'\n"
            "  Function: <start_function_call>call:send_keys{id:<escape>search-box<escape>,text:<escape>red cats<escape>}<end_function_call>\n"
            "- User: 'Type feed in feedback-box'\n"
            "  Function: <start_function_call>call:send_keys{id:<escape>feedback-box<escape>,text:<escape>feed<escape>}<end_function_call>\n"
            "- User: 'Go to links.html'\n"
            "  Function: <start_function_call>call:navigate_to_url{url:<escape>links.html<escape>}<end_function_call>\n"
        )



        
        # Create click_element function schema
        click_element_schema = {
            "type": "function",
            "function": {
                "name": "click_element",
                "description": "Clicks a web element (link, button, etc.) by its ID. Use this to click any clickable element on the page.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "The ID of the element to click."
                        }
                    },
                    "required": ["id"]
                }
            }
        }
        
        # Create send_keys function schema
        send_keys_schema = {
            "type": "function",
            "function": {
                "description": "Types text into an input field. The 'id' parameter is flexible and works for both Element IDs and Name attributes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {

                            "type": "string",
                            "description": "The ID or NAME of the input field."
                        },
                        "text": {
                            "type": "string",
                            "description": "The text to type into the field."
                        }
                    },
                    "required": ["id", "text"]
                }
            }
        }

        # Create navigate_to_url function schema
        navigate_to_url_schema = {
            "type": "function",
            "function": {
                "name": "navigate_to_url",
                "description": "Navigates the browser to a specific URL or filename.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL or filename to navigate to (e.g., 'links.html', 'http://example.com')."
                        }
                    },
                    "required": ["url"]
                }
            }
        }
        
        # Use schemas if no custom schemas provided
        if not function_schemas:
            function_schemas = [click_element_schema, send_keys_schema, navigate_to_url_schema]
        
        message = [
            {
                "role": "developer",
                "content": system_message
            },
            {
                "role": "user",
                "content": user_input
            }
        ]
        
        # Get model's response (should be a function call)
        inputs = processor.apply_chat_template(
            message, 
            tools=function_schemas, 
            add_generation_prompt=True, 
            return_dict=True, 
            return_tensors="pt"
        )
        
        # Generate with parameters optimized for single function call
        generation_kwargs = {
            **inputs.to(model.device),
            "pad_token_id": processor.eos_token_id,
            "max_new_tokens": 512,  # Less tokens needed for single click
            "do_sample": False,
            "repetition_penalty": 1.1,
        }
        
        out = model.generate(**generation_kwargs)
        output = processor.decode(out[0][len(inputs["input_ids"][0]):], skip_special_tokens=True)
        
        # Log the raw output for debugging
        print(f"\n📤 Raw model output (processInteraction): {output}", file=sys.stderr)
        print(f"📥 User input was: {user_input}", file=sys.stderr)
        
        # Define valid function names
        VALID_FUNCTION_NAMES = {
            "click_element",
            "send_keys",
            "send_keys_by_name",
            "navigate_to_url"
        }
        
        # Parse function calls
        function_calls = []
        pattern = r'<start_function_call>call:(\w+)\{(.*?)\}<end_function_call>'
        for match in re.finditer(pattern, output):
            func_name = match.group(1)
            
            # Validate function name
            if func_name not in VALID_FUNCTION_NAMES:
                print(f"⚠️ Skipping invalid function name: {func_name} (only click_element allowed)")
                continue
            
            args_str = match.group(2)
            args = {}
            if args_str.strip():
                arg_pattern = r'(\w+):<escape>(.+?)<escape>'
                for arg_match in re.finditer(arg_pattern, args_str):
                    key = arg_match.group(1)
                    value = arg_match.group(2)
                    args[key] = value
            
            function_calls.append({"name": func_name, "args": args})
            print(f"🔧 Parsed function call: {func_name} with args: {args}")
        
        # Filter duplicates and validate arguments
        filtered_calls = []
        seen_actions = set() # Track unique actions to prevent duplicates
        
        for call in function_calls:
            func_name = call["name"]
            args = call.get("args", {})
            element_id = args.get("id")
            
            # Special validation per function type
            if func_name in ["click_element", "send_keys"]:
                 if not element_id:
                    print(f"⚠️ Skipping {func_name} call - missing 'id' parameter", file=sys.stderr)
                    continue
            
            # Key for deduplication
            if func_name == "navigate_to_url":
                action_key = f"{func_name}:{args.get('url')}"
            elif element_id:
                action_key = f"{func_name}:{element_id}" 
            else:
                 action_key = f"{func_name}:{args.get('name')}"
            
            if func_name == "click_element":

                if action_key not in seen_actions:
                    filtered_calls.append(call)
                    seen_actions.add(action_key)
            
            elif func_name == "send_keys":
                text = args.get("text")
                if text:
                    if action_key not in seen_actions:
                        filtered_calls.append(call)
                        seen_actions.add(action_key)
                else:
                     print(f"⚠️ Skipping send_keys call - missing 'text' parameter")

            elif func_name == "send_keys_by_name":
                element_name = args.get("name")
                text = args.get("text")
                if element_name and text:
                    if action_key not in seen_actions:
                        filtered_calls.append(call)
                        seen_actions.add(action_key)
                else:
                     print(f"⚠️ Skipping send_keys_by_name call - missing parameters")

            elif func_name == "navigate_to_url":
                url = args.get("url")
                if url:
                    if action_key not in seen_actions:
                        filtered_calls.append(call)
                        seen_actions.add(action_key)
                else:
                     print(f"⚠️ Skipping navigate_to_url call - missing parameters")


        
        if not filtered_calls:
            print("⚠️ No valid calls found")
        else:
            print(f"✅ {len(filtered_calls)} valid call(s)")
        
        return jsonify({
            "output": output,
            "function_calls": filtered_calls
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/close_browser', methods=['POST'])
def close_browser():
    """Close the Selenium browser(s)"""
    global selenium_driver, selenium_driver_links
    if selenium_driver:
        selenium_driver.quit()
        selenium_driver = None
        print("✅ Selenium browser (form) closed")
    if selenium_driver_links:
        selenium_driver_links.quit()
        selenium_driver_links = None
        print("✅ Selenium browser (links) closed")
    return jsonify({"status": "browser(s) closed"})

if __name__ == '__main__':
    print("=" * 50)
    print("FunctionGemma API Server")
    print("=" * 50)
    print("Starting server on http://localhost:5000")
    print("Endpoints:")
    print("  GET  /health - Health check")

    print("  POST /processInteraction - Process interaction requests (click_element, send_keys)")
    print("  POST /execute - Execute function calls using Selenium")
    print("  POST /close_browser - Close Selenium browser")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=False)

