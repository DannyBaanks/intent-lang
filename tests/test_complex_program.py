import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from intentlang.cobol_guard import verify_cobol_round_trip
from intentlang.codegen import generate_code
from intentlang.complex_program import (
    Effect,
    PermissionError,
    ProgramTypeError,
    check_program,
    parse_structured,
    plan_program,
    run_structured,
)
from intentlang.executor import execute_program
from intentlang.portable_codegen import generate_program_source
from intentlang.program import ref, value
from intentlang.transaction import execute_transaction


def test_smoke_typed_ast_and_reference():
    program = parse_structured('{"steps":[{"let":{"name":"path","value":"x","in":{"call":"cap.fs.read","inputs":{"path":{"$ref":"path"}}}}}]}')
    assert not check_program(program)
    assert isinstance(ref("x"), type(value(1)))


def test_smoke_type_checker_rejects_missing_input():
    program = parse_structured('{"steps":[{"call":"cap.fs.write","inputs":{"content":"x"}}]}')
    with pytest.raises(ProgramTypeError, match="missing required inputs"):
        plan_program(program)


def test_smoke_type_checker_rejects_wrong_scalar_type():
    program = parse_structured('{"steps":[{"call":"cap.net.connect","inputs":{"host":"localhost","port":"80"}}]}')
    with pytest.raises(ProgramTypeError, match="expected Number"):
        plan_program(program)


def test_smoke_effect_plan_requires_confirmation():
    program = parse_structured('{"steps":[{"call":"cap.fs.write","inputs":{"path":"x","content":"y"}}]}')
    plan = plan_program(program)
    assert plan.effects == (Effect.FILESYSTEM_WRITE,)
    assert plan.requires_confirmation is True


def test_smoke_effect_policy_denies_write():
    program = parse_structured('{"steps":[{"call":"cap.fs.write","inputs":{"path":"x","content":"y"}}]}')
    with pytest.raises(PermissionError, match=r"filesystem\.write"):
        plan_program(program, allowed_effects={Effect.FILESYSTEM_READ})


def test_smoke_structured_execution_and_evidence(tmp_path):
    path = str(tmp_path / "out.txt")
    source = json.dumps({"steps": [{"call": "cap.fs.write", "inputs": {"path": path, "content": "ok"}}]})
    plan, result = run_structured(source, confirmed=True)
    assert plan.capabilities == ("cap.fs.write",)
    assert result["status"] == "OK"
    assert result["evidence"][0]["node_id"] == "n1"


def test_smoke_structured_if_foreach_and_compare():
    source = json.dumps({"steps": [{"foreach": {
        "in": ["ready"],
        "as": "state",
        "do": {"if": {
            "condition": {"compare": {"op": "eq", "left": {"$ref": "state"}, "right": "ready"}},
            "then": {"sequence": [{"compare": {"op": "eq", "left": {"$ref": "state"}, "right": "ready"}}]},
        }},
    }}]})
    program = parse_structured(source)
    assert not check_program(program)
    assert execute_program(program)["result"] is True


def test_structured_functions_expand_with_arguments():
    source = json.dumps({
        "functions": {
            "write_text": {
                "params": ["target", "text"],
                "body": [{"call": "cap.fs.write", "inputs": {
                    "path": {"$ref": "target"}, "content": {"$ref": "text"},
                }}],
            },
        },
        "steps": [{"call_function": "write_text", "args": ["result.txt", "function-ok"]}],
    })
    program = parse_structured(source)
    assert plan_program(program).capabilities == ("cap.fs.write",)
    assert program.root.args[0].primitive == "CALL"


def test_structured_try_catch_and_return():
    program = parse_structured(json.dumps({"steps": [{
        "try": {
            "body": {"call": "cap.fs.read", "inputs": {"path": "missing.txt"}},
            "catch": {"return": "caught"},
            "finally": {"compare": {"op": "eq", "left": "done", "right": "done"}},
        },
    }]}))
    result = execute_program(program)
    assert result["status"] == "OK"
    assert result["result"] == "caught"


def test_transaction_rolls_back_failed_program(tmp_path):
    path = tmp_path / "tracked.txt"
    path.write_text("before", encoding="utf-8")
    program = parse_structured(json.dumps({"steps": [
        {"call": "cap.fs.write", "inputs": {"path": str(path), "content": "after"}},
        {"call": "cap.fs.copy", "inputs": {"src": str(tmp_path / "absent"), "dst": str(tmp_path / "copy.txt")}},
    ]}))
    result = execute_transaction(program, [path])
    assert result["status"] == "ERROR"
    assert result["transaction"] == "ROLLED_BACK"
    assert path.read_text(encoding="utf-8") == "before"


def test_structured_transaction_rolls_back_failed_body(tmp_path):
    path = tmp_path / "tracked.txt"
    path.write_text("before", encoding="utf-8")
    source = json.dumps({"steps": [{"transaction": {
        "paths": [str(path)],
        "body": {"sequence": [
            {"call": "cap.fs.write", "inputs": {"path": str(path), "content": "after"}},
            {"call": "cap.fs.copy", "inputs": {"src": str(tmp_path / "missing"), "dst": str(tmp_path / "copy.txt")}},
        ]},
    }}]})
    result = execute_program(parse_structured(source))
    assert result["status"] == "ERROR"
    assert path.read_text(encoding="utf-8") == "before"


def test_smoke_placeholders_never_report_success():
    result = execute_program(parse_structured('{"steps":[{"call":"cap.media.render","inputs":{"source":"a","output":"b"}}]}'))
    assert result["status"] == "OK"
    assert result["result"]["rendered"] is False
    assert result["result"]["placeholder"] is True


@pytest.mark.parametrize("language", ["c", "java"])
def test_smoke_complete_program_compiles_and_runs(language, tmp_path):
    src = str(tmp_path / "source.txt")
    dst = str(tmp_path / "copy.txt")
    document = {"steps": [{"let": {"name": "source", "value": src, "in": {
        "sequence": [
            {"call": "cap.fs.write", "inputs": {"path": {"$ref": "source"}, "content": "hello"}},
            {"call": "cap.fs.copy", "inputs": {"src": {"$ref": "source"}, "dst": dst}},
            {"if": {"condition": {"compare": {"op": "eq", "left": "ready", "right": "ready"}}, "then": {
                "foreach": {"in": ["one", "two"], "as": "item", "do": {"compare": {"op": "eq", "left": {"$ref": "item"}, "right": {"$ref": "item"}}}},
            }}},
        ]
    }}}]}
    program = parse_structured(json.dumps(document))
    generated = generate_program_source(program, language)
    compiler = "gcc" if language == "c" else "javac"
    if shutil.which(compiler) is None:
        pytest.skip(f"{compiler} unavailable")
    source_path = tmp_path / ("IntentProgram.c" if language == "c" else "IntentProgram.java")
    source_path.write_text(generated.source, encoding="utf-8")
    if language == "c":
        executable = tmp_path / "intent_program.exe"
        subprocess.run([compiler, str(source_path), "-o", str(executable)], check=True, capture_output=True, text=True)
        subprocess.run([str(executable)], cwd=tmp_path, check=True, capture_output=True, text=True)
    else:
        compile_result = subprocess.run([compiler, str(source_path)], cwd=tmp_path, check=False, capture_output=True, text=True)
        assert compile_result.returncode == 0, compile_result.stderr
        subprocess.run(["java", "IntentProgram"], cwd=tmp_path, check=True, capture_output=True, text=True)
    assert (tmp_path / "copy.txt").read_text(encoding="utf-8") == "hello"


@pytest.mark.parametrize("language", ["c", "java"])
@pytest.mark.parametrize("primitive,operands", [
    ("WRITE", {"path": "out.txt", "content": "ok"}),
    ("COPY", {"src": "in.txt", "dst": "out.txt"}),
    ("MOVE", {"src": "in.txt", "dst": "out.txt"}),
    ("DELETE", {"path": "out.txt"}),
    ("RUN", {"cmd": "echo smoke"}),
])
def test_smoke_codegen_portable_targets(language, primitive, operands, tmp_path):
    result = generate_code(primitive, language, operands)
    assert result.verified is True
    assert result.semantic_score == 1.0
    compiler = "gcc" if language == "c" else "javac"
    if shutil.which(compiler) is None:
        pytest.skip(f"{compiler} unavailable")
    source = tmp_path / ("program.c" if language == "c" else "IntentProgram.java")
    source.write_text(result.code, encoding="utf-8")
    command = [compiler, str(source), "-o", str(tmp_path / "program.exe")] if language == "c" else [compiler, str(source)]
    subprocess.run(command, check=True, capture_output=True, text=True)


def test_cobol_codegen_has_real_unverified_filesystem_templates():
    result = generate_code("WRITE", "cobol", {"path": "out.txt", "content": "ok"})
    assert result.verified is False
    assert result.semantic_score == 0.0
    assert "OPEN OUTPUT OUT-FILE" in result.code
    assert "WRITE OUT-REC" in result.code


def test_cobol_generated_program_compiles_and_runs_when_available(tmp_path):
    compiler = shutil.which("cobc")
    if compiler is None:
        pytest.skip("cobc unavailable")
    program = parse_structured(json.dumps({"steps": [{
        "call": "cap.fs.write",
        "inputs": {"path": "cobol-output.txt", "content": "standalone-pass"},
    }]}))
    source = tmp_path / "program.cob"
    executable = tmp_path / "program.exe"
    source.write_text(generate_program_source(program, "cobol").source, encoding="utf-8")
    command = [compiler, "-x", "-free"]
    config_dir = os.environ.get("COB_CONFIG_DIR")
    if config_dir:
        command.extend(["--conf", str(Path(config_dir) / "default.conf")])
    command.extend(["-o", str(executable), str(source)])
    subprocess.run(command, check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True, cwd=tmp_path)
    assert (tmp_path / "cobol-output.txt").read_text(encoding="utf-8").strip() == "standalone-pass"


def test_cobol_variable_read_rejects_oversized_record_when_available(tmp_path):
    compiler = shutil.which("cobc")
    if compiler is None:
        pytest.skip("cobc unavailable")
    (tmp_path / "input.txt").write_text("x" * 4097 + "\n", encoding="utf-8")
    program = parse_structured(json.dumps({"steps": [{
        "call": "cap.fs.read", "inputs": {"path": "input.txt"},
    }]}))
    source = tmp_path / "program.cob"
    executable = tmp_path / "program.exe"
    source.write_text(generate_program_source(program, "cobol").source, encoding="utf-8")
    command = [compiler, "-x", "-free"]
    config_dir = os.environ.get("COB_CONFIG_DIR")
    if config_dir:
        command.extend(["--conf", str(Path(config_dir) / "default.conf")])
    command.extend(["-o", str(executable), str(source)])
    subprocess.run(command, check=True, capture_output=True, text=True)

    result = subprocess.run([str(executable)], cwd=tmp_path, check=False, capture_output=True, text=True)

    assert result.returncode == 99
    assert "CRITICAL: SEMANTIC INVARIANT VIOLATION" in result.stdout


def test_cobol_codegen_keeps_advanced_features_as_hooks():
    result = generate_code("QUERY", "cobol", {"query": "select 1"})
    assert result.verified is False
    assert "TODO(cobol-backend)" in result.code
    assert "public runtime runner" in result.code


def test_cobol_program_renderer_preserves_effect_order():
    program = parse_structured(json.dumps({"steps": [
        {"call": "cap.fs.write", "inputs": {"path": "one.txt", "content": "one"}},
        {"call": "cap.fs.copy", "inputs": {"src": "one.txt", "dst": "two.txt"}},
        {"call": "cap.fs.delete", "inputs": {"path": "two.txt"}},
    ]}))
    generated = generate_program_source(program, "cobol")
    assert generated.language == "cobol"
    assert generated.source.index("OPEN OUTPUT") < generated.source.index("CBL-COPY-FILE")
    assert generated.source.index("CBL-COPY-FILE") < generated.source.index("CBL-DELETE-FILE")
    assert "IDENTIFICATION DIVISION." in generated.source


def test_cobol_program_renderer_supports_if_and_foreach():
    program = parse_structured(json.dumps({"steps": [{
        "foreach": {"in": ["one", "two"], "as": "item", "do": {"if": {
            "condition": {"compare": {"op": "eq", "left": {"$ref": "item"}, "right": "one"}},
            "then": {"call": "cap.process.run", "inputs": {"cmd": "echo one"}},
        }}},
    }]}))
    generated = generate_program_source(program, "cobol")
    assert "PERFORM VARYING INDEX-1" in generated.source
    assert "IF FUNCTION TRIM(ITEM) = FUNCTION TRIM('one')" in generated.source
    assert "END-PERFORM" in generated.source


def test_cobol_program_renderer_emits_status_based_try_and_return():
    program = parse_structured(json.dumps({"steps": [{
        "try": {
            "body": {"call": "cap.process.run", "inputs": {"cmd": "echo ok"}},
            "catch": {"return": 1},
            "finally": {"return": 0},
        },
    }]}))
    generated = generate_program_source(program, "cobol")
    assert "CALL 'SYSTEM' USING 'echo ok' RETURNING WS-ERROR" in generated.source
    assert "IF WS-ERROR NOT = 0" in generated.source
    assert "MOVE 1 TO WS-RETURN" in generated.source
    assert "MOVE 0 TO WS-RETURN" in generated.source


def test_cobol_program_renderer_accepts_structured_function_expansion():
    source = json.dumps({
        "functions": {
            "write": {
                "params": ["file", "text"],
                "body": [{"call": "cap.fs.write", "inputs": {
                    "path": {"$ref": "file"}, "content": {"$ref": "text"},
                }}],
            },
        },
        "steps": [{"call_function": "write", "args": ["generated.txt", "ok"]}],
    })
    generated = generate_program_source(parse_structured(source), "cobol")
    assert "ASSIGN TO 'generated.txt'" in generated.source
    assert "MOVE 'ok' TO OUT-REC-1" in generated.source


def test_cobol_program_renderer_emits_transaction_restore_path():
    program = parse_structured(json.dumps({"steps": [{"transaction": {
        "paths": ["tracked.txt"],
        "body": {"call": "cap.fs.write", "inputs": {"path": "tracked.txt", "content": "new"}},
    }}]}))
    generated = generate_program_source(program, "cobol")
    assert "tracked.txt.intentlang.bak" in generated.source
    assert "CBL-COPY-FILE" in generated.source
    assert "IF WS-ERROR NOT = 0" in generated.source


def test_cobol_inverse_guard_accepts_generated_linear_program():
    program = parse_structured(json.dumps({"steps": [
        {"call": "cap.fs.write", "inputs": {"path": "out.txt", "content": "ok"}},
        {"call": "cap.fs.copy", "inputs": {"src": "out.txt", "dst": "copy.txt"}},
        {"call": "cap.fs.delete", "inputs": {"path": "copy.txt"}},
    ]}))
    source = generate_program_source(program, "cobol").source

    result = verify_cobol_round_trip(program, source)

    assert result.passed is True
    assert result.reason == "PASS"
    assert result.expected == result.recovered


def test_cobol_renderer_injects_write_and_read_invariants():
    program = parse_structured(json.dumps({"steps": [
        {"call": "cap.fs.write", "inputs": {"path": "out.txt", "content": "ok"}},
        {"call": "cap.fs.read", "inputs": {"path": "out.txt"}},
    ]}))

    source = generate_program_source(program, "cobol").source

    assert "01 WS-MAX-RECORD-SIZE PIC 9(9) COMP-5 VALUE 4096." in source
    assert source.count("CRITICAL: SEMANTIC INVARIANT VIOLATION") == 2
    assert source.count("CRITICAL: FILE STATUS VIOLATION") == 6
    assert "IF FUNCTION LENGTH('ok') > WS-MAX-RECORD-SIZE" in source
    assert "RECORD IS VARYING IN SIZE FROM 1 TO 8192 CHARACTERS" in source
    assert "IF WS-INPUT-SIZE > WS-MAX-RECORD-SIZE" in source


def test_cobol_renderer_injects_foreach_index_and_item_invariants():
    program = parse_structured(json.dumps({"steps": [{
        "foreach": {"in": ["one", "two"], "as": "item", "do": {
            "call": "cap.process.run", "inputs": {"cmd": "echo one"},
        }},
    }]}))

    source = generate_program_source(program, "cobol").source

    assert "IF INDEX-1 > 2" in source
    assert "SEMANTIC INVARIANT VIOLATION - FOREACH index OUT OF BOUNDS" in source
    assert "SEMANTIC INVARIANT VIOLATION - FOREACH item OUT OF BOUNDS" in source


def test_cobol_inverse_guard_rejects_mutated_literal():
    program = parse_structured(json.dumps({"steps": [
        {"call": "cap.fs.write", "inputs": {"path": "out.txt", "content": "ok"}},
    ]}))
    source = generate_program_source(program, "cobol").source.replace("MOVE 'ok'", "MOVE 'tampered'")

    result = verify_cobol_round_trip(program, source)

    assert result.passed is False
    assert result.reason.startswith("MISMATCH:")


def test_cobol_inverse_guard_rejects_missing_defense():
    program = parse_structured(json.dumps({"steps": [
        {"call": "cap.fs.write", "inputs": {"path": "out.txt", "content": "ok"}},
    ]}))
    source = generate_program_source(program, "cobol").source
    source = source.replace("IF FUNCTION LENGTH('ok') > WS-MAX-RECORD-SIZE", "")

    result = verify_cobol_round_trip(program, source)

    assert result.passed is False
    assert result.reason.startswith("INVARIANT_VIOLATION:")


def test_cobol_inverse_guard_rejects_injected_statement():
    program = parse_structured(json.dumps({"steps": [
        {"call": "cap.fs.write", "inputs": {"path": "out.txt", "content": "ok"}},
    ]}))
    source = generate_program_source(program, "cobol").source.replace(
        "PROCEDURE DIVISION.", "PROCEDURE DIVISION.\n    DISPLAY 'injected'."
    )

    result = verify_cobol_round_trip(program, source)

    assert result.passed is False
    assert result.reason.startswith("NOT_SUPPORTED:")


def test_cobol_inverse_guard_rejects_unrecognized_source():
    program = parse_structured(json.dumps({"steps": [
        {"call": "cap.fs.write", "inputs": {"path": "out.txt", "content": "ok"}},
    ]}))

    result = verify_cobol_round_trip(program, "DISPLAY 'ok'.")

    assert result.passed is False
    assert result.reason.startswith("NOT_SUPPORTED:")


def test_cobol_inverse_guard_rejects_control_flow_for_now():
    program = parse_structured(json.dumps({"steps": [{"if": {
        "condition": {"compare": {"op": "eq", "left": "a", "right": "a"}},
        "then": {"call": "cap.fs.write", "inputs": {"path": "out.txt", "content": "ok"}},
    }}]}))
    source = generate_program_source(program, "cobol").source

    result = verify_cobol_round_trip(program, source)

    assert result.passed is False
    assert result.reason.startswith("NOT_SUPPORTED:")
