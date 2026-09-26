# validation_Art_Theory_5 — K 지식 (Knowledge)

| 항목 | 값 |
|---|---|
| 과목 / 세부 분야 | Art_Theory / Art History |
| 이미지 유형 / 난이도 | Paintings / Medium |
| 정답 | **A** — employed a mortise and tenon system for supporting lintels |
| 모델 답 | seed 0: C ✗, seed 1: C ✗ |

## 진단 (Claude 판정 — 팀 검수 전)

- **유형**: K 지식 (Knowledge) / art history fact
- **첫 오류 (모델 응답 인용)**: “This is a carpentry technique used in wood construction, not stone. Stonehenge was made of stone, not timber, and did not use mortise and tenon joints. So this is incorrect.”
- **실제**: 스톤헨지의 사르센 석은 기둥 위 상인방(lintel)을 목공 기법인 장부맞춤(mortise and tenon)으로 고정했으므로(상인방끼리는 장부촉 이음) 정답 A가 맞음. 제공된 이미지는 스톤헨지가 아니라 루벤스의 마리 드 메디시스 연작 중 '루이 13세의 성년'으로 보이는 그림으로 문항과 무관함.
- **확신도**: high
- **비고**: 두 응답 모두 이미지를 언급하지 않고 지식만으로 풂. seed 0은 '스톤헨지는 상인방이 있는 구조가 아니다'라는 오류도 범함. 두 응답 모두 C(코벨 아치)가 스톤헨지에 맞지 않는다고 스스로 인정하고도 '돌 관련 유일한 보기'라며 선택. 이미지 불일치는 데이터 결함이지만 지식만으로 답이 유일하게 정해져 D 아님.
- **검수**: 이미지를 직접 확인함. 이미지는 스톤헨지가 아니라 루벤스의 마리 드 메디시스 연작 회화(데이터셋의 이미지-문항 불일치). 문항은 지식만으로 풀 수 있어 K 유지.

## 이미지

![image 1](image_1.png)

## 문제 (모델에 들어간 텍스트 그대로)

````text
<image 1> The use of stone in such prehistoric structures as Stonehenge illustrates an architectural tradition that
(A) employed a mortise and tenon system for supporting lintels
(B) showed the enduring power of concrete to unify large blocks of stone
(C) maintained the stability of structures using a corbeled arch
(D) unified architectural works with carefully planned gardens
Think step by step, then give your final answer on the last line in exactly this format: "Answer: X"  (X = the letter of the correct option).
````

## 모델의 풀이

<details><summary>seed 0 — 파싱 C, 오답, 잘림 아니오, 루프 아니오</summary>

````text
Step 1: Understand the context. The question refers to prehistoric structures like Stonehenge and asks about an architectural tradition illustrated by their use of stone.

Step 2: Recall what Stonehenge is. Stonehenge is a megalithic monument in England, built around 3000 BCE. It is composed of large standing stones (sarsen stones and bluestones) arranged in a circular pattern. It is not a building with lintels, arches, or gardens — it’s a ceremonial or astronomical structure.

Step 3: Evaluate each option.

Option A: “employed a mortise and tenon system for supporting lintels.” This is a woodworking technique, not typically used in prehistoric stone structures. Stonehenge was constructed using massive stone blocks, not timber joints. So this is incorrect.

Option B: “showed the enduring power of concrete to unify large blocks of stone.” Prehistoric builders did not have concrete. They used earth, wood, and stone, but no concrete. This is historically inaccurate.

Option C: “maintained the stability of structures using a corbeled arch.” A corbeled arch is a method where stones are stacked so that each layer leans inward, creating an arch. While some ancient stone structures (like Roman aqueducts) used this, Stonehenge does not feature corbelled arches. Its stability comes from the arrangement of stones and the ground, not from arches. So this is not correct.

Option D: “unified architectural works with carefully planned gardens.” Stonehenge is not associated with gardens. It’s a monument in a landscape, but there’s no evidence of planned gardens as part of its architectural design. So this is also incorrect.

Wait — none of these seem correct? Let’s reconsider.

Actually, perhaps we’re misreading the question. The question says “illustrates an architectural tradition that...” — meaning, what architectural tradition does Stonehenge represent?

Stonehenge is one of the earliest examples of monumental architecture using stone, and it demonstrates how early humans could move, erect, and align massive stones without modern tools. But none of the options directly reflect that.

However, looking again at Option C: “maintained the stability of structures using a corbeled arch.” This might be misleading. Corbeled arches were used in later periods (e.g., in Mesopotamia and Egypt), but Stonehenge’s structure is not based on arches. However, if we consider the broader category of “prehistoric stone structures,” the corbelled arch is indeed a traditional technique for stone construction that predates many other methods. But Stonehenge doesn’t use it.

Wait — perhaps the question is tricking us. Maybe the correct answer is not among them? Or perhaps I need to reconsider.

Actually, let’s look at the most plausible choice.

Option C mentions “corbeled arch,” which is a method of stone construction. In fact, some prehistoric structures (like those in the Middle East and parts of Europe) used corbelled vaults. Stonehenge, however, does not use corbeled arches — it uses vertical stone posts and horizontal sarsens. So it doesn't illustrate that tradition.

But wait — perhaps the question is asking about the *tradition* of stone construction in prehistoric times, and corbeled arches are a known example of such tradition. But Stonehenge is not an example of it.

Perhaps the question has a flaw, but we must choose the best available option.

Let’s go back to Option A: Mortise and tenon — again, this is wooden, not stone.

Option B: Concrete — no, prehistoric people didn’t use concrete.

Option D: Gardens — no.

So perhaps none are correct? But since this is a multiple-choice test, we must pick the least wrong.

Alternatively, perhaps I’m missing something.

Wait — another thought: Stonehenge’s structure is built with massive stone blocks, and its stability is achieved through careful placement and alignment — not via arches or mortise-and-tenon. So none of the options accurately describe it.

But let’s read the question again: “illustrates an architectural tradition that...”

The key phrase is “architectural tradition.” Stonehenge is often cited as an example of early monumental stone architecture, and while it doesn’t use corbeled arches, it does demonstrate the ability to work with stone in large-scale projects.

But still — none of the options match.

Wait — perhaps Option C is the closest? Because corbeled arches are a traditional stone construction method that predates many others, and Stonehenge, though not arch-based, is part of the broader tradition of stone construction.

But that’s stretching it.

Alternatively, maybe the question is referring to the fact that Stonehenge is built with stone, and corbeled arches are a way to build with stone — but again, Stonehenge doesn’t use them.

I think the intended answer might be C, because corbeled arches are a traditional architectural technique that involves stone, and Stonehenge, as a prehistoric stone structure, illustrates the use of stone in monumental architecture — even if it doesn’t use arches.

But that’s weak.

Wait — perhaps the question is misworded. Or perhaps I’m overthinking.

Let’s try to find the best fit.

Actually, I recall that Stonehenge is sometimes compared to other prehistoric structures that use corbeled techniques, but it doesn’t. So Option C is incorrect.

Perhaps the correct answer is not listed — but since we must choose, let’s reconsider.

Another idea: Option B — “enduring power of concrete to unify large blocks of stone” — this is impossible, because concrete didn’t exist in prehistoric times.

So Option B is clearly wrong.

Option A: Mortise and tenon — wrong.

Option D: Gardens — wrong.

So only Option C remains — even though it’s not accurate for Stonehenge.

But perhaps in the context of “pre-historic structures,” the corbeled arch is a recognized tradition, and Stonehenge represents the use of stone — so maybe C is the intended answer.

Alternatively, perhaps the question is flawed.

But given the choices, and assuming that the question is testing knowledge of prehistoric stone architecture traditions, and that corbeled arches are a major tradition, and Stonehenge is a monument made of stone, then C is the only possible choice.

Wait — I just realized: Stonehenge does NOT use corbeled arches. Its structure is not an arch — it’s a circle of stones.

So I think the correct answer is not among the options — but since we must choose, and Option C is the only one that mentions stone construction, perhaps it's the best available.

But I think I made a mistake — let’s double-check Option C.

Actually, in some contexts, Stonehenge is considered to have elements of corbeled construction — for example, the inner ring of stones may have been built with corbelled techniques. But this is speculative.

Upon second thought, I believe the intended answer is C, because corbeled arches are a traditional stone construction method that predates many others, and Stonehenge, as a monumental stone structure, can be seen as illustrating that tradition — even if indirectly.

But strictly speaking, it doesn’t.

Alternatively, perhaps the question is referring to the fact that Stonehenge is a prehistoric structure, and corbeled arches are a tradition of stone construction, so Stonehenge illustrates that tradition — even if it doesn’t use them.

This is weak.

Wait — let’s look for a different approach.

Perhaps the question is about the “tradition” of using stone — and corbeled arches are a form of stone construction — so C is the only one that mentions stone construction.

But again, it’s not accurate.

I think I should go with Option C as the best available answer, despite its inaccuracy.

But I recall that in some educational materials, Stonehenge is mentioned as an example of early stone architecture, and corbeled arches are a traditional technique — so perhaps the question is poorly worded.

Given the options, I’ll choose C.

Answer: C
````

</details>

<details><summary>seed 1 — 파싱 C, 오답, 잘림 아니오, 루프 아니오</summary>

````text
Let's analyze the question step by step.

The question is about prehistoric structures like Stonehenge and asks what architectural tradition they illustrate. We are given four options, and we must choose the one that best describes the architectural technique or principle used in such structures.

First, recall what Stonehenge is: it’s a prehistoric monument in Wiltshire, England, constructed around 3000 BCE. It consists of large standing stones arranged in a circular formation. The structure is not built with mortar or concrete in the way modern buildings are; instead, it relies on the careful placement of massive stone blocks, often using wooden supports during construction.

Now, let’s evaluate each option:

(A) employed a mortise and tenon system for supporting lintels

→ This is a carpentry technique used in wood construction, not stone. Stonehenge was made of stone, not timber, and did not use mortise and tenon joints. So this is incorrect.

(B) showed the enduring power of concrete to unify large blocks of stone

→ Stonehenge was not built with concrete. In fact, it was constructed without any binding material like concrete — the stones were placed and held together by their own weight and alignment, sometimes with wooden pegs or other temporary supports. Concrete was not used in prehistoric times for such structures. So this is incorrect.

(C) maintained the stability of structures using a corbeled arch

→ A corbeled arch is a type of arch formed by stacking stones so that each layer leans inward, creating a stable arc. While some prehistoric structures (like megalithic tombs or certain stone circles) may have used corbeling for support, Stonehenge itself does not feature a corbeled arch as its primary structural method. Its stability comes from the arrangement of sarsen stones and the use of smaller bluestones, not from corbeling. But more importantly, Stonehenge is not primarily an arch structure — it’s a circle. So while corbeling is a valid ancient technique, it doesn’t accurately describe Stonehenge’s architecture.

(D) unified architectural works with carefully planned gardens

→ Stonehenge is not associated with gardens. It is a ceremonial or astronomical site, and there is no evidence of garden planning integrated into its design. So this is incorrect.

Wait — none of these seem perfectly accurate? But let’s reconsider.

Actually, upon closer inspection, Option C might be misleading. Stonehenge does not have a corbeled arch — but perhaps the question is testing whether you know that Stonehenge’s stability comes from its construction method, which involves carefully placing stones and possibly using corbeling in parts of the structure. However, the main structure of Stonehenge is not an arch — it’s a circle.

But let’s think again — perhaps the question is trying to lead us to recognize that Stonehenge demonstrates the use of stone in monumental structures, and among the choices, only (C) refers to a traditional stone-building technique that can be found in prehistoric contexts — even if not directly in Stonehenge.

However, this is problematic. Let’s check historical accuracy.

In reality, Stonehenge’s stability is achieved through the precise placement of massive stones, supported by the ground and interlocking positions, not corbeling. Corbeling is more common in small-scale or domestic structures like some megalithic tombs.

So, none of the options seem correct? But we must pick the best.

Wait — Option (B) says “enduring power of concrete to unify large blocks of stone.” That’s wrong — no concrete was used.

Option (A) — mortise and tenon — also wrong.

Option (D) — gardens — wrong.

Option (C) — corbeled arch — while not applicable to Stonehenge, it is a traditional stone architectural technique used in ancient constructions like some Roman or Mesopotamian structures. But Stonehenge is not an arch structure.

Perhaps the question is flawed — but since we must choose, maybe the intended answer is (C), because corbeled arches are a form of stone architecture, and Stonehenge uses stone — even if not arches.

But that’s not accurate.

Alternatively, perhaps I misread the question. The question says “illustrates an architectural tradition that...” — meaning, what architectural tradition does Stonehenge represent?

Stonehenge represents the use of stone in monumental construction — but none of the options directly say that.

Let’s look again at the options.

Option (C): “maintained the stability of structures using a corbeled arch”

This is a specific technique — and while Stonehenge doesn’t use it, it’s the only option that refers to a traditional stone construction method.

But wait — perhaps the question is tricking us. Maybe the answer is (C) because corbeled arches are a known ancient technique — and Stonehenge is a prehistoric structure — but it doesn't use them.

Actually, after double-checking, Stonehenge does not use corbeled arches. The famous “trilithons” at Stonehenge are not corbeled — they are upright stones with horizontal lintels, supported by vertical posts, and not arches.

So perhaps the question is poorly worded, or perhaps we’re missing something.

Wait — let’s consider another angle.

Is there any part of Stonehenge that uses corbeled arches? No — the structure is a circle, not an arch.

Perhaps the question is referring to the general architectural tradition of using stone — but none of the options say that.

Alternatively, maybe the answer is (C) because corbeled arches are a traditional stone construction method — and Stonehenge is an example of stone architecture — even if not arches.

But that’s weak.

Let’s look up: Is there any evidence that Stonehenge used corbeled arches? No — it’s not an arch structure.

Therefore, perhaps the correct answer is not among them — but since we must choose, and (C) is the only one that mentions a stone-based architectural technique, it might be the intended answer.

Wait — perhaps I’m overcomplicating.

Another thought: Option (B) says “concrete to unify large blocks of stone” — that’s definitely wrong.

Option (A) — mortise and tenon — wrong.

Option (D) — gardens — wrong.

Option (C) — corbeled arch — yes, this is a real architectural tradition — and although Stonehenge doesn’t use it, it’s the only option that refers to a traditional stone technique.

But actually, Stonehenge is a classic example of stone construction — and corbeled arches are a different style — so perhaps the question is not well designed.

Wait — perhaps the answer is (C) because corbeled arches are a form of stone architecture, and Stonehenge is made of stone — even if not arches.

But that’s not logically sound.

Alternatively, perhaps the question is referring to the fact that Stonehenge is built with stone, and corbeled arches are a technique that can be used in stone — so it’s the only option that mentions a stone technique.

But again, it’s inaccurate.

Perhaps the question is about the architectural tradition of using stone — and (C) is the closest, even though it’s not correct.

But let’s think — is there any chance that the question is referring to a different structure?

No — it says “prehistoric structures as Stonehenge.”

Perhaps the correct answer is (C) because it’s the only option that refers to a traditional stone construction method — even if not applicable to Stonehenge.

But that’s not right.

Wait — let’s consider the context. This is likely a multiple-choice test — and the intended answer is probably (C).

Upon second thought — in some ancient structures, corbeled arches are used — and Stonehenge is not one of them — so (C) is incorrect.

Then what?

Perhaps the question is flawed.

But let’s look for another perspective.

Maybe the answer is (B)? But no — concrete wasn’t used.

Or (A)? No — mortise and tenon is for wood.

Or (D)? No — gardens.

So perhaps the correct answer is (C), even though it’s not perfect — because it’s the only option that refers to a traditional stone architectural technique.

Alternatively, maybe the question is asking for a general architectural tradition — and corbeled arches are a traditional stone technique — and Stonehenge is a stone structure — so it’s the best choice.

But that’s weak.

Wait — I recall that in some ancient stone structures, like the megalithic temples of Malta or Sicily, corbeled arches are used — and Stonehenge is not one of them — so (C) is not correct.

Perhaps the answer is (C) because it’s the only option that is technically true for some prehistoric structures — but the question specifically says “Stonehenge.”

I think the most reasonable choice — despite being imperfect — is (C), because it’s the only option that refers to a traditional stone architectural technique.

But let’s double-check online or standard knowledge.

Actually, upon reflection, I realize that Stonehenge does not use corbeled arches — it uses vertical stones and horizontal lintels — which is not corbeled arches.

Therefore, the correct answer should not be (C).

But since all other options are clearly wrong, and (C) is the only one that refers to a traditional stone technique — perhaps it’s the intended answer.

Alternatively, maybe the question is about the architectural tradition of using stone — and (C) is not the best.

Wait — perhaps the answer is (B)? But no — concrete was not used.

Unless they mean “stone” as in “stone blocks” — but “concrete” is not stone.

So I think the answer must be (C), even though it’s not accurate.

But let’s think — is there any chance that the question is referring to the “corbeled arch” as a method of stone construction — and Stonehenge is an example — but it’s not.

I think the correct answer is not listed — but since we must choose, and (C) is the only one that mentions a traditional stone technique — I’ll go with (C).

But I’m not confident.

Wait — perhaps I’m missing something.

Let me read the question again: “The use of stone in such prehistoric structures as Stonehenge illustrates an architectural tradition that…”

And the options are about techniques.

In reality, Stonehenge does not use corbeled arches — so (C) is wrong.

Then what?

Perhaps the answer is (B)? But no — concrete was not used.

Unless they mean “stone” as in “stone blocks” — but “concrete” is not stone.

So perhaps the answer is (A)? But no — mortise and tenon is for wood.

So I think the only possible answer is (C) — even though it’s not correct.

But let’s consider this: in some interpretations, the structure of Stonehenge might be seen as having a kind of corbeled effect — but it’s not.

I think I need to accept that (C) is the intended answer.

Alternatively, perhaps the question is about the architectural tradition of using stone — and (C) is the only option that refers to a stone technique.

But that’s not logical.

Wait — perhaps the answer is (C) because corbeled arches are a traditional stone architectural technique — and Stonehenge is made of stone — so it illustrates that tradition — even if it doesn’t use it.

That’s stretching it.

But perhaps in the context of the question, (C) is the best available option.

I think the correct answer is (C).

Answer: C
````

</details>
