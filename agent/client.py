import requests

# server-ன் முகவரி (address)
SERVER_URL = "http://localhost:8000/v1/messages"


def ask_model(conversation, scenario="S1"):
    """
    conversation-ஐ எடுத்து server-க்கு அனுப்பி,
    server-ன் பதிலை (JSON) திரும்ப கொடுக்குது.
    Scenario = which senario server act (s1, s2, s3 , ...)
    """
    body = {
        "model": "mock-model",        # எந்த model — mock-க்கு பெயர் எதுவானாலும் சரி
        "max_tokens": 1000,           # அதிகபட்சம் எத்தனை tokens பதில் வரலாம்
        "messages": conversation,     # நம் conversation
    }

    # tells which scenario the server act
    headers = {"X-Mock-Scenario": scenario}
    response = requests.post(SERVER_URL, json=body, headers=headers)
    return response.json()