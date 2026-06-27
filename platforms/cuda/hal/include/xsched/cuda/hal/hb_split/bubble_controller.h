#pragma once

#include <algorithm>
#include <cstdint>
#include <mutex>

namespace xsched::cuda::hb_split
{

enum class BubbleAwareState : uint8_t
{
    kDisabled,
    kClosed,
    kOpen,
    kHpActive,
};

enum class BubbleRejectReason : uint8_t
{
    kNone,
    kDisabled,
    kNoHint,
    kHpPending,
    kLpInFlight,
    kFailSafe,
};

struct BubbleAwareStats
{
    uint64_t bubble_open_count = 0;
    uint64_t bubble_close_count = 0;
    uint64_t bubble_fill_attempt_count = 0;
    uint64_t bubble_fill_success_count = 0;
    uint64_t bubble_fill_rejected_count = 0;
    uint64_t bubble_reject_hp_pending_count = 0;
    uint64_t bubble_reject_no_hint_count = 0;
    uint64_t bubble_reject_lp_in_flight_count = 0;
    uint64_t lp_child_launched_in_bubble_count = 0;
    uint64_t hp_arrival_during_lp_child_count = 0;
    uint64_t stop_new_lp_on_hp_count = 0;
    uint64_t max_lp_in_flight = 0;
    uint64_t bubble_fail_safe_count = 0;
};

struct BubbleAwareSnapshot
{
    bool enabled = false;
    bool fail_safe = true;
    uint32_t max_in_flight_limit = 1;
    BubbleAwareState state = BubbleAwareState::kDisabled;
    uint32_t hp_pending = 0;
    uint32_t lp_in_flight = 0;
    BubbleAwareStats stats;
};

struct BubbleSubmitDecision
{
    bool allowed = false;
    BubbleRejectReason reason = BubbleRejectReason::kNone;
    BubbleAwareSnapshot snapshot;
};

class BubbleAwareController
{
public:
    void Configure(bool enabled, uint32_t max_in_flight, bool fail_safe)
    {
        std::lock_guard<std::mutex> lock(mu_);
        enabled_ = enabled;
        fail_safe_ = fail_safe;
        max_in_flight_limit_ = std::max<uint32_t>(1, max_in_flight);
        if (max_in_flight_limit_ > 1) max_in_flight_limit_ = 1;
        state_ = enabled_ ? BubbleAwareState::kClosed : BubbleAwareState::kDisabled;
        hp_pending_ = 0;
        lp_in_flight_ = 0;
    }

    BubbleSubmitDecision TryAcquireLpChildSlot()
    {
        std::lock_guard<std::mutex> lock(mu_);
        BubbleSubmitDecision decision;

        if (!enabled_) {
            decision.allowed = true;
            decision.reason = BubbleRejectReason::kDisabled;
            decision.snapshot = SnapshotLocked();
            return decision;
        }

        ++stats_.bubble_fill_attempt_count;

        if (state_ == BubbleAwareState::kHpActive || hp_pending_ > 0) {
            ++stats_.bubble_fill_rejected_count;
            ++stats_.bubble_reject_hp_pending_count;
            decision.reason = BubbleRejectReason::kHpPending;
            decision.snapshot = SnapshotLocked();
            return decision;
        }

        if (state_ != BubbleAwareState::kOpen) {
            ++stats_.bubble_fill_rejected_count;
            ++stats_.bubble_reject_no_hint_count;
            decision.reason = BubbleRejectReason::kNoHint;
            decision.snapshot = SnapshotLocked();
            return decision;
        }

        if (lp_in_flight_ >= max_in_flight_limit_) {
            ++stats_.bubble_fill_rejected_count;
            ++stats_.bubble_reject_lp_in_flight_count;
            decision.reason = BubbleRejectReason::kLpInFlight;
            decision.snapshot = SnapshotLocked();
            return decision;
        }

        ++lp_in_flight_;
        ++stats_.bubble_fill_success_count;
        ++stats_.lp_child_launched_in_bubble_count;
        stats_.max_lp_in_flight = std::max<uint64_t>(stats_.max_lp_in_flight, lp_in_flight_);
        decision.allowed = true;
        decision.reason = BubbleRejectReason::kNone;
        decision.snapshot = SnapshotLocked();
        return decision;
    }

    void OnLpChildComplete()
    {
        std::lock_guard<std::mutex> lock(mu_);
        if (!enabled_) return;
        if (lp_in_flight_ == 0) {
            FailSafeCloseLocked();
            return;
        }
        --lp_in_flight_;
    }

    void OnBubbleOpen()
    {
        std::lock_guard<std::mutex> lock(mu_);
        if (!enabled_) return;
        ++stats_.bubble_open_count;
        if (hp_pending_ == 0 && state_ != BubbleAwareState::kHpActive) {
            state_ = BubbleAwareState::kOpen;
        }
    }

    void OnBubbleClose()
    {
        std::lock_guard<std::mutex> lock(mu_);
        if (!enabled_) return;
        ++stats_.bubble_close_count;
        if (state_ == BubbleAwareState::kClosed && fail_safe_) {
            FailSafeCloseLocked();
            return;
        }
        if (state_ != BubbleAwareState::kHpActive) state_ = BubbleAwareState::kClosed;
    }

    void OnHpEnqueue()
    {
        std::lock_guard<std::mutex> lock(mu_);
        if (!enabled_) return;
        ++hp_pending_;
        state_ = BubbleAwareState::kHpActive;
        ++stats_.stop_new_lp_on_hp_count;
        if (lp_in_flight_ > 0) ++stats_.hp_arrival_during_lp_child_count;
    }

    void OnHpQueueEmpty()
    {
        std::lock_guard<std::mutex> lock(mu_);
        if (!enabled_) return;
        hp_pending_ = 0;
        if (state_ == BubbleAwareState::kHpActive) state_ = BubbleAwareState::kClosed;
    }

    void FailSafeClose()
    {
        std::lock_guard<std::mutex> lock(mu_);
        if (!enabled_) return;
        FailSafeCloseLocked();
    }

    BubbleAwareSnapshot Snapshot() const
    {
        std::lock_guard<std::mutex> lock(mu_);
        return SnapshotLocked();
    }

private:
    BubbleAwareSnapshot SnapshotLocked() const
    {
        BubbleAwareSnapshot snapshot;
        snapshot.enabled = enabled_;
        snapshot.fail_safe = fail_safe_;
        snapshot.max_in_flight_limit = max_in_flight_limit_;
        snapshot.state = enabled_ ? state_ : BubbleAwareState::kDisabled;
        snapshot.hp_pending = hp_pending_;
        snapshot.lp_in_flight = lp_in_flight_;
        snapshot.stats = stats_;
        return snapshot;
    }

    void FailSafeCloseLocked()
    {
        ++stats_.bubble_fail_safe_count;
        state_ = hp_pending_ > 0 ? BubbleAwareState::kHpActive : BubbleAwareState::kClosed;
        if (lp_in_flight_ > max_in_flight_limit_) lp_in_flight_ = max_in_flight_limit_;
    }

    mutable std::mutex mu_;
    bool enabled_ = false;
    bool fail_safe_ = true;
    uint32_t max_in_flight_limit_ = 1;
    BubbleAwareState state_ = BubbleAwareState::kDisabled;
    uint32_t hp_pending_ = 0;
    uint32_t lp_in_flight_ = 0;
    BubbleAwareStats stats_;
};

} // namespace xsched::cuda::hb_split
