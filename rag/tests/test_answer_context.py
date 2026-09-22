import json
import unicodedata

from test_rag import create, index, search


def test_answer_context_restores_missing_sections_and_keeps_citable_ids(client):
    c, root, core = client
    name = unicodedata.normalize("NFD", "마늘볶음밥.md")
    (root / name).write_text(
        "# 마늘볶음밥\n\n## 기본 정보\n2인분\n\n## 재료\n밥 400g, 마늘 10개, 기름 2큰술\n\n## 조리 순서\n마늘을 볶고 밥을 넣습니다.\n"
    )
    (root / "README.md").write_text("# 전체 레시피 목록\n레시피 조리 순서 안내입니다.\n")
    wid = create(c, "")
    assert index(c, wid)["state"] == "READY"
    found = search(c, wid, "마늘볶음밥 레시피", top_k=1)
    assert found["evidence"][0]["relative_path"] == name
    context = core.retrieval.answer_context(found, 8000)
    assert any("밥 400g" in e["text"] for e in context)
    assert any("마늘을 볶고" in e["text"] for e in context)
    for evidence in context:
        response = c.get(
            f"/api/rag/workspaces/{wid}/evidence/{evidence['evidence_id']}",
            params={"revision_id": found["revision_id"]},
        )
        assert response.status_code == 200
        assert response.json()["evidence"]["text"] == evidence["text"]
    size = sum(
        len(
            json.dumps(
                {k: e.get(k) for k in ("evidence_id", "relative_path", "title_path", "text")},
                ensure_ascii=False,
            )
        )
        for e in context
    )
    assert size <= 8000


def test_answer_context_expands_only_matching_sheet_and_revision(client):
    from openpyxl import Workbook

    c, root, core = client
    wb = Workbook()
    ws = wb.active
    ws.title = "브랜드A"
    ws.append(["상품명", "가격"])
    for i in range(16):
        ws.append([f"원두-{i}", 1000 + i])
    other = wb.create_sheet("다른 브랜드")
    other.append(["상품명", "가격"])
    other.append(["다른 상품", 999])
    wb.save(root / "원두.xlsx")
    wid = create(c, "")
    assert index(c, wid)["state"] == "READY"
    found = search(c, wid, "브랜드A 원두")
    found["evidence"] = [e for e in found["evidence"] if e["location"].get("sheet") == "브랜드A"][:1]
    assert found["evidence"]
    context = core.retrieval.answer_context(found, 20000)
    assert len(context) == 16
    assert {e["location"]["sheet"] for e in context} == {"브랜드A"}
    assert any("원두-15" in e["text"] for e in context)


def test_named_source_spelling_variant_beats_generic_recipe_hits(client):
    c, root, core = client
    (root / '돈가스.md').write_text('# 돈가스\n\n## 재료\n등심 300g, 빵가루 100g\n\n## 조리 순서\n170도에서 튀깁니다.\n')
    for i in range(8):
        (root / f'안내{i}.md').write_text('# 레시피 안내\n레시피가 뭐야? 전체 레시피 설명과 조리 정보.\n')
    wid = create(c, '')
    assert index(c, wid)['state'] == 'READY'
    found = search(c, wid, '돈까스 레시피가 뭐야?')
    assert found['evidence'][0]['relative_path'] == '돈가스.md'
    context = core.retrieval.answer_context(found, 16000)
    assert {e['relative_path'] for e in context} == {'돈가스.md'}
    assert any('등심 300g' in e['text'] for e in context)
    assert any('170도' in e['text'] for e in context)


def test_context_budget_never_evicts_the_matched_late_section(client):
    c, root, core = client
    (root / '정책.md').write_text('# 정책\n\n' + '\n\n'.join(f'## 조항{i}\n일반 운영 안내 {i}' for i in range(30)) + '\n\n## 비밀항목\nTARGET-73 보관은 73일\n')
    wid = create(c, '')
    assert index(c, wid)['state'] == 'READY'
    found = search(c, wid, '정책 TARGET-73')
    late = next(e for e in found['evidence'] if 'TARGET-73' in e['text'])
    found['evidence'] = [late]
    context = core.retrieval.answer_context(found, 1000)
    assert context[0]['evidence_id'] == late['evidence_id']
    assert 'TARGET-73' in context[0]['text']
