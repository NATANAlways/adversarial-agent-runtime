import requests

response = requests.get("https://api.github.com")

data = response.json()          # turn the JSON text into a Python dictionary

print(type(data))               # see what type it is now
print(data["current_user_url"]) # pull ONE specific value out of it