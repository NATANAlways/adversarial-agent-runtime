from agent.tools import read_file, write_file
from agent.tools import http_get


print("Test 1 (read good file):")
print(read_file("notes.txt"))

print("\nTest 2 (write file):")
print(write_file("output.txt", "some data here"))

print("\nTest 3 (escape attempt):")
try:
    print(read_file("../../etc/passwd"))
except ValueError as e:
    print(e)




# 4. host — REFUSED
print("\nTest 4 (blocked host):")
print(http_get("https://evil-hacker-site.com/steal"))

# 5. host does it there it must worked
print("\nTest 5 (allowed host):")
print(http_get("https://example.com"))