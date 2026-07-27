import requests

response = requests.post(
    "http://localhost:8000/v1/messages",
    json={"messages": [{"role": "user", "content": "Read notes.txt"}]}
)

print("Status:", response.status_code)
print("Server replied:", response.json())