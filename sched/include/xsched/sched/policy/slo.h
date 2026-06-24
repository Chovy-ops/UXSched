#pragma once

#include <map>
#include <chrono>

#include "xsched/types.h"
#include "xsched/protocol/def.h"
#include "xsched/sched/policy/policy.h"

namespace xsched::sched
{

struct SLOQueueInfo
{
    Priority priority = PRIORITY_DEFAULT;
    Deadline deadline_us = NO_DEADLINE;
    Utilization utilization = UTILIZATION_DEFAULT;
    double vruntime = 0.0;
    bool running = false;
    std::chrono::system_clock::time_point last_resume_time;
};

class SLOAdaptivePolicy : public Policy
{
public:
    SLOAdaptivePolicy() : Policy(kPolicySLOAdaptive) {}
    virtual ~SLOAdaptivePolicy() = default;

    virtual void Sched(const Status &status) override;
    virtual void RecvHint(std::shared_ptr<const Hint> hint) override;

private:
    SLOQueueInfo &GetInfo(XQueueHandle handle);
    Utilization GetUtilization(const XQueueStatus &status, const SLOQueueInfo &info) const;
    bool IsLatencySensitive(const SLOQueueInfo &info) const;
    double GetSlackUs(const XQueueStatus &status, const SLOQueueInfo &info,
                      std::chrono::system_clock::time_point now) const;
    XQueueHandle PickBestQueue(XDevice device, const Status &status,
                               std::chrono::system_clock::time_point now);
    void UpdateRuntime(const Status &status, std::chrono::system_clock::time_point now);

    std::map<XQueueHandle, SLOQueueInfo> queue_infos_;
    std::map<PID, Utilization> process_utils_;
    std::chrono::microseconds tick_ = std::chrono::microseconds(TIMESLICE_DEFAULT);
};

} // namespace xsched::sched
