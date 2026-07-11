"""Custom pipeline transform scripts — CRUD + jailed execution."""
from __future__ import annotations

import json

import pytest

from copilot.backend import transforms as tf


pytestmark = pytest.mark.asyncio


UPPER_SCRIPT = '''"""Uppercase every assistant message."""
import argparse, json

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    kept = 0
    with open(args.input, "r", encoding="utf-8") as fin, \\
         open(args.output, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            for m in rec.get("messages", []):
                if m.get("role") == "assistant":
                    m["content"] = str(m.get("content", "")).upper()
            fout.write(json.dumps(rec, ensure_ascii=False) + "\\n")
            kept += 1
    print(f"kept={kept}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


async def test_save_list_read_delete_roundtrip(repo):
    saved = tf.save_transform(repo, "upper_case.py", UPPER_SCRIPT)
    assert saved["name"] == "upper_case.py"
    assert saved["description"] == "Uppercase every assistant message."
    assert saved["warnings"] == []
    assert saved["backup"] is None

    listed = tf.list_transforms(repo)
    assert [t["name"] for t in listed] == ["upper_case.py"]
    assert listed[0]["description"] == "Uppercase every assistant message."

    read = tf.read_transform(repo, "upper_case.py")
    assert read["content"] == UPPER_SCRIPT

    # Overwrite creates a .bak backup.
    saved2 = tf.save_transform(repo, "upper_case.py", UPPER_SCRIPT + "\n# v2\n")
    assert saved2["backup"] == "upper_case.py.bak"

    assert tf.delete_transform(repo, "upper_case.py") is True
    assert tf.list_transforms(repo) == []
    with pytest.raises(FileNotFoundError):
        tf.read_transform(repo, "upper_case.py")


async def test_name_and_path_jail(repo):
    with pytest.raises(tf.TransformError):
        tf.save_transform(repo, "../evil.py", "x = 1")
    with pytest.raises(tf.TransformError):
        tf.save_transform(repo, "no_extension", "x = 1")
    with pytest.raises(tf.TransformError):
        tf.save_transform(repo, "ok.py", "")
    # Script missing the CLI contract still saves, but warns.
    saved = tf.save_transform(repo, "odd.py", "print('hi')\n")
    assert saved["warnings"]


async def test_run_transform_end_to_end(repo):
    tf.save_transform(repo, "upper_case.py", UPPER_SCRIPT)
    src = repo / "data" / "raw" / "sample.jsonl"
    rows = [
        {"messages": [{"role": "user", "content": "hi"},
                      {"role": "assistant", "content": "hello there"}]},
        {"messages": [{"role": "user", "content": "yo"},
                      {"role": "assistant", "content": "hey"}]},
    ]
    src.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    result = await tf.run_transform(repo, "upper_case.py", "data/raw/sample.jsonl")

    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert result["timed_out"] is False
    assert result["output"] == "data/raw/sample__upper_case.jsonl"
    assert result["output_lines"] == 2
    assert "kept=2" in result["stdout_tail"]

    out_rows = [
        json.loads(l) for l in
        (repo / "data" / "raw" / "sample__upper_case.jsonl")
        .read_text(encoding="utf-8").splitlines()
    ]
    assert out_rows[0]["messages"][1]["content"] == "HELLO THERE"


async def test_run_transform_input_jail(repo):
    tf.save_transform(repo, "upper_case.py", UPPER_SCRIPT)
    (repo / "secrets.jsonl").write_text("{}\n", encoding="utf-8")
    (repo / "data" / "raw" / "x.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(tf.TransformError):
        await tf.run_transform(repo, "upper_case.py", "secrets.jsonl")
    with pytest.raises(tf.TransformError):
        await tf.run_transform(
            repo, "upper_case.py", "data/raw/x.jsonl", "configs/out.jsonl")
    with pytest.raises(tf.TransformError):
        await tf.run_transform(
            repo, "upper_case.py", "data/raw/x.jsonl", "data/raw/x.jsonl")
    with pytest.raises(FileNotFoundError):
        await tf.run_transform(repo, "upper_case.py", "data/raw/missing.jsonl")


PASSTHROUGH = '''"""Pass records through, tagging each with a step marker."""
import argparse, json

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    n = 0
    with open(args.input, encoding="utf-8") as fin, \\
         open(args.output, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rec.setdefault("marks", []).append("{MARK}")
            fout.write(json.dumps(rec) + "\\n")
            n += 1
    print(f"kept={n}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


async def test_order_roundtrip_and_new_files_appended(repo):
    tf.save_transform(repo, "b_script.py", PASSTHROUGH.replace("{MARK}", "b"))
    tf.save_transform(repo, "a_script.py", PASSTHROUGH.replace("{MARK}", "a"))
    # No saved order yet -> alphabetical.
    assert [t["name"] for t in tf.list_transforms(repo)] == ["a_script.py", "b_script.py"]

    saved = tf.write_order(repo, ["b_script.py", "a_script.py"])
    assert saved == ["b_script.py", "a_script.py"]
    assert [t["name"] for t in tf.list_transforms(repo)] == ["b_script.py", "a_script.py"]

    # A newly added script is appended, never hidden.
    tf.save_transform(repo, "c_script.py", PASSTHROUGH.replace("{MARK}", "c"))
    assert [t["name"] for t in tf.list_transforms(repo)] == [
        "b_script.py", "a_script.py", "c_script.py"]


async def test_run_chain_pipes_in_order(repo):
    tf.save_transform(repo, "first.py", PASSTHROUGH.replace("{MARK}", "first"))
    tf.save_transform(repo, "second.py", PASSTHROUGH.replace("{MARK}", "second"))
    src = repo / "data" / "raw" / "in.jsonl"
    src.write_text('{"id": 1}\n{"id": 2}\n', encoding="utf-8")

    result = await tf.run_chain(
        repo, ["first.py", "second.py"], "data/raw/in.jsonl")
    assert result["all_ok"] is True
    assert [s["script"] for s in result["steps"]] == ["first.py", "second.py"]
    assert result["output_lines"] == 2

    rows = [json.loads(l) for l in
            (repo / result["output"].replace("data/raw", "data/raw"))
            .read_text(encoding="utf-8").splitlines()]
    # Order preserved: first ran before second.
    assert rows[0]["marks"] == ["first", "second"]


async def test_run_chain_stops_on_failure(repo):
    tf.save_transform(repo, "ok.py", PASSTHROUGH.replace("{MARK}", "ok"))
    tf.save_transform(
        repo, "boom.py",
        '"""Fails."""\nimport sys\nprint("nope")\nsys.exit(2)\n')
    src = repo / "data" / "raw" / "in.jsonl"
    src.write_text('{"id": 1}\n', encoding="utf-8")

    result = await tf.run_chain(repo, ["ok.py", "boom.py"], "data/raw/in.jsonl")
    assert result["all_ok"] is False
    assert len(result["steps"]) == 2
    assert result["steps"][1]["ok"] is False
    assert result["output_exists"] is False


async def test_run_transform_failure_surfaces(repo):
    tf.save_transform(
        repo, "broken.py",
        '"""Broken on purpose."""\nimport sys\nprint("boom")\nsys.exit(3)\n')
    src = repo / "data" / "raw" / "s.jsonl"
    src.write_text("{}\n", encoding="utf-8")
    result = await tf.run_transform(repo, "broken.py", "data/raw/s.jsonl")
    assert result["ok"] is False
    assert result["exit_code"] == 3
    assert "boom" in result["stdout_tail"]
