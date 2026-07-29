from agent.client import ask_model
from agent.tools import run_tool


# safety limit
MAX_STEPS = 10

def run_agent(task, scenario="S1"):
    # converstation starts with user task
    conversation = [{"role": "user", "content":task}]

    step = 0
    # last tool + arguments
    last_signature = None
    # same signature come again and again
    repeat_count = 0

    while True:
        # stop: step limit

        if step >= MAX_STEPS:
            print(f"\n🛑 STOPPED: {MAX_STEPS} steps over (loop).")
            return
        
        step += 1
        print(f"\n -- step {step} --")

        # ask to the server
        reply = ask_model(conversation, scenario)
        conversation.append(reply)

        # take content from server's reply
        content = reply.get("content", [])

        # search whther tool_use block there inn the content
        tool_block = None
        for block in content:
            if block.get("type") == "tool_use":
                tool_block = block
                break
        
        #stop case 
        if tool_block is None:
            print("\n Done: model fininshed...")
            for block in content:
                if block.get("type") == "text":
                    print("Model told: ", block.get("text"))
            return
        
        # model ask a tool
        name = tool_block.get("name")
        tool_input = tool_block.get("input", {})
        print(f"Model asked tool: {name}")
        print(f"Arguments: {tool_input}")

        # -- No progress detection
        signature = f"{name} | {tool_input}"

        if signature == last_signature:
            repeat_count += 1
        else:
            repeat_count = 0
        last_signature = signature

        if repeat_count >= 2:
            print(f"\n🛑 STOPPED: no progress — same action repeated {repeat_count + 1} times.")
            print(f"   Stuck on: {name} with {tool_input}")
            return
        
        # fake tool to pretent
        result = run_tool(name, tool_input)
        print(f"   Result: {result}")
        
        conversation.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_block.get("id"),
                "content": result,
                }]
        })


        

if __name__ == "__main__":
    import sys
    scenario = sys.argv[1] if len(sys.argv) > 1 else "S1"
    run_agent(f"Task for scenario {scenario}", scenario=scenario)
