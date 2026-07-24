from pathlib import Path


SHIM = Path("crates/adapters/src/responses/grok_tool_shim.rs")
MARKER = "CAS-SUB2API-GROK-APPLY-PATCH-RECOVERY-R16-HOOK"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")


text = read(SHIM)
if MARKER in text:
    print("[ok] Grok apply_patch r16 recovery: already applied")
    raise SystemExit(0)

# ---------------------------------------------------------------------------
# 1. EOF without response.completed/output_item.done is not automatically a
#    destructive interruption for apply_patch. If the accumulated JSON + V4A
#    body independently proves complete and valid, finalize_apply_patch can
#    safely complete it. Other custom/tool_search calls remain interrupted.
# ---------------------------------------------------------------------------
finish_doc = text.index("    /// 流结束:flush 尾部残帧;")
finish_fn = text.index("    pub(crate) fn finish(", finish_doc)
process_fn = text.index("    fn process_frame(", finish_fn)
finish_replacement = r'''    /// CAS-SUB2API-GROK-APPLY-PATCH-RECOVERY-R16-HOOK
    /// 流结束:flush 尾部残帧。Sub2API/Grok 真机流可能在 function arguments 已完整后直接 EOF,
    /// 既没有 `response.output_item.done` 也没有 terminal response。对 apply_patch 不再把 EOF 本身
    /// 当作唯一的 interruption 证据:让 `finalize_apply_patch` 用 JSON/V4A 完整性 + 语法校验决定。
    /// 只有结构完整且 V4A 合法的 patch 才能 completed;截断/非法输入仍会 poison 后 fail-closed。
    /// 其他 custom/tool_search 没有同等严格的自证完整性校验,仍按 interrupted 处理。
    pub(crate) fn finish(&mut self) -> Vec<u8> {
        let mut out = Vec::new();
        if !self.buffer.is_empty() {
            let frame = std::mem::take(&mut self.buffer);
            self.process_frame(&frame, &mut out);
        }
        let mut leftovers: Vec<(u64, Pending)> = self.items.drain().collect();
        leftovers.sort_by_key(|(idx, _)| *idx);
        self.id_to_index.clear();
        for (output_index, p) in leftovers {
            let allow_structural_completion =
                matches!(p.kind, ToolKind::Custom { apply_patch: true });
            tracing::info!(
                target: "adapters::grok_tool_diag",
                tool = %p.name,
                output_index,
                args_len = p.args_acc.len(),
                eof = true,
                allow_structural_completion,
                "closing Grok pending tool call at EOF"
            );
            self.emit_tool_call_done(
                output_index,
                &p,
                !allow_structural_completion,
                &mut out,
            );
        }
        out
    }

'''
text = text[:finish_doc] + finish_replacement + text[process_fn:]

# ---------------------------------------------------------------------------
# 2. Grok 4.5 is observed emitting Markdown-style closing stars on the two V4A
#    envelope sentinels (`*** Begin Patch ***` / `*** End Patch ***`) even though
#    the tool schema says the literals are `*** Begin Patch` / `*** End Patch`.
#    Repair only exact unprefixed sentinel lines. Never touch +/-/space-prefixed
#    patch body lines or operation headers.
# ---------------------------------------------------------------------------
const_anchor = 'const INCOMPLETE_APPLY_PATCH_PREFIX: &str = "*** BLOCKED INCOMPLETE APPLY_PATCH ***";'
if const_anchor not in text:
    raise SystemExit("anchor not found: incomplete apply_patch prefix")
helper = r'''/// Grok 4.5 sometimes Markdown-closes V4A envelope sentinels with an extra ` ***`.
/// Normalize only exact, column-0 sentinel lines. A valid patch body line always carries a
/// `+`/`-`/space prefix, so this cannot rewrite file content. Preserve trailing newline shape.
fn repair_grok_v4a_sentinels(input: &str) -> (String, bool, bool) {
    const BAD_BEGIN: &str = "*** Begin Patch ***";
    const BAD_END: &str = "*** End Patch ***";

    let mut begin_repaired = false;
    let mut end_repaired = false;
    let mut lines = Vec::new();
    for line in input.lines() {
        match line.trim_end() {
            BAD_BEGIN if line.starts_with(BAD_BEGIN) => {
                lines.push("*** Begin Patch".to_owned());
                begin_repaired = true;
            }
            BAD_END if line.starts_with(BAD_END) => {
                lines.push("*** End Patch".to_owned());
                end_repaired = true;
            }
            _ => lines.push(line.to_owned()),
        }
    }
    let mut repaired = lines.join("\n");
    if input.ends_with('\n') {
        repaired.push('\n');
    }
    (repaired, begin_repaired, end_repaired)
}

'''
text = text.replace(const_anchor, helper + const_anchor, 1)

# ---------------------------------------------------------------------------
# 3. Run the Grok-only sentinel repair before truncation/validation, and add a
#    content-free diagnostic whenever preflight decides to fail closed.
# ---------------------------------------------------------------------------
finalize_start = text.index("fn finalize_apply_patch(")
next_doc = text.index("/// [review nL]", finalize_start)
finalize_replacement = r'''fn finalize_apply_patch(args_acc: &str, cwd: Option<&str>, interrupted: bool) -> (String, bool) {
    let normalized_args = normalize_apply_patch_arguments(args_acc);
    let input = extract_apply_patch_input(&normalized_args);
    let (input, begin_repaired, end_repaired) = repair_grok_v4a_sentinels(&input);
    if begin_repaired || end_repaired {
        tracing::warn!(
            target: "adapters::grok_tool_diag",
            begin_repaired,
            end_repaired,
            input_len = input.len(),
            "repaired Grok Markdown-style V4A envelope sentinel"
        );
    }

    let json_trunc = detect_json_truncation(&normalized_args);
    let (input, _repairs) =
        apply_patch_preflight::optimize_patch(&input, cwd, json_trunc.is_none());
    let v4a_trunc = detect_v4a_truncation(&input);
    let json_truncated = json_trunc.is_some();
    let v4a_truncated = v4a_trunc.is_some();
    let is_trunc = json_truncated || v4a_truncated;
    let v4a_invalid = if is_trunc {
        false
    } else {
        validate_v4a_syntax(&input).is_err()
    };
    let incomplete = interrupted || is_trunc || v4a_invalid;

    if incomplete {
        let starts_begin = input
            .lines()
            .next()
            .is_some_and(|line| line.trim_end() == "*** Begin Patch");
        let ends_end = input
            .lines()
            .last()
            .is_some_and(|line| line.trim_end() == "*** End Patch");
        tracing::warn!(
            target: "adapters::grok_tool_diag",
            interrupted,
            json_truncated,
            v4a_truncated,
            v4a_invalid,
            starts_begin,
            ends_end,
            input_len = input.len(),
            args_len = normalized_args.len(),
            "Grok apply_patch preflight marked call incomplete"
        );
    }

    (input, incomplete)
}

'''
text = text[:finalize_start] + finalize_replacement + text[next_doc:]

# ---------------------------------------------------------------------------
# 4. Regression coverage:
#    - complete apply_patch at raw EOF is allowed only after structural proof;
#    - truncated EOF stays poisoned;
#    - exact Grok `*** Begin/End Patch ***` drift is canonicalized.
# ---------------------------------------------------------------------------
old_test_start = text.index(
    "    #[test]\n    fn interrupted_apply_patch_is_poisoned_because_codex_ignores_incomplete_status()"
)
next_test = text.index(
    "    #[test]\n    fn completed_terminal_without_output_item_done_recovers_apply_patch()",
    old_test_start,
)
replacement_tests = r'''    #[test]
    fn complete_apply_patch_at_eof_without_terminal_is_structurally_recovered() {
        let patch = "*** Begin Patch\n*** Add File: eof-complete.txt\n+ok\n*** End Patch\n";
        let args = serde_json::to_string(&json!({ "input": patch })).unwrap();
        let input = frame(
            "response.output_item.added",
            json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                "item":{"type":"function_call","id":"fc_eof_complete","call_id":"call_eof_complete","name":"apply_patch","arguments":args}}),
        );
        let frames = run(&input);
        let done = &frames[3].1["item"];
        assert_eq!(done["status"], "completed");
        assert_eq!(done["input"], patch);
        assert!(!done["input"]
            .as_str()
            .unwrap()
            .starts_with(INCOMPLETE_APPLY_PATCH_PREFIX));
    }

    #[test]
    fn truncated_apply_patch_at_eof_stays_poisoned() {
        let patch = "*** Begin Patch\n*** Add File: must-not-run.txt\n+blocked\n";
        let args = serde_json::to_string(&json!({ "input": patch })).unwrap();
        let input = frame(
            "response.output_item.added",
            json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                "item":{"type":"function_call","id":"fc_interrupt","call_id":"call_interrupt","name":"apply_patch","arguments":args}}),
        );
        let frames = run(&input);
        let done = &frames[1].1["item"];
        assert_eq!(done["status"], "incomplete");
        let blocked = done["input"].as_str().unwrap();
        assert!(blocked.starts_with(INCOMPLETE_APPLY_PATCH_PREFIX));
        assert!(blocked.contains("*** Begin Patch"));
        assert!(validate_v4a_syntax(blocked).is_err());
    }

    #[test]
    fn grok_markdown_style_v4a_sentinels_are_repaired() {
        let malformed =
            "*** Begin Patch ***\n*** Add File: grok-sentinel.txt\n+ok\n*** End Patch ***\n";
        let canonical =
            "*** Begin Patch\n*** Add File: grok-sentinel.txt\n+ok\n*** End Patch\n";
        let args = serde_json::to_string(&json!({ "input": malformed })).unwrap();
        let input = [
            frame(
                "response.output_item.added",
                json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                    "item":{"type":"function_call","id":"fc_grok_sentinel","call_id":"call_grok_sentinel","name":"apply_patch","arguments":""}}),
            ),
            frame(
                "response.output_item.done",
                json!({"type":"response.output_item.done","sequence_number":1,"output_index":0,
                    "item":{"type":"function_call","id":"fc_grok_sentinel","call_id":"call_grok_sentinel","name":"apply_patch","arguments":args}}),
            ),
        ]
        .concat();
        let frames = run(&input);
        let done = &frames[3].1["item"];
        assert_eq!(done["status"], "completed");
        assert_eq!(done["input"], canonical);
    }

'''
text = text[:old_test_start] + replacement_tests + text[next_test:]

write(SHIM, text)
print("[ok] Grok apply_patch r16 recovery: applied")
