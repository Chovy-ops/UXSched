#include <algorithm>
#include <limits>
#include <map>

#include "xsched/utils/log.h"
#include "xsched/utils/xassert.h"
#include "xsched/sched/policy/slo.h"

using namespace xsched::sched;

SLOQueueInfo &SLOAdaptivePolicy::GetInfo(XQueueHandle handle)
{
    auto it = queue_infos_.find(handle);
    if (it != queue_infos_.end()) return it->second;

    auto &info = queue_infos_[handle];
    info.last_resume_time = std::chrono::system_clock::now();
    return info;
}

Utilization SLOAdaptivePolicy::GetUtilization(const XQueueStatus &status,
                                              const SLOQueueInfo &info) const
{
    auto proc_it = process_utils_.find(status.pid);
    Utilization util = proc_it == process_utils_.end() ? info.utilization : proc_it->second;
    if (util < UTILIZATION_MIN) return UTILIZATION_MIN;
    if (util > UTILIZATION_MAX) return UTILIZATION_MAX;
    return util;
}

bool SLOAdaptivePolicy::IsLatencySensitive(const SLOQueueInfo &info) const
{
    return info.deadline_us != NO_DEADLINE || info.priority > PRIORITY_DEFAULT;
}

double SLOAdaptivePolicy::GetSlackUs(const XQueueStatus &status, const SLOQueueInfo &info,
                                     std::chrono::system_clock::time_point now) const
{
    if (info.deadline_us == NO_DEADLINE) return std::numeric_limits<double>::infinity();
    auto waited = std::chrono::duration_cast<std::chrono::microseconds>(now - status.ready_time).count();
    return (double)info.deadline_us - (double)waited;
}

void SLOAdaptivePolicy::UpdateRuntime(const Status &status, std::chrono::system_clock::time_point now)
{
    for (auto &entry : status.xqueue_status) {
        XQueueHandle handle = entry.second->handle;
        auto &info = GetInfo(handle);
        if (!info.running) continue;

        auto elapsed_us = std::chrono::duration_cast<std::chrono::microseconds>(
            now - info.last_resume_time).count();
        if (elapsed_us <= 0) continue;

        Utilization util = std::max(GetUtilization(*entry.second, info), (Utilization)1);
        info.vruntime += (double)elapsed_us * ((double)UTILIZATION_DEFAULT / (double)util);
        info.last_resume_time = now;
    }
}

XQueueHandle SLOAdaptivePolicy::PickBestQueue(XDevice device, const Status &status,
                                              std::chrono::system_clock::time_point now)
{
    XQueueHandle best_urgent = 0;
    double best_slack = std::numeric_limits<double>::infinity();
    Priority best_urgent_prio = PRIORITY_MIN;

    XQueueHandle best_latency = 0;
    Priority best_latency_prio = PRIORITY_MIN;
    double best_latency_slack = std::numeric_limits<double>::infinity();

    XQueueHandle best_batch = 0;
    double best_vruntime = std::numeric_limits<double>::infinity();

    for (auto &entry : status.xqueue_status) {
        const auto &st = *entry.second;
        if (!st.ready || st.device != device) continue;

        auto &info = GetInfo(st.handle);
        double slack = GetSlackUs(st, info, now);
        bool latency_sensitive = IsLatencySensitive(info);
        bool urgent = info.deadline_us != NO_DEADLINE && slack <= (double)tick_.count();

        if (urgent && (slack < best_slack ||
            (slack == best_slack && info.priority > best_urgent_prio))) {
            best_urgent = st.handle;
            best_slack = slack;
            best_urgent_prio = info.priority;
        }

        if (latency_sensitive && (info.priority > best_latency_prio ||
            (info.priority == best_latency_prio && slack < best_latency_slack))) {
            best_latency = st.handle;
            best_latency_prio = info.priority;
            best_latency_slack = slack;
        }

        if (!latency_sensitive && info.vruntime < best_vruntime) {
            best_batch = st.handle;
            best_vruntime = info.vruntime;
        }
    }

    if (best_urgent != 0) return best_urgent;
    if (best_latency != 0) return best_latency;
    return best_batch;
}

void SLOAdaptivePolicy::Sched(const Status &status)
{
    auto now = std::chrono::system_clock::now();
    UpdateRuntime(status, now);

    std::map<XDevice, XQueueHandle> chosen;
    bool has_ready = false;
    for (auto &entry : status.xqueue_status) {
        if (!entry.second->ready) continue;
        has_ready = true;
        XDevice device = entry.second->device;
        if (chosen.find(device) == chosen.end()) {
            chosen[device] = PickBestQueue(device, status, now);
        }
    }

    for (auto &entry : status.xqueue_status) {
        const auto &st = *entry.second;
        auto &info = GetInfo(st.handle);

        if (!st.ready) {
            info.running = false;
            continue;
        }

        if (chosen[st.device] == st.handle) {
            if (!info.running) {
                Resume(st.handle);
                info.running = true;
            }
            info.last_resume_time = now;
        } else {
            if (info.running || !st.suspended) Suspend(st.handle);
            info.running = false;
        }
    }

    if (has_ready) AddTimer(now + tick_);
}

void SLOAdaptivePolicy::RecvHint(std::shared_ptr<const Hint> hint)
{
    switch (hint->Type())
    {
    case kHintTypePriority:
    {
        auto h = std::dynamic_pointer_cast<const PriorityHint>(hint);
        XASSERT(h != nullptr, "hint type not match");
        auto &info = GetInfo(h->Handle());
        info.priority = std::min(std::max(h->Prio(), PRIORITY_MIN), PRIORITY_MAX);
        XINFO("SLO: set priority %d for XQueue 0x" FMT_64X, info.priority, h->Handle());
        break;
    }
    case kHintTypeDeadline:
    {
        auto h = std::dynamic_pointer_cast<const DeadlineHint>(hint);
        XASSERT(h != nullptr, "hint type not match");
        auto &info = GetInfo(h->Handle());
        info.deadline_us = h->Ddl();
        XINFO("SLO: set deadline " FMT_64D " us for XQueue 0x" FMT_64X,
              info.deadline_us, h->Handle());
        break;
    }
    case kHintTypeUtilization:
    {
        auto h = std::dynamic_pointer_cast<const UtilizationHint>(hint);
        XASSERT(h != nullptr, "hint type not match");
        Utilization util = std::min(std::max(h->Util(), UTILIZATION_MIN), UTILIZATION_MAX);
        if (h->Handle() != 0) {
            GetInfo(h->Handle()).utilization = util;
            XINFO("SLO: set utilization %d for XQueue 0x" FMT_64X, util, h->Handle());
        }
        if (h->Pid() != 0) {
            process_utils_[h->Pid()] = util;
            XINFO("SLO: set utilization %d for process " FMT_PID, util, h->Pid());
        }
        break;
    }
    case kHintTypeTimeslice:
    {
        auto h = std::dynamic_pointer_cast<const TimesliceHint>(hint);
        XASSERT(h != nullptr, "hint type not match");
        if (h->Ts() >= TIMESLICE_MIN && h->Ts() <= TIMESLICE_MAX) {
            tick_ = std::chrono::microseconds(h->Ts());
            XINFO("SLO: set scheduling tick to " FMT_64D " us", h->Ts());
        }
        break;
    }
    default:
        XWARN("SLO: unsupported hint type: %d", hint->Type());
        break;
    }
}
