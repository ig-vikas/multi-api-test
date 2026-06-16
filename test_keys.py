#!/usr/bin/env python3
import os
import json
import urllib.request
import urllib.error
import sys

# Enable ANSI colors on Windows terminal if needed
if os.name == 'nt':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # 7 is ENABLE_PROCESSED_OUTPUT | ENABLE_WRAP_AT_EOL_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

# Handle encoding errors on Windows terminal gracefully
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(errors='replace')
        sys.stderr.reconfigure(errors='replace')
    except Exception:
        pass

# ANSI Color Codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def print_success(msg):
    print(f"{GREEN}[OK] {msg}{RESET}")

def print_failure(msg):
    print(f"{RED}[FAIL] {msg}{RESET}")

def print_info(msg):
    print(f"{CYAN}[INFO] {msg}{RESET}")

def print_warning(msg):
    print(f"{YELLOW}[WARN] {msg}{RESET}")

def load_env(filepath=".env"):
    """Loads variables from .env file into os.environ if it exists."""
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    # Strip single/double quotes if present
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    if key:
                        os.environ[key] = val

def http_post(url, headers, payload, timeout=15):
    """Zero-dependency HTTP POST using standard library."""
    # Ensure there is a User-Agent to prevent Cloudflare blocks (e.g. error 1010 on Groq)
    headers = headers.copy() if headers else {}
    if not any(k.lower() == 'user-agent' for k in headers.keys()):
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.status
            body = response.read().decode('utf-8')
            return status, json.loads(body), None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8') if e.fp else ""
        try:
            err_json = json.loads(body)
        except Exception:
            err_json = body
        return e.code, err_json, str(e)
    except Exception as e:
        return 0, None, str(e)

def test_anthropic(api_key, model):
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": model,
        "max_tokens": 10,
        "messages": [{"role": "user", "content": "hii"}]
    }
    
    status, res, err = http_post(url, headers, payload)
    if err:
        return False, f"HTTP Error {status}: {res if res else err}"
    
    try:
        text = res['content'][0]['text']
        return True, f"Response: {repr(text)}"
    except KeyError:
        return False, f"Unexpected response structure: {res}"

def test_gemini(api_key, model):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {
        "content-type": "application/json"
    }
    payload = {
        "contents": [{"parts": [{"text": "hii"}]}]
    }
    
    status, res, err = http_post(url, headers, payload)
    if err:
        return False, f"HTTP Error {status}: {res if res else err}"
        
    try:
        text = res['candidates'][0]['content']['parts'][0]['text']
        return True, f"Response: {repr(text)}"
    except KeyError:
        return False, f"Unexpected response structure: {res}"

def test_openai_compatible(provider_name, url, api_key, model):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hii"}],
        "max_tokens": 10
    }
    
    status, res, err = http_post(url, headers, payload)
    if err:
        return False, f"HTTP Error {status}: {res if res else err}"
        
    try:
        message = res['choices'][0]['message']
        text = message.get('content')
        if text is None:
            text = message.get('reasoning_content') or message.get('reasoning') or str(message)
        return True, f"Response: {repr(text)}"
    except KeyError:
        return False, f"Unexpected response structure: {res}"

def test_ollama_cloud(api_key, model, api_url):
    url = api_url
    if not url.endswith('/chat'):
        url = url.rstrip('/') + '/chat'
        
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hii"}],
        "stream": False,
        "options": {"num_predict": 10}
    }
    
    status, res, err = http_post(url, headers, payload)
    if err:
        return False, f"HTTP Error {status}: {res if res else err}"
        
    try:
        text = res['message']['content']
        return True, f"Response: {repr(text)}"
    except KeyError:
        return False, f"Unexpected response structure: {res}"

def main():
    print(f"\n{BOLD}========================================")
    print("      API Key Tester Script")
    print(f"========================================{RESET}\n")
    
    load_env()
    
    providers = [
        {
            "name": "Anthropic",
            "key_var": "ANTHROPIC_API_KEY",
            "model_var": "ANTHROPIC_MODEL",
            "tester": lambda k, m: test_anthropic(k, m)
        },
        {
            "name": "Gemini",
            "key_var": "GEMINI_API_KEY",
            "model_var": "GEMINI_MODEL",
            "tester": lambda k, m: test_gemini(k, m)
        },
        {
            "name": "OpenRouter",
            "key_var": "OPENROUTER_API_KEY",
            "model_var": "OPENROUTER_MODEL",
            "tester": lambda k, m: test_openai_compatible("OpenRouter", "https://openrouter.ai/api/v1/chat/completions", k, m)
        },
        {
            "name": "Ollama Cloud",
            "key_var": "OLLAMA_CLOUD_API_KEY",
            "model_var": "OLLAMA_CLOUD_MODEL",
            "tester": lambda k, m: test_ollama_cloud(k, m, os.getenv("OLLAMA_CLOUD_API_URL", "https://ollama.com/api"))
        },
        {
            "name": "Groq",
            "key_var": "GROQ_API_KEY",
            "model_var": "GROQ_MODEL",
            "tester": lambda k, m: test_openai_compatible("Groq", "https://api.groq.com/openai/v1/chat/completions", k, m)
        },
        {
            "name": "Mistral",
            "key_var": "MISTRAL_API_KEY",
            "model_var": "MISTRAL_MODEL",
            "tester": lambda k, m: test_openai_compatible("Mistral", "https://api.mistral.ai/v1/chat/completions", k, m)
        },
        {
            "name": "DeepSeek",
            "key_var": "DEEPSEEK_API_KEY",
            "model_var": "DEEPSEEK_MODEL",
            "tester": lambda k, m: test_openai_compatible("DeepSeek", "https://api.deepseek.com/chat/completions", k, m)
        },
        {
            "name": "Together",
            "key_var": "TOGETHER_API_KEY",
            "model_var": "TOGETHER_MODEL",
            "tester": lambda k, m: test_openai_compatible("Together", "https://api.together.xyz/v1/chat/completions", k, m)
        },
        {
            "name": "Fireworks",
            "key_var": "FIREWORKS_API_KEY",
            "model_var": "FIREWORKS_MODEL",
            "tester": lambda k, m: test_openai_compatible("Fireworks", "https://api.fireworks.ai/retrieve/v1/chat/completions", k, m)
        },
        {
            "name": "xAI",
            "key_var": "XAI_API_KEY",
            "model_var": "XAI_MODEL",
            "tester": lambda k, m: test_openai_compatible("xAI", "https://api.x.ai/v1/chat/completions", k, m)
        }
    ]
    
    tested_any = False
    
    for prov in providers:
        name = prov["name"]
        api_key = os.getenv(prov["key_var"])
        model = os.getenv(prov["model_var"])
        
        if not api_key:
            print_warning(f"{name}: Skipped (No key found in env)")
            continue
            
        if api_key.strip() == "XXXX":
            print_info(f"{name}: Skipped (Placeholder 'XXXX' detected)")
            continue
            
        tested_any = True
        print(f"Testing {BOLD}{name}{RESET} using model {BOLD}{model}{RESET}...")
        
        success, details = prov["tester"](api_key, model)
        if success:
            print_success(f"{name}: SUCCESS - {details}")
        else:
            print_failure(f"{name}: FAILED - {details}")
            
    if not tested_any:
        print_info("No keys to test. Update your API keys in the `.env` file from 'XXXX' to test them.")
    
    print(f"\n{BOLD}========================================{RESET}\n")

if __name__ == "__main__":
    main()
