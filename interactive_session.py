#!/usr/bin/env python3
"""
Interactive Selenium Session for FunctionGemma
Allows users to control the browser via a Python REPL using natural language.
"""
import os
import sys
import time
import code
import requests
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select

# Configuration
API_URL = "http://127.0.0.1:5000"
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Global driver instance
driver = None

def init_driver():
    """Initialize the Selenium WebDriver"""
    global driver
    if driver is None:
        print("🚀 Initializing Selenium WebDriver...")
        chrome_options = Options()
        # Add options if needed, e.g. --headless
        driver = webdriver.Chrome(options=chrome_options)
        print("✅ WebDriver initialized")
    return driver

def navigateToURL(url_or_filename):
    """
    Navigate to a URL. 
    If a simple filename (e.g. 'links.html') is provided, it tries to find it in the project.
    """
    global driver
    if driver is None:
        init_driver()
    
    target_url = url_or_filename
    
    # Check if it's a known local file
    if not url_or_filename.startswith("http") and not url_or_filename.startswith("file://"):
        # Try finding it in user-registration folder first as per project structure
        possible_paths = [
            os.path.join(PROJECT_ROOT, "user-registration", url_or_filename),
            os.path.join(PROJECT_ROOT, url_or_filename)
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

def enterText(natural_language_command):
    """
    Input text into a field using natural language (e.g. "enter 'hello' in search-box").
    Directs to processInteraction to decide between ID and Name.
    """
    global driver
    if driver is None:
        init_driver()
        
    print(f"🤔 Processing text entry: '{natural_language_command}'...")
    process_command(natural_language_command)


def process_command(natural_language_command):
    """
    Send natural language command to API server and execute resulting Selenium actions.
    """
    global driver
    if driver is None:
        print("⚠️ Driver not running. Initializing...")
        init_driver()
        
    print(f"🤔 Processing: '{natural_language_command}'...")
    
    try:
        # Call the API server to interpret the command
        response = requests.post(
            f"{API_URL}/processInteraction",
            json={"input": natural_language_command}
        )
        
        if response.status_code != 200:
            print(f"❌ Error from API server: {response.text}")
            return
            
        data = response.json()
        function_calls = data.get("function_calls", [])
        
        if not function_calls:
            print("⚠️ No actions identified.")
            return

        print(f"⚡ Executing {len(function_calls)} action(s)...")
        
        # Execute each function call locally
        for call in function_calls:
            func_name = call["name"]
            args = call["args"]
            
            execute_local_action(func_name, args)
            
    except requests.exceptions.ConnectionError:
        print(f"❌ Could not connect to API server at {API_URL}. Is it running?")
    except Exception as e:
        print(f"❌ Error: {e}")

def find_element_simple(driver, args):
    """Helper to find element via ID or Name"""
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

def execute_local_action(func_name, args):
    """Execute a single Selenium action locally"""
    global driver
    
    try:
        if func_name == "click_element":
            print(f"  🖱️ Clicking element: {args}")
            
            try:
                element = find_element_simple(driver, args)
            except Exception as e:
                print(f"  ❌ Element not found: {e}")
                return

            element.click()
            
            # Special handling for close_button
            if args.get("id") == "close_button":
                print("  🛑 Close button clicked. Closing session...")
                driver.quit()
                driver = None
                return

        elif func_name == "send_keys":
            text = args.get("text", "")
            print(f"  ⌨️ Typing '{text}' into element: {args}")
            
            try:
                element = find_element_simple(driver, args)
            except Exception as e:
                print(f"  ❌ Element not found: {e}")
                return

            element.clear()
            element.send_keys(text)

        elif func_name == "send_keys_by_name":
            # Legacy support
            element_name = args.get("name")
            text = args.get("text", "")
            print(f"  ⌨️ Typing '{text}' into NAME: {element_name}")
            driver.find_element(By.NAME, element_name).send_keys(text)
            
        elif func_name == "navigate_to_url":
            url = args.get("url")
            print(f"  🌐 Navigating to URL: {url}")
            navigateToURL(url)
            
        else:
            print(f"  ⚠️ Unknown function: {func_name}")
            
    except Exception as e:
        print(f"  ❌ Action failed: {e}")

def close_session():
    """Close the browser and exit"""
    global driver
    if driver:
        driver.quit()
        driver = None
    print("👋 Session ended.")
    sys.exit(0)

def main():
    """Start the interactive session"""
    print("="*60)
    print("🤖 FunctionGemma Interactive Shell")
    print("="*60)
    print("Type your commands in natural language.")
    print("Examples:")
    print("  > Go to links.html")
    print("  > Click the Google link")
    print("  > Type 'hello' in search-box")
    print("Type 'exit' or 'quit' to end session.")
    print("="*60)
    
    # Init driver early
    init_driver()
    
    while True:
        try:
            user_input = input("\n> ").strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ["exit", "quit"]:
                close_session()
                break
                
            process_command(user_input)
            
        except KeyboardInterrupt:
            print("\nInterrupted. Type 'exit' to quit.")
        except EOFError:
            close_session()
            break

if __name__ == "__main__":
    main()
