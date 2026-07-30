import requests
import time

# server's address
SERVER_URL = "http://localhost:8000/v1/messages"

# how many times to retry 
MAX_RETRIES = 5

def ask_model(conversation, scenario="S1"):
    """
    conversation is taken and sent to the server,
    return the server's answer in json format,
    if any 429/529 errors came, wait and try Again.
    Scenario = which senario server act (s1, s2, s3 , ...)
    """
    body = {
        "model": "mock-model",       
        "max_tokens": 1000,           
        "messages": conversation,
    }

    # tells which scenario the server act
    headers = {"X-Mock-Scenario": scenario}

    for attempt in range(MAX_RETRIES):
        response = requests.post(SERVER_URL, json=body, headers=headers)

        if response.status_code in (429, 529):
            wait = int(response.headers.get("Retry-After", 1))
            print(f"   ⏳ Got {response.status_code}, retrying in {wait}s "
                  f"(attempt {attempt + 1}/{MAX_RETRIES})...")
            time.sleep(wait)
            continue
        # if status code 200 or other
        return response.json()
    
    # in case all try got failed
    return {"error": f"max retries ({MAX_RETRIES}) exceeded"}