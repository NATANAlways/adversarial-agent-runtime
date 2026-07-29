from agent.email_tool import send_email

# அதே email-ஐ மூணு முறை அனுப்ப முயற்சி செய்
print("Attempt 1:", send_email("bob@example.com", "Report", "Here is the report"))
print("Attempt 2:", send_email("bob@example.com", "Report", "Here is the report"))
print("Attempt 3:", send_email("bob@example.com", "Report", "Here is the report"))

# வேறு ஒரு email — இது அனுப்பப்படணும்
print("Different:", send_email("alice@example.com", "Hi", "Hello Alice"))