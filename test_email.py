from agent.email_tool import send_email

# idempotency test (approved recipient)
print("Attempt 1:", send_email("boss@ourcompany.com", "Report", "Here is the report"))
print("Attempt 2:", send_email("boss@ourcompany.com", "Report", "Here is the report"))
print("Attempt 3:", send_email("boss@ourcompany.com", "Report", "Here is the report"))

# Different email (approved) — Must be SENT 
print("Different:", send_email("team@ourcompany.com", "Hi", "Hello team"))