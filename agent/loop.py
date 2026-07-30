from agent.client import ask_model
from agent.tools import run_tool
from agent.event_log import log_event, get_completed_tools, run_exsists
import uuid


# safety limit
MAX_STEPS = 10

def run_agent(task, scenario="S1", run_id=None, conversation=None):
    if run_id is None:
        run_id = str(uuid.uuid4())[:8]
    print(f"🆔 Run ID: {run_id}")

    if conversation is None:
        log_event(run_id, "run_start", {"task": task, "scenario": scenario})
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
            log_event(run_id, "run_end", {"status": "done"})
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
        
        # to log the tool call before
        log_event(run_id, "tool_call", {"tool": name, "args": tool_input})

        # fake tool to pretent
        result = run_tool(name, tool_input)
        print(f"   Result: {result}")

        # too result log
        log_event(run_id, "tool_result", {"tool": name, "result": str(result)[:200]})
        
        conversation.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_block.get("id"),
                "content": result,
                }]
        })

def resume_agent(run_id, scenario="S1"):
    """Continue crash of a run"""
    if not run_exsists(run_id):
        print(f"❌ Run '{run_id}' not found.")
        return
    print(f"🔄 Resuming run: {run_id}")

    # taking already completed tools
    completed = get_completed_tools(run_id)
    print(f"   Found {len(completed)} completed tool(s) from before the crash.")
    
    # making the already done work - regrouping the conversation
    conversation = [{"role":"user", "content": "Resuming previous task."}]
    for c in completed:
        # called tools
        conversation.append({
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "resumed", "name": c["tool"], "input":c["args"]}]
        })


        # results
        conversation.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "resumed", "content": c["result"]}]
        })
    log_event(run_id, "run_resumed", {"completed_tools": len(completed)})

    run_agent(task=None, scenario=scenario, run_id=run_id, conversation=conversation)


        

if __name__ == "__main__":
    import sys
    command = sys.argv[1] if len(sys.argv) > 1 else "run"

    if command == "resume":
        run_id = sys.argv[2]
        scenario = sys.argv[3] if len(sys.argv) > 3 else "S1"
        resume_agent(run_id, scenario=scenario)
    else:
        scenario = sys.argv[1] if len(sys.argv) > 1 else "S1"
        run_agent(f"Task for scenario {scenario}", scenario=scenario)
