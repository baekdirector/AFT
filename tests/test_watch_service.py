"""
감시 등록 규칙 테스트 (Phase C).

핵심은 5척 상한이다. 이 숫자가 곧 스케줄러 수집량이라 느슨하면 수집이 터진다.
"""
import pytest

from db import add_boat_instance
from models import MAX_WATCHES_PER_SUBSCRIBER, Subscriber, Watch
from services.watch_service import (
    WatchLimitExceeded,
    active_watch_targets,
    add_watch,
    count_watches,
    list_watches,
    remove_watch,
    upsert_subscriber,
    watches_for,
)

DATE = '2026-09-05'


@pytest.fixture
def ctx(app):
    """배 6척과 구독자 하나를 만들어 둔다."""
    with app.app_context():
        boats = [
            add_boat_instance(name=f'배{i}호', url=f'https://b{i}.example/x',
                              city='인천', port='남항(인천항)', note='', is_shared=False)
            for i in range(6)
        ]
        sub = upsert_subscriber('https://push.example/aaa', 'p256dh-aaa', 'auth-aaa', '나')
        yield sub, [b.id for b in boats]


# --- 구독자 ----------------------------------------------------------------

def test_upsert_subscriber_creates_then_updates_same_endpoint(app):
    with app.app_context():
        a = upsert_subscriber('https://push.example/x', 'k1', 'a1', '나')
        b = upsert_subscriber('https://push.example/x', 'k2', 'a2')

        assert a.id == b.id, '같은 endpoint 면 새 행을 만들지 않는다'
        assert Subscriber.query.count() == 1
        assert (b.p256dh, b.auth) == ('k2', 'a2'), '갱신된 키가 저장돼야 한다'
        assert b.label == '나', '라벨을 안 보내면 기존 값을 지우지 않는다'


def test_upsert_subscriber_rejects_incomplete_subscription(app):
    with app.app_context():
        with pytest.raises(ValueError):
            upsert_subscriber('', 'k', 'a')


# --- 상한 ------------------------------------------------------------------

def test_can_register_up_to_the_limit(app, ctx):
    sub, boat_ids = ctx
    with app.app_context():
        for i in range(MAX_WATCHES_PER_SUBSCRIBER):
            add_watch(sub, boat_ids[i], f'선박{i}', DATE)
        assert count_watches(sub) == MAX_WATCHES_PER_SUBSCRIBER


def test_exceeding_the_limit_is_rejected(app, ctx):
    sub, boat_ids = ctx
    with app.app_context():
        for i in range(MAX_WATCHES_PER_SUBSCRIBER):
            add_watch(sub, boat_ids[i], f'선박{i}', DATE)

        with pytest.raises(WatchLimitExceeded) as exc:
            add_watch(sub, boat_ids[5], '한척더', DATE)

        assert exc.value.limit == 5
        assert count_watches(sub) == 5


def test_removing_frees_a_slot(app, ctx):
    sub, boat_ids = ctx
    with app.app_context():
        for i in range(MAX_WATCHES_PER_SUBSCRIBER):
            add_watch(sub, boat_ids[i], f'선박{i}', DATE)

        assert remove_watch(sub, boat_ids[0], '선박0', DATE) is True
        add_watch(sub, boat_ids[5], '새배', DATE)   # 예외가 나면 안 된다

        assert count_watches(sub) == 5


def test_limit_is_per_subscriber_not_global(app, ctx):
    sub, boat_ids = ctx
    with app.app_context():
        other = upsert_subscriber('https://push.example/bbb', 'k', 'a', '친구')
        for i in range(MAX_WATCHES_PER_SUBSCRIBER):
            add_watch(sub, boat_ids[i], f'선박{i}', DATE)

        add_watch(other, boat_ids[0], '선박0', DATE)  # 다른 사람은 영향 없음

        assert count_watches(sub) == 5 and count_watches(other) == 1


# --- 중복 등록 -------------------------------------------------------------

def test_registering_same_target_twice_is_idempotent(app, ctx):
    sub, boat_ids = ctx
    with app.app_context():
        first = add_watch(sub, boat_ids[0], '선박0', DATE)
        second = add_watch(sub, boat_ids[0], '선박0', DATE)

        assert first.id == second.id
        assert count_watches(sub) == 1, '같은 대상은 슬롯을 두 번 먹지 않는다'


def test_toggling_off_and_on_reuses_the_row(app, ctx):
    sub, boat_ids = ctx
    with app.app_context():
        w = add_watch(sub, boat_ids[0], '선박0', DATE)
        remove_watch(sub, boat_ids[0], '선박0', DATE)
        again = add_watch(sub, boat_ids[0], '선박0', DATE)

        assert again.id == w.id, '행을 지우지 않아야 발송 이력이 살아남는다'
        assert Watch.query.count() == 1


def test_reactivating_still_respects_the_limit(app, ctx):
    """껐던 것을 되살리는 것도 상한을 넘으면 안 된다."""
    sub, boat_ids = ctx
    with app.app_context():
        w0 = add_watch(sub, boat_ids[0], '선박0', DATE)
        remove_watch(sub, boat_ids[0], '선박0', DATE)
        for i in range(1, 6):
            add_watch(sub, boat_ids[i], f'선박{i}', DATE)

        with pytest.raises(WatchLimitExceeded):
            add_watch(sub, boat_ids[0], '선박0', DATE)


def test_removing_a_nonexistent_watch_reports_false(app, ctx):
    sub, boat_ids = ctx
    with app.app_context():
        assert remove_watch(sub, boat_ids[0], '없는배', DATE) is False


def test_unknown_boat_is_rejected(app, ctx):
    sub, _ = ctx
    with app.app_context():
        with pytest.raises(ValueError):
            add_watch(sub, 99999, '선박', DATE)


# --- 스케줄러가 쓰는 조회 ---------------------------------------------------

def test_active_watch_targets_dedupes_across_subscribers(app, ctx):
    """여러 사람이 같은 배·날짜를 보면 수집은 한 번만 한다."""
    sub, boat_ids = ctx
    with app.app_context():
        other = upsert_subscriber('https://push.example/bbb', 'k', 'a')
        add_watch(sub, boat_ids[0], '1호', DATE)
        add_watch(other, boat_ids[0], '2호', DATE)      # 같은 배·날짜, 다른 선박
        add_watch(sub, boat_ids[1], '3호', '2026-09-06')

        targets = active_watch_targets()

        assert targets == [(boat_ids[0], DATE), (boat_ids[1], '2026-09-06')]


def test_active_watch_targets_excludes_inactive(app, ctx):
    sub, boat_ids = ctx
    with app.app_context():
        add_watch(sub, boat_ids[0], '1호', DATE)
        remove_watch(sub, boat_ids[0], '1호', DATE)

        assert active_watch_targets() == []


def test_watches_for_finds_every_subscriber_of_a_target(app, ctx):
    """한 전환에 여러 사람이 걸려 있으면 전원에게 보내야 한다."""
    sub, boat_ids = ctx
    with app.app_context():
        other = upsert_subscriber('https://push.example/bbb', 'k', 'a')
        add_watch(sub, boat_ids[0], '1호', DATE)
        add_watch(other, boat_ids[0], '1호', DATE)
        add_watch(sub, boat_ids[0], '2호', DATE)

        found = watches_for(boat_ids[0], DATE, '1호')

        assert len(found) == 2
        assert {w.subscriber_id for w in found} == {sub.id, other.id}


def test_list_watches_is_ordered(app, ctx):
    sub, boat_ids = ctx
    with app.app_context():
        add_watch(sub, boat_ids[0], '나호', '2026-09-06')
        add_watch(sub, boat_ids[1], '가호', '2026-09-05')

        assert [w.ship_name for w in list_watches(sub)] == ['가호', '나호']
