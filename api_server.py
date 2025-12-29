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

app = Flask(__name__)
CORS(app)  # Enable CORS for Electron app

# Global model and processor
processor = None
model = None

# Global Selenium driver
selenium_driver = None

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

def get_selenium_driver():
    """Initialize and return Selenium WebDriver"""
    global selenium_driver
    if selenium_driver is None:
        chrome_options = Options()
        # Uncomment if you want headless mode
        # chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        
        selenium_driver = webdriver.Chrome(options=chrome_options)
        # Load the HTML file
        html_path = os.path.abspath("user-registration/index.html")
        selenium_driver.get(f"file://{html_path}")
        # Wait for form to load
        WebDriverWait(selenium_driver, 10).until(
            EC.presence_of_element_located((By.ID, "userForm"))
        )
        print(f"✅ Selenium driver initialized and loaded: {html_path}")
    return selenium_driver

def execute_selenium_function(func_name, args):
    """Execute form functions using Selenium"""
    driver = get_selenium_driver()
    wait = WebDriverWait(driver, 10)
    
    try:
        if func_name == "set_user_name":
            field = driver.find_element(By.ID, "name")
            field.clear()
            field.send_keys(args.get("name", ""))
            return f"Set name to: {args.get('name')}"
        
        elif func_name == "set_user_age":
            field = driver.find_element(By.ID, "age")
            field.clear()
            field.send_keys(str(args.get("age", "")))
            return f"Set age to: {args.get('age')}"
        
        elif func_name == "set_user_sex":
            dropdown = Select(driver.find_element(By.ID, "sex"))
            sex_value = args.get("sex", "").lower()
            dropdown.select_by_value(sex_value)
            return f"Set sex to: {sex_value}"
        
        elif func_name == "set_user_address":
            field = driver.find_element(By.ID, "address")
            field.clear()
            field.send_keys(args.get("address", ""))
            return f"Set address to: {args.get('address')}"
        
        elif func_name == "set_user_pincode":
            field = driver.find_element(By.ID, "pincode")
            field.clear()
            field.send_keys(str(args.get("pincode", "")))
            return f"Set pincode to: {args.get('pincode')}"
        
        elif func_name == "submit_form":
            # Wait before submitting so user can see the filled form
            print("⏳ Waiting 2 seconds before submitting form...")
            time.sleep(2)
            
            button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            button.click()
            
            # Wait for success overlay
            wait.until(EC.visibility_of_element_located((By.ID, "successOverlay")))
            print("✅ Form submitted successfully - success overlay visible")
            
            # Wait after submission so user can see the success message
            print("⏳ Waiting 3 seconds to show success message...")
            time.sleep(3)
            
            # Close the browser
            print("🔒 Closing browser...")
            driver.quit()
            global selenium_driver
            selenium_driver = None
            print("✅ Browser closed")
            
            return "Form submitted successfully and browser closed"
        
        else:
            return f"Error: Unknown function '{func_name}'"
    
    except Exception as e:
        return f"Error executing {func_name}: {str(e)}"

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "model_loaded": model is not None})

@app.route('/process', methods=['POST'])
def process_input():
    """
    Process natural language input and return function calls
    
    Request body:
    {
        "input": "My name is John Doe, I am 30 years old",
        "function_schemas": [...]  # Optional: custom function schemas
    }
    
    Response:
    {
        "output": "<start_function_call>call:set_user_name{name:<escape>John Doe<escape>}<end_function_call>",
        "function_calls": [
            {"name": "set_user_name", "args": {"name": "John Doe"}}
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
        
        # Build the message with improved context
        system_message = (
            "You are a model that can do function calling. "
            "**CRITICAL INSTRUCTION**: When the user provides multiple pieces of information, "
            "you MUST generate ALL corresponding function calls in a SINGLE response, one after another. "
            "Do NOT stop after a few calls - continue until ALL information is processed.\n"
            "\n"
            "Generate function calls in this exact order:\n"
            "1. set_user_name (if name mentioned)\n"
            "2. set_user_age (if age mentioned)\n"
            "3. set_user_sex (if sex mentioned)\n"
            "4. set_user_address (if address/location mentioned)\n"
            "5. set_user_pincode (if pincode mentioned)\n"
            "6. submit_form (if submit/send/finalize mentioned) - MUST be last\n"
            "\n"
            "CRITICAL RULES - FOLLOW THESE EXACTLY:\n"
            "1. **MANDATORY**: Generate ALL function calls for which the user provides information.\n"
            "2. Generate them ALL in sequence - do not stop early.\n"
            "3. If user says 'My name is John Doe, I am 30 years old, male, I live at 123 Main Street, Bangalore, pincode 560001, submit the form', "
            "you MUST generate ALL SIX calls: set_user_name, set_user_age, set_user_sex, set_user_address, set_user_pincode, submit_form.\n"
            "4. Do NOT stop after 2-3 calls - continue until ALL are generated.\n"
            "5. If the user mentions their name (e.g., 'My name is X' or 'I am X'), you MUST call set_user_name.\n"
            "6. If the user mentions their age (e.g., 'I am 30 years old' or 'age 30'), you MUST call set_user_age.\n"
            "7. If the user mentions sex/gender (e.g., 'male', 'female', 'I am a man'), you MUST call set_user_sex.\n"
            "8. If the user mentions an address, location, or where they live (e.g., 'I live at X', 'address is X', 'residing at X', 'location X'), you MUST call set_user_address.\n"
            "9. If the user mentions a pincode, postal code, zip code, or similar, you MUST call set_user_pincode.\n"
            "10. **MANDATORY**: If the user mentions ANY of these words: 'submit', 'send', 'finalize', 'done', 'complete', 'go ahead', 'submit it', 'send it', 'finalize it', you MUST call submit_form() as the VERY LAST function call.\n"
            "11. Do NOT make up or invent values - only extract what the user actually says.\n"
            "12. Do NOT extract values from examples in function descriptions.\n"
            "\n"
            "Example 1: If user says 'My name is John Doe, I am 30 years old, male', "
            "you MUST call: set_user_name(name='John Doe'), set_user_age(age='30'), set_user_sex(sex='male'). "
            "Do NOT call set_user_pincode or set_user_address.\n"
            "\n"
            "Example 2: If user says 'My name is John Doe, I am 30 years old, male, submit the form', "
            "you MUST call: set_user_name(name='John Doe'), set_user_age(age='30'), set_user_sex(sex='male'), submit_form(). "
            "The submit_form() call MUST be the LAST function call.\n"
            "\n"
            "Example 3: If user says 'My name is John Doe, I am 30, male, pincode 560001, submit', "
            "you MUST call: set_user_name(name='John Doe'), set_user_age(age='30'), set_user_sex(sex='male'), set_user_pincode(pincode='560001'), submit_form(). "
            "Notice submit_form() is ALWAYS last.\n"
            "\n"
            "Example 4: If user says 'My name is John Doe, I am 30 years old, male, I live at 123 Main Street, Bangalore, pincode 560001, submit the form', "
            "you MUST call ALL SIX of these in sequence: "
            "set_user_name(name='John Doe'), "
            "set_user_age(age='30'), "
            "set_user_sex(sex='male'), "
            "set_user_address(address='123 Main Street, Bangalore'), "
            "set_user_pincode(pincode='560001'), "
            "submit_form(). "
            "Do NOT skip any. Generate ALL SIX calls."
        )
        
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
            tools=function_schemas if function_schemas else None, 
            add_generation_prompt=True, 
            return_dict=True, 
            return_tensors="pt"
        )
        
        # Try multiple generation strategies to get all function calls
        # Strategy 1: Greedy with repetition penalty
        generation_kwargs = {
            **inputs.to(model.device),
            "pad_token_id": processor.eos_token_id,
            "max_new_tokens": 1536,
            "do_sample": False,
            "repetition_penalty": 1.15,  # Moderate penalty to prevent early stopping without excessive repetition
        }
        
        # Try to add min_new_tokens if supported (some transformers versions)
        try:
            generation_kwargs["min_new_tokens"] = 400
        except:
            pass  # Ignore if not supported
        
        out = model.generate(**generation_kwargs)
        output = processor.decode(out[0][len(inputs["input_ids"][0]):], skip_special_tokens=True)
        
        # Log the raw output for debugging
        print(f"\n📤 Raw model output: {output}")
        print(f"📥 User input was: {user_input}")
        print(f"📏 Output length: {len(output)} characters")
        print(f"📊 Generated tokens: {out[0].shape[0] - inputs['input_ids'].shape[1]}")
        
        # Check if output might be truncated
        if not output.rstrip().endswith('>'):
            print("⚠️ Warning: Output might be truncated (doesn't end with '>')")
        
        # Check if output is suspiciously short
        if len(output) < 300:
            print(f"⚠️ WARNING: Output is very short ({len(output)} chars). Model may have stopped early.")
            print(f"   This could indicate the model hit an EOS token prematurely.")
            print(f"   Consider: 1) The model might be too small (270M) for complex multi-call scenarios")
            print(f"             2) The prompt might need to be more explicit")
            print(f"             3) Try breaking the input into smaller chunks")
        
        # Count expected function calls based on user input
        expected_calls = []
        user_input_lower = user_input.lower()
        if any(word in user_input_lower for word in ["name is", "i am", "my name"]):
            expected_calls.append("set_user_name")
        if any(word in user_input_lower for word in ["years old", "age", "i am"]):
            expected_calls.append("set_user_age")
        if any(word in user_input_lower for word in ["male", "female", "other", "man", "woman"]):
            expected_calls.append("set_user_sex")
        if any(word in user_input_lower for word in ["address", "live", "lives", "living", "residing", "location", "street", "city", "at ", "live at"]):
            expected_calls.append("set_user_address")
        if any(word in user_input_lower for word in ["pincode", "postal code", "zip code", "zip", "postcode"]):
            expected_calls.append("set_user_pincode")
        if any(word in user_input_lower for word in ["submit", "send", "finalize", "done", "complete"]):
            expected_calls.append("submit_form")
        print(f"🔍 Expected function calls based on input: {expected_calls}")
        
        # Define valid function names
        VALID_FUNCTION_NAMES = {
            "set_user_name",
            "set_user_age", 
            "set_user_sex",
            "set_user_address",
            "set_user_pincode",
            "submit_form"
        }
        
        # Parse function calls
        function_calls = []
        seen_functions = set()  # Track which functions we've already seen to avoid duplicates
        
        # Extract all function calls (handle multiple)
        # Note: Use .*? instead of .+? to allow empty braces for functions with no args (like submit_form)
        pattern = r'<start_function_call>call:(\w+)\{(.*?)\}<end_function_call>'
        for match in re.finditer(pattern, output):
            func_name = match.group(1)
            
            # Validate function name - only allow known functions
            if func_name not in VALID_FUNCTION_NAMES:
                print(f"⚠️ Skipping invalid function name: {func_name} (not in valid list)")
                continue
            
            # Deduplicate - only keep first occurrence of each function
            if func_name in seen_functions:
                print(f"⚠️ Skipping duplicate function call: {func_name} (already processed)")
                continue
            
            seen_functions.add(func_name)
            
            args_str = match.group(2)
            args = {}
            # Only parse arguments if args_str is not empty
            if args_str.strip():
                arg_pattern = r'(\w+):<escape>(.+?)<escape>'
                for arg_match in re.finditer(arg_pattern, args_str):
                    key = arg_match.group(1)
                    value = arg_match.group(2)
                    args[key] = value
            function_calls.append({"name": func_name, "args": args})
            print(f"🔧 Parsed function call: {func_name} with args: {args}")
        
        print(f"📊 Total valid function calls parsed from model output: {len(function_calls)}")
        
        # Post-process: Filter out invalid function calls
        filtered_calls = []
        user_input_lower = user_input.lower()
        
        for call in function_calls:
            # Filter out pincode if user didn't mention pincode/postal code/zip
            if call["name"] == "set_user_pincode":
                pincode_keywords = ["pincode", "postal code", "zip code", "zip", "postcode", "pin code"]
                if not any(keyword in user_input_lower for keyword in pincode_keywords):
                    print(f"⚠️ Filtering out pincode call - user didn't mention pincode. Value was: {call.get('args', {}).get('pincode', 'N/A')}")
                    continue
                # Check if pincode args are empty - this indicates a parsing issue
                pincode_value = call.get('args', {}).get('pincode', '')
                if not pincode_value or pincode_value == '':
                    print(f"⚠️ WARNING: set_user_pincode has empty args. This might be a parsing issue.")
                    print(f"   Raw function call in output might be malformed. Check the raw output above.")
                    # Try to extract pincode from user input as fallback
                    pincode_match = re.search(r'\b(\d{6})\b', user_input)
                    if pincode_match:
                        pincode_value = pincode_match.group(1)
                        call['args']['pincode'] = pincode_value
                        print(f"   ✅ Extracted pincode from user input: {pincode_value}")
                    else:
                        print(f"   ❌ Could not extract pincode from user input")
                        continue
            
            # Filter out address if user didn't mention address
            if call["name"] == "set_user_address":
                address_keywords = ["address", "live", "lives", "living", "residing", "reside", "location", "street", "city", "residence", "at ", "live at", "lives at", "residing at", "reside at"]
                if not any(keyword in user_input_lower for keyword in address_keywords):
                    print(f"⚠️ Filtering out address call - user didn't mention address. User input: {user_input_lower[:100]}")
                    continue
                else:
                    print(f"✅ Address call validated - found address keyword in user input")
            
            filtered_calls.append(call)
        
        # Ensure submit_form is always last if present
        submit_form_call = None
        other_calls = []
        for call in filtered_calls:
            if call["name"] == "submit_form":
                submit_form_call = call
            else:
                other_calls.append(call)
        
        # Reorder: all other calls first, then submit_form
        if submit_form_call:
            filtered_calls = other_calls + [submit_form_call]
            print(f"✅ Reordered calls: submit_form moved to last position")
        
        if not filtered_calls:
            print("⚠️ No valid function calls found after filtering")
        else:
            print(f"✅ {len(filtered_calls)} valid function call(s) after filtering")
            print(f"📋 Filtered calls: {[call['name'] for call in filtered_calls]}")
            
        # Compare expected vs actual
        actual_call_names = [call['name'] for call in filtered_calls]
        missing_calls = [call for call in expected_calls if call not in actual_call_names]
        if missing_calls:
            print(f"⚠️ WARNING: Expected calls not found in output: {missing_calls}")
            print(f"   Model only generated {len(function_calls)} calls but {len(expected_calls)} were expected")
            print(f"   This might indicate the model didn't generate all required function calls or stopped early.")
            print(f"   Raw output length: {len(output)} characters")
            if len(output) < 500:
                print(f"   ⚠️ Output seems short - model may have stopped early.")
                print(f"   NOTE: The 270M model may be too small to reliably generate all 6 function calls in sequence.")
                print(f"   Suggestions:")
                print(f"   1. Try breaking the input into smaller chunks (e.g., fill fields first, then submit)")
                print(f"   2. Use a larger model if available")
                print(f"   3. The model might work better with fewer fields at once")
        
        return jsonify({
            "output": output,
            "function_calls": filtered_calls
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
            
            # Validate function calls before executing
            if func_name == "set_user_pincode":
                pincode = args.get("pincode", "")
                if not pincode or not pincode.isdigit() or len(pincode) != 6:
                    print(f"⚠️ Skipping invalid pincode call: {pincode}")
                    continue
            
            if func_name == "set_user_sex":
                sex = args.get("sex", "").lower()
                if sex not in ["male", "female", "other"]:
                    print(f"⚠️ Skipping invalid sex call: {sex}")
                    continue
            
            if func_name == "set_user_age":
                age = args.get("age", "")
                try:
                    age_num = int(age)
                    if age_num < 1 or age_num > 120:
                        print(f"⚠️ Skipping invalid age call: {age}")
                        continue
                except ValueError:
                    print(f"⚠️ Skipping invalid age call: {age}")
                    continue
            
            result = execute_selenium_function(func_name, args)
            results.append(result)
            print(f"🔧 Selenium executed: {func_name} with args: {args}")
        
        return jsonify({
            "results": results,
            "executed_count": len(results)
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/close_browser', methods=['POST'])
def close_browser():
    """Close the Selenium browser"""
    global selenium_driver
    if selenium_driver:
        selenium_driver.quit()
        selenium_driver = None
        print("✅ Selenium browser closed")
    return jsonify({"status": "browser closed"})

if __name__ == '__main__':
    print("=" * 50)
    print("FunctionGemma API Server")
    print("=" * 50)
    print("Starting server on http://localhost:5000")
    print("Endpoints:")
    print("  GET  /health - Health check")
    print("  POST /process - Process natural language input")
    print("  POST /execute - Execute function calls using Selenium")
    print("  POST /close_browser - Close Selenium browser")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)

