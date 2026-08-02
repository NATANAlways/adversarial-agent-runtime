from agent.client import ask_model
from agent.tools import run_tool
from agent.event_log import log_event, get_completed_tools, run_exsists, export_jsonl
import uuid
from mockllm.tokenizer import count_tokens
import json
import re



# safety limit
MAX_STEPS = 20

TOKEN_BUDGET = 8000

COMPACT_THRESHOLD = 6000 

COST_PER_CALL = 0.01
COST_BUDGET = 0.20 

def parse_tool_input(raw):
    """
    If the tool input is in dict format then allow, if it string or malformed json 
    repair it S2
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            repaired = re.sub(r",\s*([}\]])", r"\1", raw)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                return {}
    return {}

            


def conversation_tokens(conversation):
    """cmeasuring the tokens"""
    text = json.dumps(conversation)
    return count_tokens(text)

def compact_converstaion(conversation):
    """if the Converstaion go big make the old middle messages as a summary"""
    if len(conversation) <= 6:
        return conversation
    task_msg = conversation[0]
    recent = conversation[-4:]
    dropped = len(conversation) - 5

    summary = {
        "role": "user",
        "content": f"[Compacted {dropped} earlier messages to stay within token budget. "
                   f"Original task and recent context preserved.]"
    }
    return [task_msg, summary] + recent

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
    # failed tools
    failed_tools = []
    # budget
    total_cost = 0.0

    while True:
        # stop: step limit

        if step >= MAX_STEPS:
            print(f"\n🛑 STOPPED: {MAX_STEPS} steps over (loop).")
            return
        
        step += 1
        total_cost += COST_PER_CALL

        tokens = conversation_tokens(conversation)
        print(f"\n -- step {step} (tokens: {tokens}/{TOKEN_BUDGET}, cost: ${total_cost:.2f}/${COST_BUDGET:.2f}) --")

        # --- R5: cost budget ---
        if total_cost > COST_BUDGET:
            print(f"\n🛑 STOPPED: cost budget exceeded (${total_cost:.2f} > ${COST_BUDGET:.2f}).")
            log_event(run_id, "run_end", {"status": "cost_exceeded", "cost": total_cost})
            return

        if tokens > COMPACT_THRESHOLD:
            conversation = compact_converstaion(conversation)
            tokens = conversation_tokens(conversation)
            print(f"   🗜️  Compacted -> {tokens} tokens")


        if tokens > TOKEN_BUDGET:
            print(f"\n🛑 STOPPED: token budget exceeded ({tokens} > {TOKEN_BUDGET}).")
            log_event(run_id, "run_end", {"status": "budget_exceeded", "tokens": tokens})
            return

        # ask to the server
        try:
            reply = ask_model(conversation, scenario)
        except Exception as e:
            print(f"\n🛑 STOPPED: could not reach the model server ({e}).")
            log_event(run_id, "run_end", {"status": "server_unreachable", "error": str(e)[:100]})
            return
        
        conversation.append(reply)

        # take content from server's reply
        content = reply.get("content", [])

        # collecting all the tool_use blocks (parallel calls)
        tool_blocks = [b for b in content if b.get("type") == "tool_use"]
        
        #stop case : no tool the model fininshes
        if not tool_blocks:
            print("\n Done: model fininshed...")
            log_event(run_id, "run_end", {"status": "done", "failed_tools": len(failed_tools)})
            for block in content:
                if block.get("type") == "text":
                    print("Model told: ", block.get("text"))
            if failed_tools:
                print(f"\n⚠️  WARNING: model claims success, but {len(failed_tools)} tool(s) actually FAILED:")
                for f in failed_tools:
                    print(f"     - {f['tool']}: {f['result']}")
            return
            
        # no-progress:
        first = tool_blocks[0]
        signature = f"{first.get('name')} | {first.get('input', {})}"
        if signature == last_signature:
            repeat_count += 1
        else:
            repeat_count = 0
        last_signature = signature
        if repeat_count >= 2:
            print(f"\n🛑 STOPPED: no progress — same action repeated {repeat_count + 1} times.")
            return
            
            # making all tool use in process
        tool_results = []
        for tb in tool_blocks:
            name = tb.get("name")
            tool_input = parse_tool_input(tb.get("input", {}))
            print(f"Model asked tool: {name}")
            print(f"Arguments: {tool_input}")

            log_event(run_id, "tool_call", {"tool": name, "args": tool_input})
            result = run_tool(name, tool_input)
            print(f" Result: {result}")
            log_event(run_id, "tool_result", {"tool": name, "result": str(result)[:200]})

            # ground truth: does it fail ? - s11
            result_upper = str(result).upper()
            if str(result_upper).startswith("ERROR") or "REFUSED" in str(result_upper):
                failed_tools.append({"tool": name, "result": str(result_upper)[:100]})

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tb.get("id"),
                "content": result,
            })
                
                 # all results taken in one user message 
            conversation.append({"role": "user", "content": tool_results})  

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

def replay_run(run_id):
    """
    replay using old run event logs
    no server, no tools run again, only showing records
    """
    from agent.event_log import get_events

    events = get_events(run_id)
    if not events:
        print(f"❌ Run '{run_id}' not found (no events).")
        return
    
    print(f"🎬 Replaying run: {run_id} ({len(events)} events)")
    print("="*50)

    for event in events:
        etype = event["event_type"]
        data = event["data"]
        seq = event["seq"]

        if etype == "run_start":
            print(f"[{seq}] 🚀 START: task={data.get('task')} scenario={data.get('scenario')}")
        elif etype == "tool_call":
            print(f"[{seq}] 🔧 TOOL CALL: {data.get('tool')} args={data.get('args')}")
        elif etype == "tool_result":
            print(f"[{seq}] 📤 RESULT: {data.get('result')}")
        elif etype == "run_end":
            print(f"[{seq}] ✅ END: status={data.get('status')}")
        elif etype == "run_resumed":
            print(f"[{seq}] 🔄 RESUMED: completed_tools={data.get('completed_tools')}")
        else:
            print(f"[{seq}] {etype}: {data}")

    print("=" * 50)
    print("🎬 Replay complete (no server, no tools executed).")
        

if __name__ == "__main__":
    import sys
    command = sys.argv[1] if len(sys.argv) > 1 else "run"

    if command == "resume":
        run_id = sys.argv[2]
        scenario = sys.argv[3] if len(sys.argv) > 3 else "S1"
        resume_agent(run_id, scenario=scenario)
    elif command == "replay":
        run_id = sys.argv[2]
        replay_run(run_id)
    elif command == "export":
        run_id = sys.argv[2]
        path = export_jsonl(run_id)
        print(f"📄 Exported JSONL trace to {path}")
    else:
        scenario = sys.argv[1] if len(sys.argv) > 1 else "S1"
        run_agent(f"Task for scenario {scenario}", scenario=scenario)
