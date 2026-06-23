#!/usr/bin/env python3
"""
Test selected OpenCode Zen models with a simple "hii" message.

Env:
  OPENCODE_API_KEY=your_opencode_zen_key
  OPENCODE_BASE_URL=https://opencode.ai/zen/v1
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "https://opencode.ai/zen/v1"
DEFAULT_MESSAGE = "hii"
DEFAULT_MODELS = [
    "minimax-m3-free",
    "mimo-v2.5-free",
    "nemotron-3-super-free",
    "nemotron-3-ultra-free",
    "qwen3.6-plus-free",
    "deepseek-v4-flash-free",
]

# OpenCode docs list Qwen 3.x Plus models on the Anthropic-compatible
# /messages endpoint. The rest of this free set is chat-completions style.
MESSAGES_FIRST_PREFIXES = ("qwen3.",)


def enable_windows_ansi():
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


enable_windows_ansi()

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def load_env(path=".env"):
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]

            os.environ.setdefault(key, value)


def env_models():
    raw = os.getenv("OPENCODE_MODELS", "")
    if not raw.strip():
        return DEFAULT_MODELS
    return [item.strip() for item in raw.split(",") if item.strip()]


def request_json(method, url, headers=None, payload=None, timeout=45):
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "opencode-zen-api-tester/1.0")

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body) if body else {}, None
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace") if error.fp else ""
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = body
        return error.code, parsed, str(error)
    except Exception as error:
        return 0, None, str(error)


def fetch_models(base_url, api_key):
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    status, body, error = request_json("GET", f"{base_url}/models", headers=headers)
    if status != 200:
        detail = body if body is not None else error
        raise RuntimeError(f"Could not fetch models: HTTP {status} {detail}")

    return {item.get("id") for item in body.get("data", []) if item.get("id")}


def chat_completions(base_url, api_key, model, message, max_tokens):
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "max_tokens": max_tokens,
    }
    status, body, error = request_json(
        "POST", f"{base_url}/chat/completions", headers=headers, payload=payload
    )
    if status < 200 or status >= 300:
        return False, status, compact_error(body, error)

    try:
        content = body["choices"][0]["message"].get("content")
        return True, status, content or json.dumps(body["choices"][0]["message"])
    except Exception:
        return False, status, f"Unexpected response: {short_json(body)}"


def messages(base_url, api_key, model, message, max_tokens):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": message}],
    }
    status, body, error = request_json(
        "POST", f"{base_url}/messages", headers=headers, payload=payload
    )
    if status < 200 or status >= 300:
        return False, status, compact_error(body, error)

    try:
        parts = body.get("content", [])
        text_parts = [part.get("text", "") for part in parts if part.get("type") == "text"]
        return True, status, "\n".join(part for part in text_parts if part).strip()
    except Exception:
        return False, status, f"Unexpected response: {short_json(body)}"


def endpoint_order(model):
    if model.startswith(MESSAGES_FIRST_PREFIXES):
        return [("messages", messages), ("chat/completions", chat_completions)]
    return [("chat/completions", chat_completions), ("messages", messages)]


def compact_error(body, fallback):
    if isinstance(body, dict):
        error = body.get("error") or body
        if isinstance(error, dict):
            return error.get("message") or short_json(error)
        return str(error)
    if body:
        return str(body).strip()
    return fallback or "unknown error"


def short_json(value, limit=500):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def mask_key(key):
    if not key:
        return "(missing)"
    if len(key) <= 10:
        return "***"
    return f"{key[:6]}...{key[-4:]}"


def print_model_check(requested, live_models):
    print(f"\n{BOLD}Live model check{RESET}")
    for model in requested:
        if model in live_models:
            print(f"{GREEN}[FOUND]{RESET} {model}")
        else:
            print(f"{RED}[MISSING]{RESET} {model}")


def test_model(base_url, api_key, model, message, max_tokens):
    errors = []
    for endpoint_name, tester in endpoint_order(model):
        ok, status, detail = tester(base_url, api_key, model, message, max_tokens)
        if ok:
            return True, endpoint_name, status, detail
        errors.append(f"{endpoint_name}: HTTP {status} {detail}")
    return False, "all", 0, " | ".join(errors)


def main():
    load_env()

    parser = argparse.ArgumentParser(description="Test OpenCode Zen models.")
    parser.add_argument("--list-only", action="store_true", help="Only fetch/check model IDs.")
    parser.add_argument("--message", default=os.getenv("OPENCODE_TEST_MESSAGE", DEFAULT_MESSAGE))
    parser.add_argument("--max-tokens", type=int, default=int(os.getenv("OPENCODE_MAX_TOKENS", "64")))
    args = parser.parse_args()

    base_url = os.getenv("OPENCODE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    api_key = os.getenv("OPENCODE_API_KEY", "").strip()
    models = env_models()

    print(f"\n{BOLD}OpenCode Zen API tester{RESET}")
    print(f"{CYAN}Base URL:{RESET} {base_url}")
    print(f"{CYAN}API key:{RESET} {mask_key(api_key)}")
    print(f"{CYAN}Test message:{RESET} {args.message!r}")

    try:
        live_models = fetch_models(base_url, api_key)
    except Exception as error:
        print(f"{RED}[FAIL]{RESET} {error}")
        return 1

    print_model_check(models, live_models)

    if args.list_only:
        print(f"\n{YELLOW}[INFO]{RESET} List-only mode; no chat requests were sent.")
        return 0

    if not api_key or api_key.upper() == "XXXX":
        print(
            f"\n{YELLOW}[WARN]{RESET} Put your OpenCode Zen key in OPENCODE_API_KEY "
            "inside .env, then run this script again to send the hii test."
        )
        return 2

    print(f"\n{BOLD}Sending message tests{RESET}")
    exit_code = 0
    for model in models:
        if model not in live_models:
            print(f"{RED}[SKIP]{RESET} {model}: not returned by /models")
            exit_code = 1
            continue

        ok, endpoint, status, detail = test_model(
            base_url, api_key, model, args.message, args.max_tokens
        )
        if ok:
            print(f"{GREEN}[OK]{RESET} {model} via /{endpoint}: {detail!r}")
        else:
            print(f"{RED}[FAIL]{RESET} {model}: {detail}")
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
