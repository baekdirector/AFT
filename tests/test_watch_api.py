"""
감시 등록 API 테스트 (Phase C).

로그인이 없으므로 사람을 가르는 유일한 키가 푸시 구독 endpoint 다.
그 전제가 깨지면 남의 감시를 건드릴 수 있으므로 격리를 특히 촘촘히 본다.
"""
import pytest

from db import add_boat_instance
from models import MAX_WATCHES_PER_SUBSCRIBER, Watch

DATE = '2026-09-05'
EP = 'https://push.example/aaa'
SUB_BODY = {'endpoint': EP, 'keys': {'p256dh': 'k', 'auth': 'a'}, 'label': '나'}


@pytest.fixture
def boats(app):
    with app.app_context():
        made = [
            add_boat_instance(name=f'배{i}호', url=f'https://b{i}.example/x',
                              city='인천', port='남항(인천항)', note='', is_shared=False)
            for i in range(6)
        ]
        yield [b.id for b in made]


def subscribe(client, endpoint=EP, label='나'):
    body = dict(SUB_BODY, endpoint=endpoint, label=label)
    return client.post('/api/push/subscribe', json=body)


# --- 공개키 ----------------------------------------------------------------

def test_public_key_reports_unconfigured_without_crashing(client, monkeypatch):
    """VAPID 키가 없어도 에러가 아니라 configured=false 여야 한다.

    프론트는 이걸 보고 구독 버튼을 숨긴다. 500 이 나면 화면이 깨진다.
    """
    monkeypatch.delenv('VAPID_PUBLIC_KEY', raising=False)
    rv = client.get('/api/push/public-key')

    assert rv.status_code == 200
    assert rv.get_json() == {'configured': False, 'public_key': None}


def test_public_key_is_returned_when_configured(client, monkeypatch):
    monkeypatch.setenv('VAPID_PUBLIC_KEY', 'BPublicKeyValue')
    rv = client.get('/api/push/public-key')

    assert rv.get_json() == {'configured': True, 'public_key': 'BPublicKeyValue'}


# --- 구독 ------------------------------------------------------------------

def test_subscribe_creates_subscriber(client):
    rv = subscribe(client)

    assert rv.status_code == 200
    body = rv.get_json()
    assert body['limit'] == MAX_WATCHES_PER_SUBSCRIBER
    assert body['watches'] == []


def test_subscribe_twice_does_not_duplicate(client):
    first = subscribe(client).get_json()
    second = subscribe(client).get_json()

    assert first['subscriber_id'] == second['subscriber_id']


def test_subscribe_rejects_incomplete_body(client):
    rv = client.post('/api/push/subscribe', json={'endpoint': EP})
    assert rv.status_code == 400


# --- 감시 등록 -------------------------------------------------------------

def test_create_watch(client, boats):
    subscribe(client)
    rv = client.post('/api/watches', json={
        'endpoint': EP, 'boat_id': boats[0],
        'ship_name': '1호', 'target_date': DATE})

    assert rv.status_code == 200
    body = rv.get_json()
    assert body['watch']['ship_name'] == '1호'
    assert len(body['watches']) == 1


def test_create_watch_without_subscription_is_rejected(client, boats):
    """구독 없이 체크박스를 켜면 누구에게 보낼지 알 수 없다."""
    rv = client.post('/api/watches', json={
        'endpoint': EP, 'boat_id': boats[0],
        'ship_name': '1호', 'target_date': DATE})

    assert rv.status_code == 409
    assert '구독' in rv.get_json()['error']


def test_create_watch_accepts_boat_name_instead_of_id(client, boats):
    """프론트가 표에서 배 이름만 들고 있어도 등록된다."""
    subscribe(client)
    rv = client.post('/api/watches', json={
        'endpoint': EP, 'boat_name': '배0호',
        'ship_name': '1호', 'target_date': DATE})

    assert rv.status_code == 200
    assert rv.get_json()['watch']['boat_id'] == boats[0]


def test_exceeding_limit_returns_409_with_message(client, boats):
    subscribe(client)
    for i in range(MAX_WATCHES_PER_SUBSCRIBER):
        client.post('/api/watches', json={
            'endpoint': EP, 'boat_id': boats[i],
            'ship_name': f'{i}호', 'target_date': DATE})

    rv = client.post('/api/watches', json={
        'endpoint': EP, 'boat_id': boats[5],
        'ship_name': '한척더', 'target_date': DATE})

    assert rv.status_code == 409
    body = rv.get_json()
    assert body['limit'] == 5 and '5척' in body['error']


def test_limit_counts_across_all_dates_not_per_date(client, boats):
    """상한은 날짜별이 아니라 전체다.

    실제로 겪은 문제: 9월 4일에 2척, 10월 3일에 3척을 걸어둔 상태에서 화면은
    '3/5' 로 보였다. 프론트가 조회 중인 날짜만 세고 있었기 때문이다. 서버는
    이미 5척이라 4번째 등록을 거절했고, 사용자는 왜 막히는지 알 수 없었다.
    세는 기준이 서버와 화면에서 갈리지 않도록 서버 규칙을 여기에 고정한다.
    """
    subscribe(client)
    for i in range(2):
        client.post('/api/watches', json={
            'endpoint': EP, 'boat_id': boats[i],
            'ship_name': f'{i}호', 'target_date': '2026-09-04'})
    for i in range(2, 5):
        client.post('/api/watches', json={
            'endpoint': EP, 'boat_id': boats[i],
            'ship_name': f'{i}호', 'target_date': '2026-10-03'})

    rv = client.post('/api/watches', json={
        'endpoint': EP, 'boat_id': boats[5],
        'ship_name': '6호', 'target_date': '2026-10-03'})

    assert rv.status_code == 409, '날짜가 달라도 상한은 합산된다'

    # 화면이 카운트를 맞게 셀 수 있도록 응답에는 모든 날짜의 감시가 들어있어야 한다
    listed = client.get('/api/watches', query_string={'endpoint': EP}).get_json()['watches']
    assert len(listed) == 5
    assert {w['target_date'] for w in listed} == {'2026-09-04', '2026-10-03'}


def test_watch_list_carries_fields_needed_to_unregister(client, boats):
    """다른 날짜의 감시를 목록에서 바로 해제하려면 그 세 값이 필요하다."""
    subscribe(client)
    client.post('/api/watches', json={
        'endpoint': EP, 'boat_id': boats[0], 'ship_name': '1호', 'target_date': DATE})

    w = client.get('/api/watches', query_string={'endpoint': EP}).get_json()['watches'][0]

    assert w['boat_id'] == boats[0]
    assert w['boat_name'] == '배0호'
    assert w['ship_name'] == '1호'
    assert w['target_date'] == DATE


def test_unknown_boat_returns_400(client, boats):
    subscribe(client)
    rv = client.post('/api/watches', json={
        'endpoint': EP, 'boat_name': '없는배',
        'ship_name': '1호', 'target_date': DATE})

    assert rv.status_code == 400


# --- 조회 / 해제 -----------------------------------------------------------

def test_get_watches_restores_checkbox_state(client, boats):
    """화면을 새로 열면 이 목록으로 체크박스를 복원한다."""
    subscribe(client)
    client.post('/api/watches', json={
        'endpoint': EP, 'boat_id': boats[0], 'ship_name': '1호', 'target_date': DATE})

    rv = client.get('/api/watches', query_string={'endpoint': EP})

    assert rv.status_code == 200
    assert [w['ship_name'] for w in rv.get_json()['watches']] == ['1호']


def test_get_watches_for_unknown_endpoint_is_empty_not_error(client):
    """구독 전인 브라우저가 화면을 열어도 200 이어야 한다."""
    rv = client.get('/api/watches', query_string={'endpoint': 'https://nope/x'})

    assert rv.status_code == 200
    assert rv.get_json()['watches'] == []


def test_delete_watch(client, boats):
    subscribe(client)
    client.post('/api/watches', json={
        'endpoint': EP, 'boat_id': boats[0], 'ship_name': '1호', 'target_date': DATE})

    rv = client.delete('/api/watches', json={
        'endpoint': EP, 'boat_id': boats[0], 'ship_name': '1호', 'target_date': DATE})

    assert rv.status_code == 200
    assert rv.get_json()['removed'] is True
    assert rv.get_json()['watches'] == []


def test_delete_nonexistent_watch_reports_false(client, boats):
    subscribe(client)
    rv = client.delete('/api/watches', json={
        'endpoint': EP, 'boat_id': boats[0], 'ship_name': '없음', 'target_date': DATE})

    assert rv.status_code == 200 and rv.get_json()['removed'] is False


# --- 사람 간 격리 ----------------------------------------------------------

def test_one_browser_cannot_delete_anothers_watch(client, boats):
    """endpoint 가 사람을 가르는 유일한 키다. 남의 감시를 못 지워야 한다."""
    other_ep = 'https://push.example/bbb'
    subscribe(client)
    subscribe(client, endpoint=other_ep, label='친구')

    client.post('/api/watches', json={
        'endpoint': EP, 'boat_id': boats[0], 'ship_name': '1호', 'target_date': DATE})

    rv = client.delete('/api/watches', json={
        'endpoint': other_ep, 'boat_id': boats[0],
        'ship_name': '1호', 'target_date': DATE})

    assert rv.get_json()['removed'] is False
    assert Watch.query.filter_by(active=True).count() == 1


def test_each_browser_sees_only_its_own_watches(client, boats):
    other_ep = 'https://push.example/bbb'
    subscribe(client)
    subscribe(client, endpoint=other_ep, label='친구')

    client.post('/api/watches', json={
        'endpoint': EP, 'boat_id': boats[0], 'ship_name': '내배', 'target_date': DATE})
    client.post('/api/watches', json={
        'endpoint': other_ep, 'boat_id': boats[1], 'ship_name': '친구배', 'target_date': DATE})

    mine = client.get('/api/watches', query_string={'endpoint': EP}).get_json()
    theirs = client.get('/api/watches', query_string={'endpoint': other_ep}).get_json()

    assert [w['ship_name'] for w in mine['watches']] == ['내배']
    assert [w['ship_name'] for w in theirs['watches']] == ['친구배']
