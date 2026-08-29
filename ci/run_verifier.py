"""Run the engine-lang verifier and exit with its code. Called by CI."""
import sys

sys.path.insert(0, "src")

from engine_lang.verifier import overall_exit_code, print_report, verify_all

results = verify_all()
print_report(results)
sys.exit(overall_exit_code(results))