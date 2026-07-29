from agent.client import ask_model

# ஒரு எளிமையான conversation
conversation = [{"role": "user", "content": "Read notes.txt"}]

# function-ஐ அழைக்கிறோம்
reply = ask_model(conversation)

print("Server சொன்னது:", reply)