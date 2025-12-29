#!/usr/bin/env python3
from transformers import AutoProcessor, AutoModelForCausalLM
import re


def get_current_temperature(location: str) -> str:
    """Mock implementation - replace with real API call (e.g., OpenWeatherMap)"""
    # Fake temperatures for demo purposes
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
    # Pattern: <start_function_call>call:func_name{key:<escape>value<escape>}<end_function_call>
    pattern = r'<start_function_call>call:(\w+)\{(.+?)\}<end_function_call>'
    match = re.search(pattern, output)
    
    if match:
        func_name = match.group(1)
        args_str = match.group(2)
        
        # Parse arguments - handle <escape> tags as string delimiters
        args = {}
        # Split by comma for multiple args, but be careful with nested escapes
        arg_pattern = r'(\w+):<escape>(.+?)<escape>'
        for arg_match in re.finditer(arg_pattern, args_str):
            key = arg_match.group(1)
            value = arg_match.group(2)
            args[key] = value
        
        return func_name, args
    
    return None, None


def execute_function(func_name: str, args: dict) -> str:
    """Execute the requested function and return the result."""
    available_functions = {
        "get_current_temperature": get_current_temperature,
    }
    
    if func_name in available_functions:
        func = available_functions[func_name]
        return func(**args)
    else:
        return f"Error: Unknown function '{func_name}'"


def call_gemma():
    # Use local model instead of downloading from Hugging Face
    LOCAL_MODEL_PATH = "./models"

    print("Loading model... (this may take a moment)")
    processor = AutoProcessor.from_pretrained(LOCAL_MODEL_PATH, device_map="auto")
    model = AutoModelForCausalLM.from_pretrained(LOCAL_MODEL_PATH, dtype="auto", device_map="auto")
    print("Model loaded!\n")

    weather_function_schema = {
        "type": "function",
        "function": {
            "name": "get_current_temperature",
            "description": "Gets the current temperature for a given location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city name, e.g. San Francisco",
                    },
                },
                "required": ["location"],
            },
        }
    }

    print("=" * 50)
    print("Function Calling Demo with Gemma")
    print("Ask about the weather in any city!")
    print("Type 'quit' or 'exit' to stop")
    print("=" * 50)

    while True:
        user_input = input("\nYou: ").strip()
        
        if not user_input:
            continue
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("Goodbye!")
            break

        # Build the message
        message = [
            {
                "role": "developer",
                "content": "You are a model that can do function calling with the following functions"
            },
            {
                "role": "user",
                "content": user_input
            }
        ]

        # Get model's response (should be a function call)
        inputs = processor.apply_chat_template(
            message, 
            tools=[weather_function_schema], 
            add_generation_prompt=True, 
            return_dict=True, 
            return_tensors="pt"
        )

        out = model.generate(
            **inputs.to(model.device), 
            pad_token_id=processor.eos_token_id, 
            max_new_tokens=128
        )
        output = processor.decode(out[0][len(inputs["input_ids"][0]):], skip_special_tokens=True)

        print(f"\n📤 Model output: {output}")

        # Parse and execute the function call
        func_name, args = parse_function_call(output)
        
        if func_name:
            print(f"🔧 Calling function: {func_name}({args})")
            result = execute_function(func_name, args)
            print(f"📥 Function result: {result}")
            
            # Feed the result back to the model for a final response
            message.append({"role": "assistant", "content": output})
            message.append({"role": "tool", "name": func_name, "content": result})
            
            # Generate final response with the function result
            inputs = processor.apply_chat_template(
                message, 
                tools=[weather_function_schema], 
                add_generation_prompt=True, 
                return_dict=True, 
                return_tensors="pt"
            )
            
            out = model.generate(
                **inputs.to(model.device), 
                pad_token_id=processor.eos_token_id, 
                max_new_tokens=128
            )
            final_output = processor.decode(out[0][len(inputs["input_ids"][0]):], skip_special_tokens=True)
            
            print(f"\n🤖 Assistant: {final_output}")
        else:
            # Model didn't make a function call, just print the response
            print(f"\n🤖 Assistant: {output}")


if __name__ == "__main__":
    call_gemma()
