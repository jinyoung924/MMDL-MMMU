You are grading student solutions for a research experiment. Read the packet file PACKET_PATH completely (it can be longer than one Read call: continue with offset until the end). It contains up to 4 questions. For each question it gives an image path, the problem, a reference solution (correct), and several student responses, each headed "### Response <id>".

For each question, open its image file with the Read tool and look at it before grading that question.

Grade every student response independently against the image and the reference solution.
IMAGE: are all visual facts the student states or relies on (values, labels, which point, side, angle or component a value belongs to, markings, relations shown) consistent with the image and the reference? One uncorrected wrong visual claim makes it INCORRECT.
REASONING: is the student's final line of reasoning valid (right principles, correctly applied, correct arithmetic) so that it actually supports its final answer? Mistakes the student explicitly corrects do not count. A correct final answer reached through invalid reasoning is INVALID.

Do not create or modify any file. Your final message must be only a JSON array with one object per student response in the packet, in packet order:
[{"id": "<response id>", "image": "CORRECT" or "INCORRECT", "reasoning": "VALID" or "INVALID"}, ...]
