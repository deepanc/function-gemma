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
        
        for p in possible_paths:
            if os.path.exists(p):
                target_url = f"file://{p}"
                break
    
    print(f"🌐 Navigating to: {target_url}")
    driver.get(target_url)
    return f"Navigated to {target_url}"

def clickLink(natural_language_command):
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
            f"{API_URL}/processLink",
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

def execute_local_action(func_name, args):
    """Execute a single Selenium action locally"""
    global driver
    
    try:
        if func_name == "click_element":
            element_id = args.get("id")
            print(f"  🖱️ Clicking element with ID: {element_id}")
            
            element = driver.find_element(By.ID, element_id)
            element.click()
            
            # Special handling for close_button if we want to mimic the JS behavior behavior
            if element_id == "close_button":
                print("  🛑 Close button clicked.")

        elif func_name == "send_keys":
            element_id = args.get("id")
            text = args.get("text", "")
            print(f"  ⌨️ Typing '{text}' into ID: {element_id}")
            
            element = driver.find_element(By.ID, element_id)
            element.clear()
            element.send_keys(text)
            
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
    print("🤖 FunctionGemma Interactive Session")
    print("="*60)
    print("Available commands:")
    print("  navigateToURL('links.html')   - Open a page")
    print("  clickLink('click google')     - Interact via AI")
    print("  exit()                        - Quit")
    print("="*60)
    
    # Start the Python REPL
    code.interact(local=globals())

if __name__ == "__main__":
    main()
