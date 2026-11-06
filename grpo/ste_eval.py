"""Diagnostic only, not a protocol eval: the base model with an ASD-STE100-style instruction in place of
run_eval.py's CoT suffix. Everything else is run_eval.py unchanged; the variant text is saved with the results."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_eval as R

STE = ('Solve the problem in numbered steps (Step 1, Step 2, ...). Write one fact or one calculation per step. '
       'Keep each sentence under 20 words. Use active voice. Name each quantity explicitly; never write "it" or "this". '
       'Do not repeat a check that you already did. Then give your final answer on the last line in exactly this format: ')
R.COT_MC_SUFFIX = STE + '"Answer: X"  (X = the letter of the correct option).'
R.COT_OPEN_SUFFIX = STE + '"Answer: <single word or phrase>".'

if __name__ == '__main__':
    out = Path(sys.argv[sys.argv.index('--out') + 1])
    out.mkdir(parents=True, exist_ok=True)
    (out / 'prompt_variant.txt').write_text(R.COT_MC_SUFFIX + '\n' + R.COT_OPEN_SUFFIX + '\n')
    R.main()
