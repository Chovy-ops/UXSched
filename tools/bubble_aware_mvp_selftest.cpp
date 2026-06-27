#include <cstdlib>
#include <iostream>
#include <string>

#include "xsched/cuda/hal/hb_split/bubble_controller.h"

using xsched::cuda::hb_split::BubbleAwareController;
using xsched::cuda::hb_split::BubbleAwareState;
using xsched::cuda::hb_split::BubbleRejectReason;

namespace
{

void Check(bool value, const std::string &message)
{
    if (value) return;
    std::cerr << "FAIL: " << message << std::endl;
    std::exit(1);
}

void TestDefaultDisabled()
{
    BubbleAwareController ctrl;
    auto decision = ctrl.TryAcquireLpChildSlot();
    Check(decision.allowed, "disabled controller preserves existing LP submit behavior");
    Check(decision.reason == BubbleRejectReason::kDisabled, "disabled decision reason");
    Check(decision.snapshot.state == BubbleAwareState::kDisabled, "disabled state");
}

void TestOpenAllowsOneChild()
{
    BubbleAwareController ctrl;
    ctrl.Configure(true, 1, true);
    auto closed = ctrl.TryAcquireLpChildSlot();
    Check(!closed.allowed, "CLOSED rejects LP child");
    Check(closed.reason == BubbleRejectReason::kNoHint, "CLOSED rejects due no hint");

    ctrl.OnBubbleOpen();
    auto first = ctrl.TryAcquireLpChildSlot();
    Check(first.allowed, "OPEN allows first LP child");
    Check(first.snapshot.lp_in_flight == 1, "first LP child in flight");

    auto second = ctrl.TryAcquireLpChildSlot();
    Check(!second.allowed, "second LP child rejected while one in flight");
    Check(second.reason == BubbleRejectReason::kLpInFlight, "second reject reason");

    ctrl.OnLpChildComplete();
    auto after_complete = ctrl.TryAcquireLpChildSlot();
    Check(after_complete.allowed, "OPEN allows another child after completion");
}

void TestHpArrivalStopsLp()
{
    BubbleAwareController ctrl;
    ctrl.Configure(true, 1, true);
    ctrl.OnBubbleOpen();
    auto first = ctrl.TryAcquireLpChildSlot();
    Check(first.allowed, "precondition LP child launched");

    ctrl.OnHpEnqueue();
    auto during_hp = ctrl.TryAcquireLpChildSlot();
    Check(!during_hp.allowed, "HP_ACTIVE rejects LP child");
    Check(during_hp.reason == BubbleRejectReason::kHpPending, "HP reject reason");
    auto snapshot = ctrl.Snapshot();
    Check(snapshot.stats.hp_arrival_during_lp_child_count == 1,
          "HP arrival during LP child counted");
    Check(snapshot.stats.stop_new_lp_on_hp_count == 1, "stop-new-LP counted");

    ctrl.OnLpChildComplete();
    ctrl.OnHpQueueEmpty();
    auto no_auto_open = ctrl.TryAcquireLpChildSlot();
    Check(!no_auto_open.allowed, "HP queue empty does not imply bubble open");
    Check(no_auto_open.reason == BubbleRejectReason::kNoHint, "new open hint required");
}

void TestBubbleCloseAndFailSafe()
{
    BubbleAwareController ctrl;
    ctrl.Configure(true, 1, true);
    ctrl.OnBubbleOpen();
    ctrl.OnBubbleClose();
    auto closed = ctrl.TryAcquireLpChildSlot();
    Check(!closed.allowed, "bubble close rejects LP child");

    ctrl.OnBubbleClose();
    auto snapshot = ctrl.Snapshot();
    Check(snapshot.stats.bubble_fail_safe_count == 1,
          "repeated bubble close triggers fail-safe");
    Check(snapshot.state == BubbleAwareState::kClosed, "fail-safe closes bubble window");
}

void RunMockSmoke()
{
    BubbleAwareController ctrl;
    ctrl.Configure(true, 1, true);

    ctrl.OnBubbleOpen();
    auto first = ctrl.TryAcquireLpChildSlot();
    Check(first.allowed, "mock smoke first LP launch");
    ctrl.OnLpChildComplete();
    ctrl.OnBubbleClose();

    ctrl.OnHpEnqueue();
    ctrl.OnBubbleOpen();
    auto rejected = ctrl.TryAcquireLpChildSlot();
    Check(!rejected.allowed && rejected.reason == BubbleRejectReason::kHpPending,
          "mock smoke rejects LP while HP pending");

    ctrl.OnHpQueueEmpty();
    auto still_closed = ctrl.TryAcquireLpChildSlot();
    Check(!still_closed.allowed && still_closed.reason == BubbleRejectReason::kNoHint,
          "mock smoke requires fresh bubble after HP completes");

    ctrl.OnBubbleOpen();
    auto second = ctrl.TryAcquireLpChildSlot();
    Check(second.allowed, "mock smoke second LP launch after fresh bubble");

    auto snapshot = ctrl.Snapshot();
    Check(snapshot.stats.bubble_open_count == 3, "mock smoke open count");
    Check(snapshot.stats.bubble_close_count == 1, "mock smoke close count");
    Check(snapshot.stats.bubble_fill_success_count == 2, "mock smoke success count");
    Check(snapshot.stats.bubble_reject_hp_pending_count == 1, "mock smoke HP reject count");
    Check(snapshot.stats.max_lp_in_flight == 1, "mock smoke max LP in-flight");
}

} // namespace

int main()
{
    TestDefaultDisabled();
    TestOpenAllowsOneChild();
    TestHpArrivalStopsLp();
    TestBubbleCloseAndFailSafe();
    RunMockSmoke();
    std::cout << "bubble_aware_mvp_selftest=PASS" << std::endl;
    return 0;
}
