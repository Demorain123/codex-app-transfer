use codex_app_transfer_codex_integration::catalog_models_for_provider_with_display_names;
use serde_json::json;

#[test]
fn r70_local_gateway_exposes_six_distinct_128k_choices() {
    let mappings = json!({
        "default": "q36-35b-a3b",
        "gpt_5_5": "q38-dt-iq3xxs",
        "gpt_5_4": "q38-dt-iq2s",
        "gpt_5_4_mini": "q38-gsq-iq3s",
        "gpt_5_3_codex": "q38-efficient-q2",
        "gpt_5_2": "q38-unsloth-iq3xxs"
    });
    let caps = json!({
        "q38-dt-iq3xxs": {"context_window": 131072, "display_name": "Qwen3.8 DT-IQ3 MTP3 128K"},
        "q38-dt-iq2s": {"context_window": 131072, "display_name": "Qwen3.8 DT-IQ2 MTP2 128K"},
        "q38-gsq-iq3s": {"context_window": 131072, "display_name": "Qwen3.8 GSQ IQ3S Ngram 128K"},
        "q38-efficient-q2": {"context_window": 131072, "display_name": "Qwen3.8 Efficient Q2 Ngram 128K"},
        "q38-unsloth-iq3xxs": {"context_window": 131072, "display_name": "Qwen3.8 Unsloth IQ3 Vanilla 128K"},
        "q36-35b-a3b": {"context_window": 131072, "display_name": "Qwen3.6 35B-A3B MoE 128K"}
    });

    let models = catalog_models_for_provider_with_display_names(
        "Sub2API Local Gateway",
        "q36-35b-a3b",
        false,
        Some(&mappings),
        Some(&caps),
        None,
        None,
        false,
    );

    assert_eq!(
        models.len(),
        6,
        "five Codex slots + distinct default must produce six choices"
    );
    assert!(models.iter().all(|m| m.context_window == 131072));

    let primary = models
        .iter()
        .find(|m| m.slug == "gpt-5.5")
        .expect("primary gpt-5.5 slot");
    assert_eq!(primary.display_name, "Qwen3.8 DT-IQ3 MTP3 128K");

    let sixth = models
        .iter()
        .find(|m| m.slug == "q36-35b-a3b")
        .expect("raw default sixth model");
    assert_eq!(sixth.display_name, "Qwen3.6 35B-A3B MoE 128K");
    assert_eq!(sixth.context_window, 131072);
}
