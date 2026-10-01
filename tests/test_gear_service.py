"""장비 구매 서비스 (3단계 spec §5). 값은 전부 지어낸 것."""
from datetime import date

import pytest

TODAY = date(2026, 6, 15)


def _order(**over):
    base = {'original': None, 'date': '2026-05-02', 'shop': '가나낚시',
            'items': [{'item': '테스트 에기 3개', 'category': '에기', 'price': '12,000'},
                      {'item': '테스트 봉돌', 'category': '', 'price': 3000}]}
    base.update(over)
    return base


def _gear(name='테스트 릴', kind='릴'):
    from services.fishing_log.gear_service import save_gear_item
    return save_gear_item(None, {'name': name, 'kind': kind, 'memo': '메모'})


# ---- 주문 저장 ----

def test_create_order_adds_items_with_same_date_and_shop(app):
    from models import GearPurchase
    from services.fishing_log.gear_service import save_order
    order = save_order(_order())
    rows = GearPurchase.query.order_by(GearPurchase.id).all()
    assert [(r.purchase_date, r.shop, r.item, r.category, r.price) for r in rows] == [
        (date(2026, 5, 2), '가나낚시', '테스트 에기 3개', '에기', 12000),
        (date(2026, 5, 2), '가나낚시', '테스트 봉돌', '기타', 3000),
    ]
    assert order['total'] == 15000
    assert order['date'] == '2026-05-02' and order['shop'] == '가나낚시'


def test_update_order_adds_edits_deletes_and_propagates_date_shop(app):
    from models import GearPurchase
    from services.fishing_log.gear_service import save_order
    first = save_order(_order())
    keep, drop = first['items']
    save_order({'original': {'date': '2026-05-02', 'shop': '가나낚시'}, 'date': '2026-05-03', 'shop': '나다낚시',
                'items': [{'id': keep['id'], 'item': '수정된 에기', 'category': '에기', 'price': 11000},
                          {'item': '새 도래', 'category': '도래', 'price': 500}]})
    rows = GearPurchase.query.order_by(GearPurchase.id).all()
    assert [(r.item, r.purchase_date, r.shop) for r in rows] == [
        ('수정된 에기', date(2026, 5, 3), '나다낚시'), ('새 도래', date(2026, 5, 3), '나다낚시')]
    assert GearPurchase.query.get(drop['id']) is None


def test_update_rejects_item_id_from_another_order(app):
    from services.fishing_log.gear_service import GearValidationError, save_order
    other = save_order(_order(shop='딴가게'))
    save_order(_order())
    with pytest.raises(GearValidationError) as exc:
        save_order({'original': {'date': '2026-05-02', 'shop': '가나낚시'}, 'date': '2026-05-02', 'shop': '가나낚시',
                    'items': [{'id': other['items'][0]['id'], 'item': 'x', 'price': 1}]})
    assert exc.value.field == 'items'


def test_blank_shop_is_its_own_order(app):
    from services.fishing_log.gear_service import list_gear, save_order
    save_order(_order(shop='  '))
    orders = list_gear(2026, TODAY)['orders']
    assert orders[0]['shop'] is None


def test_delete_order_removes_all_its_items_only(app):
    from models import GearPurchase
    from services.fishing_log.gear_service import delete_order, save_order
    save_order(_order())
    save_order(_order(shop='딴가게'))
    assert delete_order('2026-05-02', '가나낚시') == 2
    assert [r.shop for r in GearPurchase.query.all()] == ['딴가게', '딴가게']


@pytest.mark.parametrize('over, field', [
    ({'date': ''}, 'date'),
    ({'date': '2026/05/02'}, 'date'),
    ({'shop': '가' * 101}, 'shop'),
    ({'items': []}, 'items'),
    ({'items': [{'item': '', 'price': 1}]}, 'items'),
    ({'items': [{'item': '가' * 501}]}, 'items'),
    ({'items': [{'item': 'x', 'category': '가' * 51}]}, 'items'),
    ({'items': [{'item': 'x', 'price': '-1'}]}, 'items'),
    ({'items': [{'item': 'x', 'price': '만원'}]}, 'items'),
    ({'items': [{'item': 'x', 'gear_id': 999}]}, 'items'),
    ({'items': [{'item': 'x', 'memo': '가' * 1001}]}, 'items'),
])
def test_invalid_order_names_the_field(app, over, field):
    from services.fishing_log.gear_service import GearValidationError, save_order
    with pytest.raises(GearValidationError) as exc:
        save_order(_order(**over))
    assert exc.value.field == field


def test_category_synonyms_and_gear_link(app):
    from services.fishing_log.gear_service import save_order
    gear = _gear()
    order = save_order(_order(items=[{'item': '합사 1호', 'category': '줄', 'price': 1, 'gear_id': gear['id']}]))
    assert order['items'][0]['category'] == '라인'
    assert order['items'][0]['gear_id'] == gear['id']
    assert order['items'][0]['gear_name'] == '테스트 릴'


# ---- 목록 · 요약 ----

def test_list_groups_orders_sorted_and_summarizes(app):
    from services.fishing_log.gear_service import list_gear, save_order
    save_order(_order(date='2026-03-01', shop='가나낚시', items=[{'item': '에기A', 'category': '에기', 'price': 1000}]))
    save_order(_order(date='2026-05-02', shop='Temu', items=[{'item': '봉돌A', 'category': '봉돌', 'price': 500},
                                                             {'item': '에기B', 'category': '에기', 'price': 2000}]))
    save_order(_order(date='2025-10-01', shop='가나낚시', items=[{'item': '작년 릴', 'category': '릴', 'price': 9999}]))
    result = list_gear(2026, TODAY)
    assert [(o['date'], o['shop'], o['total']) for o in result['orders']] == [
        ('2026-05-02', 'Temu', 2500), ('2026-03-01', '가나낚시', 1000)]
    s = result['summary']
    assert (s['total'], s['count']) == (3500, 3)
    assert s['by_category'][0] == {'category': '에기', 'amount': 3000, 'count': 2}
    assert s['top_shops'][0] == {'shop': 'Temu', 'amount': 2500, 'count': 2}
    assert result['years'] == [2026, 2025]
    assert result['shops'][0] == '가나낚시'
    assert result['categories'][:3] == ['에기', '채비', '봉돌']
    assert len(list_gear(None, TODAY)['orders']) == 3


# ---- 정리 제안 ----

def test_cleanup_suggests_shop_merge_and_categories_then_applies(app):
    from models import GearPurchase
    from services.fishing_log.gear_service import apply_cleanup, cleanup_suggestions, save_order
    save_order(_order(date='2026-01-01', shop='AliExpress', items=[{'item': 'a', 'price': 1}]))
    save_order(_order(date='2026-01-02', shop='AliExpress', items=[{'item': 'b', 'price': 1}]))
    save_order(_order(date='2026-01-03', shop='ali express', items=[{'item': '스냅도래 100개', 'category': '기타', 'price': 1}]))
    save_order(_order(date='2026-01-04', shop='가나낚시', items=[{'item': '이름없는 소품', 'category': '기타', 'price': 1}]))

    sug = cleanup_suggestions()
    shop = [s for s in sug if s['kind'] == 'shop']
    cat = [s for s in sug if s['kind'] == 'category']
    assert shop == [{'kind': 'shop', 'key': 'aliexpress', 'to': 'AliExpress', 'from': ['ali express'], 'count': 1}]
    assert [(c['item'], c['to']) for c in cat] == [('스냅도래 100개', '도래')]

    changed = apply_cleanup({'shops': [{'from': ['ali express'], 'to': 'AliExpress'}],
                             'categories': [{'id': cat[0]['id'], 'category': '도래'}]})
    assert changed == 2
    assert {r.shop for r in GearPurchase.query.filter(GearPurchase.item.like('%도래%'))} == {'AliExpress'}
    assert cleanup_suggestions() == []


# ---- 내 장비 노트 ----

def test_gear_item_crud_and_unlink_on_delete(app):
    from models import GearPurchase
    from services.fishing_log.gear_service import (
        GearValidationError, delete_gear_item, list_gear, save_gear_item, save_order)
    gear = _gear()
    save_order(_order(items=[{'item': '릴 본체', 'category': '릴', 'price': 100000, 'gear_id': gear['id']}]))
    listed = list_gear(2026, TODAY)['gear_items']
    assert listed == [{'id': gear['id'], 'name': '테스트 릴', 'kind': '릴', 'memo': '메모', 'status': 'active',
                       'purchase_count': 1, 'purchase_total': 100000}]
    updated = save_gear_item(gear['id'], {'name': '바꾼 이름', 'kind': '릴', 'memo': ''})
    assert updated['name'] == '바꾼 이름' and updated['memo'] is None
    assert [p['item'] for p in updated['purchases']] == ['릴 본체']
    with pytest.raises(GearValidationError):
        save_gear_item(None, {'name': ''})
    delete_gear_item(gear['id'])
    assert GearPurchase.query.one().gear_id is None


def test_gear_status_save_validate_and_sort(app):
    from services.fishing_log.gear_service import GearValidationError, gear_items_summary, save_gear_item
    a = save_gear_item(None, {'name': '가 릴', 'kind': '릴'})
    assert a['status'] == 'active'
    save_gear_item(None, {'name': '나 로드', 'kind': '로드', 'status': 'broken'})
    save_gear_item(None, {'name': '다 릴', 'kind': '릴', 'status': 'lost'})
    save_gear_item(None, {'name': '라 릴', 'kind': '릴'})
    # 없어진 장비는 아래로, 각 묶음 안은 이름순
    assert [(g['name'], g['status']) for g in gear_items_summary()] == [
        ('가 릴', 'active'), ('라 릴', 'active'), ('나 로드', 'broken'), ('다 릴', 'lost')]
    # status 를 안 보내면 기존 값 유지
    assert save_gear_item(a['id'], {'name': '가 릴', 'kind': '릴', 'status': 'lost'})['status'] == 'lost'
    assert save_gear_item(a['id'], {'name': '가 릴', 'kind': '릴'})['status'] == 'lost'
    with pytest.raises(GearValidationError) as exc:
        save_gear_item(a['id'], {'name': '가 릴', 'status': 'gone'})
    assert exc.value.field == 'status'
