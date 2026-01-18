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
        
        found_local = False
        for p in possible_paths:
            if os.path.exists(p):
                target_url = f"file://{p}"
                found_local = True
                break
        
        # If not found locally, assume it's a web URL and default to https
        if not found_local:
            target_url = f"https://{url_or_filename}"
    
    print(f"🌐 Navigating to: {target_url}")
    driver.get(target_url)
    return f"Navigated to {target_url}"

def execute_selenium_function(func_name, args):
    """Execute Selenium WebDriver functions - supports dynamic driver selection"""
    global selenium_driver_links

    # Common arguments
    element_id = args.get("id", "")
    element_name = args.get("name", "")
    element_css = args.get("css", "")
    element_xpath = args.get("xpath", "")
    
    # Helper to find element via ID or Name
    def find_element_simple(driver, args):
        eid = args.get("id")
        ename = args.get("name")

        if eid:
             try: return driver.find_element(By.ID, eid)
             except: pass
             # Fallback ID as name
             try: return driver.find_element(By.NAME, eid)
             except: pass
        
        if ename:
            try: return driver.find_element(By.NAME, ename)
            except: pass
            
        raise Exception(f"Element not found with args: {args}")

    # Helper to check if element exists in a driver
    def element_exists(drv, args):
        try:
            if not is_driver_alive(drv):
                return False
            # Just try finding it
            find_element_simple(drv, args)
            return True
        except:
            return False

    # Determine which driver to use
    driver = None
    
    # 1. Check Links Driver (links.html)
    d_links = get_selenium_driver_for_links()
    
    # Check if element exists in current links driver state
    # We pass 'args' now instead of just 'element_id'
    if element_exists(d_links, args):
        driver = d_links
    
    # 2. If not found, logic to restore links.html if needed (simplified for now)
    if driver is None:
        driver = get_selenium_driver_for_links()

            
    # Initialize wait
    wait = WebDriverWait(driver, 10)
    
    try:
        if func_name == "send_keys":
            text = args.get("text", "")
            
            try:
                element = find_element_simple(driver, args)
                print(f"✅ Found element for send_keys: {args}", file=sys.stderr)
            except Exception as e:
                # Fallback print and re-raise
                print(f"❌ Element not found for send_keys: {args} (Error: {str(e)})", file=sys.stderr)
                raise Exception(f"Element not found for send_keys: {args}")
            
            element.clear()
            element.send_keys(text)
            return f"Sent keys '{text}' to element: {args}"
        
        elif func_name == "click_element":
            try:
                element = find_element_simple(driver, args)
            except Exception as e:
                raise Exception(f"Element not found for click_element: {args}")

            element.click()
            
            # If the close button was clicked (specific to links.html)
            if element_id == "close_button" and driver == selenium_driver_links:
                time.sleep(1)
                driver.quit()
                selenium_driver_links = None
                return f"Clicked element {args} and closed browser"
            
            return f"Clicked element: {args}"
        
        elif func_name == "select_option":
            value = args.get("text", "")
            element = find_element_simple(driver, args)
            dropdown = Select(element)
            try:
                dropdown.select_by_visible_text(value)
                return f"Selected option '{value}' in dropdown: {args}"
            except Exception:
                # Fallback to value if text fails
                dropdown.select_by_value(value)
                return f"Selected value '{value}' in dropdown: {args}"

        elif func_name == "select_dropdown_by_value":
            value = args.get("value", "")
            element = find_element_simple(driver, args)
            dropdown = Select(element)
            dropdown.select_by_value(value)
            return f"Selected value '{value}' in dropdown: {args}"
        
        elif func_name == "navigate_to_url":
            url = args.get("url", "")
            return navigate_to_url_logic(url)
        
        elif func_name == "send_keys_by_name":
            # Keeping for backward compatibility, mapped to generic logic if desired,
            # but users might call it directly.
            element_name = args.get("name", "")
            text = args.get("text", "")
            driver.find_element(By.NAME, element_name).send_keys(text)
            return f"Sent keys '{text}' to element NAME: {element_name}"

        
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
        
        # Heuristic: Auto-quote text for Type/Enter/Input commands if quotes are missing
        # This helps the model capture multi-word strings including "please", "in", etc.
        try:
            lower_input = user_input.lower()
            if (lower_input.startswith("type ") or lower_input.startswith("enter ") or lower_input.startswith("input ")) and \
               (" in " in lower_input or " from " in lower_input) and \
               '"' not in user_input and "'" not in user_input:
                
                # Find last " in " or " from " to separate content from target
                last_sep_idx = lower_input.rfind(" in ")
                if last_sep_idx == -1: last_sep_idx = lower_input.rfind(" from ")
                
                if last_sep_idx > -1:
                    # distinct verb
                    verb_end_idx = lower_input.find(" ") + 1
                    
                    if last_sep_idx > verb_end_idx:
                        content = user_input[verb_end_idx:last_sep_idx].strip()
                        target = user_input[last_sep_idx+len(" in "):].strip() # approximate
                        # if using " from ", adjust len
                        if " from " in lower_input[last_sep_idx:]:
                             target = user_input[last_sep_idx+len(" from "):].strip()
                        
                        verb = user_input[:verb_end_idx].strip()
                        
                        if content and target:
                            new_input = f'{verb} "{content}" in "{target}"'
                            print(f"🔄 Heuristic applied: '{user_input}' -> '{new_input}'")
                            user_input = new_input
        except Exception as e:
            print(f"⚠️ Heuristic check failed: {e}")
        
        # Load model if not already loaded
        load_model()
        
        # Build the message focused on interacting with elements
        system_message = (
            "You are a browser automation agent. Translate commands into function calls.\n"
            "Do NOT refuse commands. Use the locator strategy that best matches the user's description.\n"
            "\n"
            "**FUNCTIONS:**\n"
            "1. **send_keys**: Type text.\n"
            "   - 'text': Content to type.\n"
            "   - 'id': The ID of the element (e.g. 'search-box'). Can also be the 'name' attribute.\n"
            "2. **click_element**: Click element.\n"
            "   - 'id': The ID of the element.\n"
            "3. **select_option**: Select from dropdown.\n"
            "   - 'id': The ID of the dropdown.\n"
            "   - 'text': The visible text of the option to select.\n"
            "4. **navigate_to_url**: Go to URL.\n"
            "\n"
            "**IMPORTANT RULES:**\n"
            "- Do NOT copy values from examples. Use the EXACT values from the user's command.\n"
            "- Extract text content EXACTLY as it appears. Do not summarize or remove words like 'please'.\n"
            "- If the user says 'Type X in Y' or 'Select X in Y', X is the content. X can include multiple words. Y is the ID.\n"
            "- Use the identifier Y EXACTLY as provided. Do not infer IDs based on content.\n"
            "- Typically use 'id' for all element interactions.\n"
            "\n"
            "**EXAMPLES:**\n"
            "- User: 'Select Dark Mode in theme-select'\n"
            "  Function: <start_function_call>call:select_option{id:<escape>theme-select<escape>,text:<escape>Dark Mode<escape>}<end_function_call>\n"
            "- User: 'Type please update my profile in \"profile-box\"'\n"
            "  Function: <start_function_call>call:send_keys{id:<escape>profile-box<escape>,text:<escape>please update my profile<escape>}<end_function_call>\n"
            "- User: 'Type \"hello\" in field user-name'\n"
            "  Function: <start_function_call>call:send_keys{id:<escape>user-name<escape>,text:<escape>hello<escape>}<end_function_call>\n"
            "- User: 'Type verify this address is correct in feedback-box'\n"
            "  Function: <start_function_call>call:send_keys{id:<escape>feedback-box<escape>,text:<escape>verify this address is correct<escape>}<end_function_call>\n"
            "- User: 'Type \"hello\" in search-box'\n"
            "  Function: <start_function_call>call:send_keys{id:<escape>search-box<escape>,text:<escape>hello<escape>}<end_function_call>\n"
            "- User: 'Close the page'\n"
            "  Function: <start_function_call>call:click_element{id:<escape>close_button<escape>}<end_function_call>\n"
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
                "name": "send_keys",
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

        # Create select_option function schema
        select_option_schema = {
            "type": "function",
            "function": {
                "name": "select_option",
                "description": "Selects an option from a dropdown menu by its visible text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "The ID of the dropdown element."
                        },
                        "text": {
                            "type": "string",
                            "description": "The visible text of the option to select."
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
            function_schemas = [click_element_schema, send_keys_schema, select_option_schema, navigate_to_url_schema]
        
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
            "send_keys",
            "send_keys_by_name",
            "select_option",
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
            if func_name in ["click_element", "send_keys", "select_option"]:
                 if not (element_id or args.get("name")):
                    print(f"⚠️ Skipping {func_name} call - missing locator (id or name)", file=sys.stderr)
                    continue
            
            # Key for deduplication
            if func_name == "navigate_to_url":
                action_key = f"{func_name}:{args.get('url')}"
            elif element_id:
                action_key = f"{func_name}:id={element_id}" 
            elif args.get("name"):
                 action_key = f"{func_name}:name={args.get('name')}"
            else:
                 action_key = str(call)
            
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

            elif func_name == "select_option":
                text = args.get("text")
                if text:
                    if action_key not in seen_actions:
                        filtered_calls.append(call)
                        seen_actions.add(action_key)
                else:
                    print(f"⚠️ Skipping select_option call - missing 'text' parameter")

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

