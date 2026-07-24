from pathlib import Path


SHIM = Path("crates/adapters/src/responses/grok_tool_shim.rs")
MARKER = "CAS-SUB2API-GROK-TERMINAL-COMPLETION-HOOK"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")


text = read(SHIM)
if MARKER in text:
    print("[ok] Grok terminal completion recovery: already applied")
    raise SystemExit(0)

# Sub2API/Grok can close a function call with response.completed + response.output
# without ever sending response.output_item.done. The previous shim interpreted any
# still-pending item at a terminal frame as an interrupted stream. r14 then correctly
# poisoned that "incomplete" apply_patch to fail closed, which is exactly why real
# r14 traffic showed `*** BLOCKED INCOMPLETE APPLY_PATCH ***` even though the model
# had produced a complete V4A patch. A successful response.completed frame must not
# be treated as interruption solely because output_item.done is missing.
doc_start = text.index("    /// 终帧(completed / incomplete / failed):")
fn_start = text.index("    fn on_terminal(", doc_start)
next_doc = text.index("    /// envelope `output[]`", fn_start)
replacement = r'''    /// 终帧(completed / incomplete / failed):同步重写 `response.output[]` 里的 apply_patch /
    /// tool_search function_call → custom_tool_call / tool_search_call(与流式 done 一致)。
    ///
    /// CAS-SUB2API-GROK-TERMINAL-COMPLETION-HOOK
    /// Sub2API/Grok 真机流有时不会为 function_call 发 `response.output_item.done`,而是直接以
    /// `response.completed` + terminal envelope 收尾。completed 是成功终帧,不能仅因为 pending
    /// item 尚未收到 output_item.done 就判成 interrupted。此处优先从 terminal envelope 回收完整
    /// arguments,再交给现有 apply_patch truncation/V4A validator 决定 completed/incomplete。
    /// `response.incomplete` / `response.failed` 仍严格 fail-closed。
    fn on_terminal(&mut self, event_name: &str, mut data: Value, out: &mut Vec<u8>) {
        let terminal_completed = event_name == "response.completed";
        let terminal_output = data
            .get("response")
            .and_then(|r| r.get("output"))
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();

        let mut interrupted: std::collections::HashSet<String> =
            std::collections::HashSet::new();
        if !self.items.is_empty() {
            let mut leftovers: Vec<(u64, Pending)> = self.items.drain().collect();
            leftovers.sort_by_key(|(idx, _)| *idx);
            self.id_to_index.clear();
            for (output_index, mut p) in leftovers {
                // Prefer the same output_index, then fall back to stable item/call ids.
                // This recovers the authoritative complete arguments from the terminal
                // envelope when the provider omitted response.output_item.done.
                let indexed = usize::try_from(output_index)
                    .ok()
                    .and_then(|idx| terminal_output.get(idx))
                    .filter(|item| {
                        item.get("type").and_then(Value::as_str) == Some("function_call")
                    });
                let matched = indexed.or_else(|| {
                    terminal_output.iter().find(|item| {
                        if item.get("type").and_then(Value::as_str) != Some("function_call") {
                            return false;
                        }
                        let id_matches = !p.item_id.is_empty()
                            && item.get("id").and_then(Value::as_str)
                                == Some(p.item_id.as_str());
                        let call_matches = !p.call_id.is_empty()
                            && item.get("call_id").and_then(Value::as_str)
                                == Some(p.call_id.as_str());
                        id_matches || call_matches
                    })
                });
                let terminal_args = matched
                    .and_then(|item| item.get("arguments"))
                    .map(|args| function_arguments_to_string(Some(args)))
                    .filter(|args| !args.is_empty());
                let recovered_terminal_args = terminal_args.is_some();
                if let Some(args) = terminal_args {
                    p.args_acc = args;
                }

                // A successful terminal response is not an interrupted stream. Let
                // finalize_apply_patch independently reject truly truncated/invalid V4A.
                // Incomplete/failed terminal responses remain explicitly interrupted.
                let treat_as_interrupted = !terminal_completed;
                if treat_as_interrupted {
                    interrupted.insert(p.item_id.clone());
                }

                // Safe diagnostic only: never log patch contents or argument previews.
                tracing::info!(
                    target: "adapters::grok_tool_diag",
                    terminal = %event_name,
                    tool = %p.name,
                    output_index,
                    recovered_terminal_args,
                    args_len = p.args_acc.len(),
                    missing_output_item_done = true,
                    "closing Grok pending tool call at terminal response"
                );

                self.emit_tool_call_done(output_index, &p, treat_as_interrupted, out);
            }
        }

        if let Some(output) = data
            .get_mut("response")
            .and_then(|r| r.get_mut("output"))
            .and_then(|o| o.as_array_mut())
        {
            for item in output.iter_mut() {
                let id = item.get("id").and_then(|v| v.as_str()).map(str::to_owned);
                self.rewrite_envelope_item(item);
                if let Some(id) = id {
                    if interrupted.contains(&id) {
                        if let Some(o) = item.as_object_mut() {
                            o.insert("status".into(), Value::String("incomplete".into()));
                            // Keep incomplete/failed terminal envelopes fail-closed too.
                            if o.get("type").and_then(Value::as_str) == Some("custom_tool_call")
                                && o.get("name").and_then(Value::as_str) == Some("apply_patch")
                            {
                                if let Some(input) =
                                    o.get("input").and_then(Value::as_str).map(str::to_owned)
                                {
                                    o.insert(
                                        "input".into(),
                                        Value::String(block_incomplete_apply_patch(&input)),
                                    );
                                }
                            }
                        }
                    }
                }
            }
        }
        emit_event(out, &mut self.seq, event_name, data);
    }

'''
text = text[:doc_start] + replacement + text[next_doc:]

# Regression 1: exact Sub2API shape observed in r14 investigation — no
# output_item.done, but response.completed carries the complete function call.
# This must execute as completed, not be poisoned merely because a done event is
# absent.
test_anchor = '''    #[test]
    fn tool_search_function_call_rewritten_to_tool_search_call() {'''
if test_anchor not in text:
    raise SystemExit("anchor not found: Grok terminal completion regression tests")

tests = r'''    #[test]
    fn completed_terminal_without_output_item_done_recovers_apply_patch() {
        let patch = "*** Begin Patch\n*** Add File: terminal-only.txt\n+ok\n*** End Patch\n";
        let args = serde_json::to_string(&json!({ "input": patch })).unwrap();
        let input = [
            frame(
                "response.output_item.added",
                json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                    "item":{"type":"function_call","id":"fc_terminal_only","call_id":"call_terminal_only","name":"apply_patch","arguments":""}}),
            ),
            frame(
                "response.completed",
                json!({"type":"response.completed","sequence_number":1,
                    "response":{"output":[{"type":"function_call","id":"fc_terminal_only","call_id":"call_terminal_only","name":"apply_patch","arguments":args}]}}),
            ),
        ]
        .concat();
        let frames = run(&input);
        assert_eq!(
            events(&frames),
            vec![
                "response.output_item.added",
                "response.custom_tool_call_input.delta",
                "response.custom_tool_call_input.done",
                "response.output_item.done",
                "response.completed",
            ]
        );
        let done = &frames[3].1["item"];
        assert_eq!(done["status"], "completed");
        assert_eq!(done["input"], patch);
        assert!(!done["input"]
            .as_str()
            .unwrap()
            .starts_with(INCOMPLETE_APPLY_PATCH_PREFIX));
        assert_eq!(
            frames[4].1["response"]["output"][0]["status"],
            "completed"
        );
    }

    #[test]
    fn incomplete_terminal_without_output_item_done_stays_fail_closed() {
        let patch = "*** Begin Patch\n*** Add File: must-not-run-terminal.txt\n+blocked\n*** End Patch\n";
        let args = serde_json::to_string(&json!({ "input": patch })).unwrap();
        let input = [
            frame(
                "response.output_item.added",
                json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                    "item":{"type":"function_call","id":"fc_terminal_incomplete","call_id":"call_terminal_incomplete","name":"apply_patch","arguments":args}}),
            ),
            frame(
                "response.incomplete",
                json!({"type":"response.incomplete","sequence_number":1,
                    "response":{"output":[{"type":"function_call","id":"fc_terminal_incomplete","call_id":"call_terminal_incomplete","name":"apply_patch","arguments":args}]}}),
            ),
        ]
        .concat();
        let frames = run(&input);
        let done = &frames[1].1["item"];
        assert_eq!(done["status"], "incomplete");
        assert!(done["input"]
            .as_str()
            .unwrap()
            .starts_with(INCOMPLETE_APPLY_PATCH_PREFIX));
        assert_eq!(
            frames[2].1["response"]["output"][0]["status"],
            "incomplete"
        );
    }

'''
text = text.replace(test_anchor, tests + test_anchor, 1)
write(SHIM, text)
print("[ok] Grok terminal completion recovery: applied")
