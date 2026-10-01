"""장비 구매 조회·저장·정리 제안·내 장비 노트 - docs/superpowers/specs/2026-10-01-fishing-log-gear-design.md §5.

"주문" 테이블은 없다: 같은 purchase_date + 같은 shop(빈 값 포함) 품목들을 한 주문으로 묶는다.
주문 저장은 한 트랜잭션으로 추가·수정·삭제를 함께 처리한다.
"""
import re
from collections import Counter
from datetime import date

from db import db
from models import GEAR_STATUSES, GearItem, GearPurchase
from services.fishing_log.excel_seed import normalize_category

DEFAULT_CATEGORIES = ['에기', '채비', '봉돌', '도래', '라인', '로드', '릴', '의류', '기타']
TOP_SHOPS = 5

# 정리 제안: '기타' 품목 이름에 들어 있으면 이 카테고리를 제안한다(먼저 맞는 것).
# '레인'은 에기 색상 '레인보우'와 겹쳐서 '레인코트'로만 본다.
CATEGORY_KEYWORDS = [
    ('봉돌', ['봉돌']),
    ('도래', ['도래', '스위블', '스냅']),
    ('라인', ['합사', '라인', '원줄', '목줄']),
    ('채비', ['채비', '천평', '바늘', '훅', '슬리브']),
    ('에기', ['에기']),
    ('의류', ['장갑', '모자', '조끼', '우의', '레인코트']),
    ('로드', ['로드', '낚시대']),
    ('릴', ['릴']),
]


class GearValidationError(ValueError):
    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


class GearNotFound(LookupError):
    pass


# ---- 입력 정리 ----

def _text(value, field, limit, label, required=False):
    text = str(value or '').strip()
    if required and not text:
        raise GearValidationError(field, f'{label}을(를) 입력해 주세요.')
    if len(text) > limit:
        raise GearValidationError(field, f'{label}은(는) {limit}자 이하로 입력해 주세요.')
    return text or None


def _date(value, field='date'):
    text = str(value or '').strip()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        raise GearValidationError(field, '날짜를 YYYY-MM-DD 형식으로 입력해 주세요.')
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise GearValidationError(field, '올바른 날짜가 아닙니다.') from None


def _price(value):
    if value is None or str(value).strip() == '':
        return None
    if isinstance(value, bool):
        raise GearValidationError('items', '가격은 숫자로 입력해 주세요.')
    if isinstance(value, int):
        number = value
    else:
        text = str(value).strip().replace(',', '')
        if not re.fullmatch(r'\d+', text):
            raise GearValidationError('items', '가격은 0 이상의 숫자로 입력해 주세요.')
        number = int(text)
    if number < 0:
        raise GearValidationError('items', '가격은 0 이상의 숫자로 입력해 주세요.')
    return number


def _clean_item(row):
    if not isinstance(row, dict):
        raise GearValidationError('items', '품목 형식이 올바르지 않습니다.')
    gear_id = row.get('gear_id') or None
    if gear_id is not None:
        try:
            gear_id = int(gear_id)
        except (TypeError, ValueError):
            raise GearValidationError('items', '내 장비 값이 올바르지 않습니다.') from None
        if db.session.get(GearItem, gear_id) is None:
            raise GearValidationError('items', '없는 장비입니다.')
    category = _text(row.get('category'), 'items', 50, '카테고리')
    return {
        'id': int(row['id']) if row.get('id') else None,
        'item': _text(row.get('item'), 'items', 500, '품목명', required=True),
        'category': normalize_category(category),
        'price': _price(row.get('price')),
        'gear_id': gear_id,
        'memo': _text(row.get('memo'), 'items', 1000, '메모'),
    }


def _shop(value):
    return _text(value, 'shop', 100, '구매처')


# ---- 직렬화 ----

def _item_dict(p):
    return {'id': p.id, 'item': p.item, 'category': p.category, 'price': p.price,
            'gear_id': p.gear_id, 'gear_name': p.gear.name if p.gear else None, 'memo': p.memo}


def _order_dict(purchase_date, shop, items):
    items = sorted(items, key=lambda p: p.id)
    return {'date': purchase_date.isoformat(), 'shop': shop,
            'total': sum(p.price or 0 for p in items), 'items': [_item_dict(p) for p in items]}


def _order_rows(purchase_date, shop):
    query = GearPurchase.query.filter(GearPurchase.purchase_date == purchase_date)
    query = query.filter(GearPurchase.shop.is_(None)) if shop is None else query.filter(GearPurchase.shop == shop)
    return query.all()


# ---- 주문 ----

def save_order(data):
    """새 주문(original 없음) 또는 기존 주문 수정. 저장된 주문(새 키 기준)을 돌려준다."""
    purchase_date = _date(data.get('date'))
    shop = _shop(data.get('shop'))
    rows = data.get('items')
    if not isinstance(rows, list) or not rows:
        raise GearValidationError('items', '품목을 1개 이상 입력해 주세요.')
    items = [_clean_item(r) for r in rows]

    existing = {}
    original = data.get('original')
    if original:
        existing = {p.id: p for p in _order_rows(_date(original.get('date')), _shop(original.get('shop')))}
    for it in items:
        if it['id'] is not None and it['id'] not in existing:
            raise GearValidationError('items', '다른 주문의 품목은 여기서 고칠 수 없습니다.')

    try:
        kept = set()
        for it in items:
            row = existing.get(it['id']) if it['id'] else None
            if row is None:
                row = GearPurchase()
                db.session.add(row)
            else:
                kept.add(row.id)
            row.purchase_date, row.shop = purchase_date, shop
            for field in ('item', 'category', 'price', 'gear_id', 'memo'):
                setattr(row, field, it[field])
        for pid, row in existing.items():
            if pid not in kept:
                db.session.delete(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return _order_dict(purchase_date, shop, _order_rows(purchase_date, shop))


def delete_order(purchase_date, shop):
    rows = _order_rows(_date(purchase_date), _shop(shop))
    for row in rows:
        db.session.delete(row)
    db.session.commit()
    return len(rows)


# ---- 목록 ----

def gear_items_summary():
    stats = {}
    for gear_id, price in db.session.query(GearPurchase.gear_id, GearPurchase.price).filter(GearPurchase.gear_id.isnot(None)):
        count, total = stats.get(gear_id, (0, 0))
        stats[gear_id] = (count + 1, total + (price or 0))
    # 부러지거나 잃어버린 장비는 목록 아래로(각 묶음 안은 이름순)
    items = sorted(GearItem.query.all(), key=lambda g: ((g.status or 'active') != 'active', g.name))
    return [{'id': g.id, 'name': g.name, 'kind': g.kind, 'memo': g.memo, 'status': g.status or 'active',
             'purchase_count': stats.get(g.id, (0, 0))[0], 'purchase_total': stats.get(g.id, (0, 0))[1]}
            for g in items]


def list_gear(year, today):
    """year=None 이면 전체. 주문은 날짜 내림차순(같은 날은 구매처 이름순)."""
    query = GearPurchase.query
    if year is not None:
        query = query.filter(GearPurchase.purchase_date >= date(year, 1, 1),
                             GearPurchase.purchase_date <= date(year, 12, 31))
    rows = query.all()
    groups = {}
    for p in rows:
        groups.setdefault((p.purchase_date, p.shop), []).append(p)
    keys = sorted(groups, key=lambda k: (-k[0].toordinal(), k[1] or ''))

    by_cat, by_shop = {}, {}
    for p in rows:
        amount, count = by_cat.get(p.category, (0, 0))
        by_cat[p.category] = (amount + (p.price or 0), count + 1)
        if p.shop:
            amount, count = by_shop.get(p.shop, (0, 0))
            by_shop[p.shop] = (amount + (p.price or 0), count + 1)

    all_rows = db.session.query(GearPurchase.purchase_date, GearPurchase.shop, GearPurchase.category).all()
    shops = [s for s, _ in Counter(s for _, s, _ in all_rows if s).most_common()]
    used = [c for c, _ in Counter(c for _, _, c in all_rows if c).most_common()]
    return {
        'orders': [_order_dict(k[0], k[1], groups[k]) for k in keys],
        'years': sorted({d.year for d, _, _ in all_rows} | {today.year}, reverse=True),
        'shops': shops,
        'categories': DEFAULT_CATEGORIES + [c for c in used if c not in DEFAULT_CATEGORIES],
        'summary': {
            'total': sum(p.price or 0 for p in rows),
            'count': len(rows),
            'by_category': [{'category': c, 'amount': a, 'count': n}
                            for c, (a, n) in sorted(by_cat.items(), key=lambda kv: (-kv[1][0], kv[0]))],
            'top_shops': [{'shop': s, 'amount': a, 'count': n}
                          for s, (a, n) in sorted(by_shop.items(), key=lambda kv: (-kv[1][0], kv[0]))[:TOP_SHOPS]],
        },
        'gear_items': gear_items_summary(),
    }


# ---- 정리 제안 ----

def _shop_key(shop):
    return re.sub(r'\s+', '', shop).lower()


def _suggest_category(item):
    for category, words in CATEGORY_KEYWORDS:
        if any(w in item for w in words):
            return category
    return None


def cleanup_suggestions():
    rows = GearPurchase.query.order_by(GearPurchase.id).all()
    spellings = {}
    for p in rows:
        if p.shop:
            spellings.setdefault(_shop_key(p.shop), []).append(p.shop)
    result = []
    for key, names in spellings.items():
        counts = Counter(names)
        if len(counts) < 2:
            continue
        top = max(counts.items(), key=lambda kv: (kv[1], -names.index(kv[0])))[0]
        others = sorted(n for n in counts if n != top)
        result.append({'kind': 'shop', 'key': key, 'to': top, 'from': others,
                       'count': sum(counts[n] for n in others)})
    for p in rows:
        if p.category == '기타':
            to = _suggest_category(p.item)
            if to:
                result.append({'kind': 'category', 'id': p.id, 'item': p.item, 'to': to})
    return result


def apply_cleanup(data):
    changed = 0
    try:
        for merge in data.get('shops') or []:
            to = _text(merge.get('to'), 'shops', 100, '구매처', required=True)
            names = [n for n in (merge.get('from') or []) if n and n != to]
            if names:
                changed += GearPurchase.query.filter(GearPurchase.shop.in_(names)).update(
                    {GearPurchase.shop: to}, synchronize_session=False)
        for change in data.get('categories') or []:
            row = db.session.get(GearPurchase, int(change.get('id') or 0))
            category = _text(change.get('category'), 'categories', 50, '카테고리', required=True)
            if row is not None and row.category != category:
                row.category = category
                changed += 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return changed


# ---- 내 장비 노트 ----

def gear_item_dict(g):
    purchases = sorted(g.purchases, key=lambda p: (p.purchase_date, p.id), reverse=True)
    return {'id': g.id, 'name': g.name, 'kind': g.kind, 'memo': g.memo, 'status': g.status or 'active',
            'purchase_count': len(purchases), 'purchase_total': sum(p.price or 0 for p in purchases),
            'purchases': [{'id': p.id, 'date': p.purchase_date.isoformat(), 'shop': p.shop,
                           'item': p.item, 'price': p.price} for p in purchases]}


def get_gear_item(gear_id):
    return db.session.get(GearItem, gear_id)


def save_gear_item(gear_id, data):
    name = _text(data.get('name'), 'name', 200, '장비 이름', required=True)
    kind = _text(data.get('kind'), 'kind', 50, '종류')
    memo = _text(data.get('memo'), 'memo', 2000, '메모')
    status = data.get('status')
    if status is not None and status not in GEAR_STATUSES:
        raise GearValidationError('status', '장비 상태를 다시 골라 주세요.')
    if gear_id is None:
        gear = GearItem()
        db.session.add(gear)
    else:
        gear = get_gear_item(gear_id)
        if gear is None:
            raise GearNotFound(gear_id)
    gear.name, gear.kind, gear.memo = name, kind, memo
    if status is not None:
        gear.status = status
    elif gear.status is None:
        gear.status = 'active'
    db.session.commit()
    return gear_item_dict(gear)


def delete_gear_item(gear_id):
    gear = get_gear_item(gear_id)
    if gear is None:
        raise GearNotFound(gear_id)
    db.session.delete(gear)
    db.session.commit()
