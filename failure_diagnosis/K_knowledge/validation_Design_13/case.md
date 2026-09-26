# validation_Design_13 — K 지식 (Knowledge)

| 항목 | 값 |
|---|---|
| 과목 / 세부 분야 | Design / Design History |
| 이미지 유형 / 난이도 | Paintings / Medium |
| 정답 | **B** — model the anatomy of the figures naturalistically |
| 모델 답 | seed 0: C ✗, seed 1: C ✗ |

## 진단 (Claude 판정 — 팀 검수 전)

- **유형**: K 지식 (Knowledge) / wrong art-historical fact
- **첫 오류 (모델 응답 인용)**: “Portability — because it’s made of small, manageable pieces, it can be transported without breaking apart (as was common for Roman mosaics)”
- **실제**: 이미지는 폼페이 '파우누스의 집'에서 나온 알렉산더 모자이크(이수스 전투)이며 모델도 올바르게 식별함. 100만 개 이상의 미세한 테세라(opus vermiculatum)는 섬세한 색조·음영 변화로 인물과 말의 해부학적 형태를 자연주의적으로 표현하기 위한 것(B)이고, 운반·수정 용이성과는 무관하다.
- **확신도**: high
- **비고**: seed 1도 '모자이크 타일로는 회화·조각만큼 자연주의적 해부 묘사가 불가능하다'며 B를 배제하고 C를 골라 같은 K 오류를 범함.
- **검수**: 인용문과 사실 오류를 텍스트로 확인. 판정 유지.

## 이미지

![image 1](image_1.png)

## 문제 (모델에 들어간 텍스트 그대로)

````text
The use of over one million small tiles to make the Alexander Mosaic allowed its creator to . <image 1>
(A) depict a disorganized scene that overwhelms the viewer
(B) model the anatomy of the figures naturalistically
(C) modify and transport the composition easily
(D) reduce the figures into abstract forms
Think step by step, then give your final answer on the last line in exactly this format: "Answer: X"  (X = the letter of the correct option).
````

## 모델의 풀이

<details><summary>seed 0 — 파싱 C, 오답, 잘림 아니오, 루프 아니오</summary>

````text
Step 1: Understand the context.
The Alexander Mosaic is a famous Roman mosaic, originally from the House of the Faun in Pompeii. It depicts the Battle of Issus, where Alexander the Great defeated Darius III. The mosaic is composed of over one million small tiles (tesserae), which were laid down to form a large-scale image.

Step 2: Consider the implications of using over one million small tiles.
Mosaics are often created by laying down individual tesserae — small pieces of stone, glass, or other materials. This method allows for:
- High detail and precision
- Flexibility in composition — since each tile can be placed individually, artists could adjust or modify the image during construction
- Portability — because it’s made of small, manageable pieces, it can be transported without breaking apart (as was common for Roman mosaics)

Step 3: Evaluate the options.

(A) "depict a disorganized scene that overwhelms the viewer"
— While the scene is chaotic and dynamic, the use of tiles does not inherently cause disorganization; it's more about how the artist arranged them for dramatic effect. Not the best answer.

(B) "model the anatomy of the figures naturalistically"
— Mosaics can show anatomical detail, but this is not the primary advantage of using millions of small tiles. Naturalism is achieved through skillful arrangement, not necessarily tile count.

(C) "modify and transport the composition easily"
— This is plausible. Since the mosaic is made of small tiles, the artist could rearrange or modify sections during production. Also, as a large mosaic panel, it could be broken into smaller sections for transport (which was common in Roman practice). This fits well with historical knowledge.

(D) "reduce the figures into abstract forms"
— No, the mosaic is highly detailed and figurative — it shows realistic human forms, horses, chariots, etc. Abstract forms would imply non-representational shapes, which is not the case here.

Step 4: Choose the best answer.
Option (C) is the most accurate. The use of small tiles allowed the mosaicist to make adjustments during creation and also facilitated its transport, especially important given that such large works were often moved between locations.

Answer: C
````

</details>

<details><summary>seed 1 — 파싱 C, 오답, 잘림 아니오, 루프 아니오</summary>

````text
Let's analyze the question and the image step by step.

The Alexander Mosaic is a famous Roman mosaic, created using over one million small tiles (tesserae). It depicts the Battle of Issus, where Alexander the Great defeats Darius III. The mosaic is known for its detailed and dynamic composition — horses in motion, soldiers fighting, chariots, etc.

Now let’s evaluate each option:

(A) “depict a disorganized scene that overwhelms the viewer” — This is incorrect. The mosaic is actually highly organized, with clear composition, perspective, and narrative flow. The battle is depicted with dramatic energy but not chaos or disorganization.

(B) “model the anatomy of the figures naturalistically” — While the mosaic does show detailed human forms, the medium (mosaic tiles) doesn’t allow for the same level of naturalistic anatomical detail as painting or sculpture. Also, the mosaic was likely made to convey mythic or heroic drama rather than scientific realism.

(C) “modify and transport the composition easily” — This is plausible. Mosaics were often created on a large scale and could be assembled in sections. The use of small, individual tiles meant that the artist could adjust parts of the composition without having to rework the entire piece. Additionally, since mosaics were often transported and installed in different locations (like in Roman villas), modular construction with small tiles would have allowed for easier handling and transportation.

(D) “reduce the figures into abstract forms” — No, this is incorrect. The mosaic is representational — it shows specific characters, weapons, horses, and armor. Abstract forms are not present; it’s a realistic depiction of a historical battle scene.

Therefore, the best answer is (C) — the use of small tiles allowed the creator to modify and transport the composition easily.

Answer: C
````

</details>
