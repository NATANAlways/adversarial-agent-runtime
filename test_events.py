from agent.event_log import log_event, get_events

# ஒரு போலி run — சில events எழுது
run_id = "test-run-001"

log_event(run_id, "run_start", {"task": "Read notes.txt"})
log_event(run_id, "tool_call", {"tool": "read_file", "args": {"path": "notes.txt"}})
log_event(run_id, "tool_result", {"result": "Hello from notes"})
log_event(run_id, "run_end", {"status": "done"})

# இப்ப அவற்றை மறுபடி படி
print("Run", run_id, "-ன் events:")
for event in get_events(run_id):
    print(f"  [{event['seq']}] {event['event_type']}: {event['data']}")