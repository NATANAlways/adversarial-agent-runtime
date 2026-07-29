from agent.tools import read_file, write_file


print("Test 1 (read good file):")
print(read_file("notes.txt"))

print("\nTest 2 (write file):")
print(write_file("output.txt", "some data here"))

print("\nTest 3 (escape attempt):")
try:
    print(read_file("../../etc/passwd"))
except ValueError as e:
    print(e)