"""Conservative text triage after image screening; never marks rows train-ready."""
from collections import Counter
import json
from pathlib import Path
import re
from audit_bmmr import file_sha

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data/diagram_v2'


def main():
    rows=list(map(json.loads,(DATA/'pool_image_screen.jsonl').read_text().splitlines()))
    old=json.loads((ROOT/'pilot_diagram/annotations.json').read_text())
    old_bad=old['excluded_after_image_review']
    results=[]
    for i,r in enumerate(rows):
        q=r['question'];reasons=[]
        if r['status']!='requires_question_and_annotation_review':reasons.append('protected_image_near_match')
        if r['id'] in old_bad:reasons.append('prior_visual_rejection: '+old_bad[r['id']])
        if len(q)>1800:reasons.append('long_or_multi_item')
        if len(re.findall(r'(?:\(A\)|\bA[.:])',q))>1:reasons.append('multiple_A_options')
        if re.search(r'check all|select all|all that apply|\(a\)|\(b\)|\(c\)|fill in|answer box|\bsquare\b',q,re.I):
            reasons.append('multi_select_or_incomplete_fields')
        if re.search(r'correct answer|not correct|was incorrect|I got|Answer\s*:|why [A-H] is the answer|computer gets',q,re.I):
            reasons.append('answer_or_feedback_in_question')
        if re.search(r'Part [A-C]\s*:|\b[A-C]\.\s*(?:what|find|calculate|determine|give|name)\b',q,re.I):
            reasons.append('possible_subquestions_instead_of_options')
        if re.search(r'https?://',q):reasons.append('external_link_or_malformed_transcription')
        results.append({'index':i,'id':r['id'],'reasons':reasons,'ready_for_training':False,
                        'status':'held_for_review' if reasons else 'requires_visual_and_answer_review'})
    counts=Counter(x['status'] for x in results)
    (DATA/'question_quality_triage.json').write_text(json.dumps({'source_screen_sha256':file_sha(DATA/'pool_image_screen.jsonl'),
        'script_sha256':file_sha(Path(__file__)),'counts':dict(counts),
        'limitations':['Text heuristics can overflag valid questions; exceptions require explicit review.',
                       'Passing triage does not establish single-answer validity, readable images, or independent gold.'],
        'items':results},indent=2)+'\n')
    print(json.dumps(dict(counts)),flush=True)


if __name__=='__main__':main()
