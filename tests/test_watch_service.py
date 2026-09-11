"""
감시 등록 규칙 테스트 (Phase C).

핵심은 MAX_WATCHES_PER_SUBSCRIBER 상한이다. 이 숫자가 곧 스케줄러 수집량이라
느슨하면 수집이 터진다.
"""
import pytest

from db import add_boat_instance
from models import MAX_WATCHES_PER_SUBSCRIBER, Subscriber, Watch
from services.watch_service import (
    WatchLimitExceeded,
    active_watch_targets,
    add_watch,
    count_watches,
    deactivate_all_watches,
    list_watches,
    purge_past_watches,
    remove_watch,
    upsert_subscriber,
    watches_for,
)

DATE = '2026-09-05'


@pytest.fixture
def ctx(app):
    """배 (상한+1)척과 구독자 하나를 만들어 둔다 - 상한을 다 채우고도
    '한 척 더' 시도할 여유가 있어야 한다."""
    with app.app_context():
        boats = [
            add_boat_instance(name=f'배{i}호', url=f'https://b{i}.example/x',
                              city='인천', port='남항(인천항)', note='', is_shared=False)
            for i in range(MAX_WATCHES_PER_SUBSCRIBER + 1)
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
            add_watch(sub, boat_ids[MAX_WATCHES_PER_SUBSCRIBER], '한척더', DATE)

        assert exc.value.limit == MAX_WATCHES_PER_SUBSCRIBER
        assert count_watches(sub) == MAX_WATCHES_PER_SUBSCRIBER


def test_removing_frees_a_slot(app, ctx):
    sub, boat_ids = ctx
    with app.app_context():
        for i in range(MAX_WATCHES_PER_SUBSCRIBER):
            add_watch(sub, boat_ids[i], f'선박{i}', DATE)

        assert remove_watch(sub, boat_ids[0], '선박0', DATE) is True
        add_watch(sub, boat_ids[MAX_WATCHES_PER_SUBSCRIBER], '새배', DATE)   # 예외가 나면 안 된다

        assert count_watches(sub) == MAX_WATCHES_PER_SUBSCRIBER


def test_limit_is_per_subscriber_not_global(app, ctx):
    sub, boat_ids = ctx
    with app.app_context():
        other = upsert_subscriber('https://push.example/bbb', 'k', 'a', '친구')
        for i in range(MAX_WATCHES_PER_SUBSCRIBER):
            add_watch(sub, boat_ids[i], f'선박{i}', DATE)

        add_watch(other, boat_ids[0], '선박0', DATE)  # 다른 사람은 영향 없음

        assert count_watches(sub) == MAX_WATCHES_PER_SUBSCRIBER and count_watches(other) == 1


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
        for i in range(1, MAX_WATCHES_PER_SUBSCRIBER + 1):
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


# --- 알림 끄기(전체 해제) ----------------------------------------------------

def test_deactivate_all_watches_turns_off_every_active_watch(app, ctx):
    """알림을 끄면 감시도 모두 해제한다(사용자 결정)."""
    sub, boat_ids = ctx
    with app.app_context():
        add_watch(sub, boat_ids[0], '1호', DATE)
        add_watch(sub, boat_ids[1], '2호', DATE)

        deactivated = deactivate_all_watches(sub)

        assert deactivated == 2
        assert count_watches(sub) == 0
        assert list_watches(sub) == []


def test_deactivate_all_watches_does_not_touch_other_subscribers(app, ctx):
    sub, boat_ids = ctx
    with app.app_context():
        other = upsert_subscriber('https://push.example/bbb', 'k', 'a', '친구')
        add_watch(sub, boat_ids[0], '1호', DATE)
        add_watch(other, boat_ids[0], '1호', DATE)

        deactivate_all_watches(sub)

        assert count_watches(sub) == 0
        assert count_watches(other) == 1


def test_deactivate_all_watches_is_soft_delete_not_hard_delete(app, ctx):
    """remove_watch 와 같은 이유 - 발송 이력이 Watch 를 참조하므로 하드
    삭제하면 껐다 켜는 것만으로 같은 알림을 다시 받게 된다."""
    sub, boat_ids = ctx
    with app.app_context():
        add_watch(sub, boat_ids[0], '1호', DATE)

        deactivate_all_watches(sub)

        row = Watch.query.filter_by(subscriber_id=sub.id, boat_id=boat_ids[0],
                                    ship_name='1호', target_date=DATE).one()
        assert row.active is False


def test_deactivate_all_watches_on_subscriber_with_no_watches_is_a_noop(app):
    with app.app_context():
        sub = upsert_subscriber('https://push.example/ccc', 'k', 'a', '나')
        assert deactivate_all_watches(sub) == 0


def test_purge_past_watches_hard_deletes_expired_rows(app, ctx):
    """지난 날짜 감시는 비활성 처리가 아니라 완전히 지워야 한다(사용자 결정:
    "화면에서도 자동으로 알림해제 되면, 불필요한 알림은 없어지는게 맞다").
    remove_watch/deactivate_all_watches 와 달리 하드 삭제가 안전한 이유는
    지난 날짜라 다시 감시할 일이 없어 Notification dedup 근거가 필요 없기
    때문이다."""
    sub, boat_ids = ctx
    with app.app_context():
        add_watch(sub, boat_ids[0], '1호', '2020-01-01')  # 지난 날짜
        add_watch(sub, boat_ids[1], '2호', DATE)           # 미래

        purged = purge_past_watches(today='2026-01-01')

        assert purged == 1
        remaining = Watch.query.all()
        assert len(remaining) == 1 and remaining[0].ship_name == '2호'


def test_purge_past_watches_also_removes_already_deactivated_rows(app, ctx):
    """수동으로 껐지만(active=False) 행이 남아있던 지난 날짜 감시도
    같이 정리된다 - 예전엔 이런 행이 영원히 비활성 상태로 쌓였다."""
    sub, boat_ids = ctx
    with app.app_context():
        add_watch(sub, boat_ids[0], '1호', '2020-01-01')
        remove_watch(sub, boat_ids[0], '1호', '2020-01-01')

        purged = purge_past_watches(today='2026-01-01')

        assert purged == 1
        assert Watch.query.count() == 0


def test_purge_past_watches_cascades_notification_history(app, ctx):
    """지운 감시를 참조하던 발송 이력(Notification)도 같이 사라져야
    한다(ondelete=CASCADE) - 다시 쓰일 일 없는 dedup 근거를 영원히 남겨둘
    이유가 없다."""
    from db import db
    from models import Notification

    sub, boat_ids = ctx
    with app.app_context():
        watch = add_watch(sub, boat_ids[0], '1호', '2020-01-01')
        db.session.add(Notification(watch_id=watch.id, dedup_key='k1', result='sent'))
        db.session.commit()

        purge_past_watches(today='2026-01-01')

        assert Notification.query.count() == 0


def test_purge_past_watches_leaves_future_watches_untouched(app, ctx):
    sub, boat_ids = ctx
    with app.app_context():
        add_watch(sub, boat_ids[0], '1호', DATE)
        assert purge_past_watches(today='2020-01-01') == 0
        assert Watch.query.count() == 1
