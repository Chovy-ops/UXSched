#include <dlfcn.h>

#include <cstdint>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "xsched/cuda/hal/common/cuda.h"

namespace
{

constexpr const char *kProbePtx = R"PTX(
.version 7.0
.target sm_50
.address_size 64

.visible .entry hb_xqueue_probe_kernel(
    .param .u64 hb_param_out,
    .param .u32 hb_param_n
)
{
    .reg .pred %p;
    .reg .b32 %r<6>;
    .reg .b64 %rd<4>;

    ld.param.u64 %rd1, [hb_param_out];
    ld.param.u32 %r1, [hb_param_n];
    mov.u32 %r2, %ctaid.x;
    mov.u32 %r3, %ntid.x;
    mov.u32 %r4, %tid.x;
    mad.lo.s32 %r5, %r2, %r3, %r4;
    setp.ge.u32 %p, %r5, %r1;
    @%p bra DONE;
    mul.wide.u32 %rd2, %r5, 4;
    add.s64 %rd3, %rd1, %rd2;
    st.global.u32 [%rd3], %r5;
DONE:
    ret;
}
)PTX";

template <typename Fn>
Fn Load(void *handle, const char *name)
{
    dlerror();
    void *sym = dlsym(RTLD_DEFAULT, name);
    if (sym == nullptr) sym = dlsym(handle, name);
    const char *err = dlerror();
    if (sym == nullptr || err != nullptr) {
        std::fprintf(stderr, "missing CUDA symbol %s: %s\n", name, err == nullptr ? "not found" : err);
        std::exit(2);
    }
    return reinterpret_cast<Fn>(sym);
}

void Check(CUresult ret, const char *op)
{
    if (ret == CUDA_SUCCESS) return;
    std::fprintf(stderr, "%s failed: CUDA error %d\n", op, static_cast<int>(ret));
    std::exit(1);
}

bool ArgEquals(const char *arg, const char *name)
{
    return std::strcmp(arg, name) == 0;
}

} // namespace

int main(int argc, char **argv)
{
    std::string stream_mode = "default";
    unsigned int blocks = 1024;
    unsigned int threads = 1;

    for (int i = 1; i < argc; ++i) {
        if (ArgEquals(argv[i], "--stream") && i + 1 < argc) {
            stream_mode = argv[++i];
        } else if (ArgEquals(argv[i], "--blocks") && i + 1 < argc) {
            blocks = static_cast<unsigned int>(std::strtoul(argv[++i], nullptr, 10));
        } else if (ArgEquals(argv[i], "--threads") && i + 1 < argc) {
            threads = static_cast<unsigned int>(std::strtoul(argv[++i], nullptr, 10));
        } else {
            std::fprintf(stderr, "usage: %s --stream default|explicit [--blocks N] [--threads N]\n",
                         argv[0]);
            return 2;
        }
    }

    if (stream_mode != "default" && stream_mode != "explicit") {
        std::fprintf(stderr, "--stream must be default or explicit\n");
        return 2;
    }
    if (blocks == 0 || threads == 0) {
        std::fprintf(stderr, "--blocks and --threads must be positive\n");
        return 2;
    }

    const char *cuda_lib = std::getenv("XSCHED_CUDA_LIB");
    if (cuda_lib == nullptr || cuda_lib[0] == '\0') cuda_lib = "libcuda.so.1";
    void *libcuda = dlopen(cuda_lib, RTLD_NOW | RTLD_GLOBAL);
    if (libcuda == nullptr) {
        std::fprintf(stderr, "dlopen(%s) failed: %s\n", cuda_lib, dlerror());
        return 2;
    }

    auto cuInit = Load<CUresult (*)(unsigned int)>(libcuda, "cuInit");
    auto cuDeviceGet = Load<CUresult (*)(CUdevice *, int)>(libcuda, "cuDeviceGet");
    auto cuDeviceGetName = Load<CUresult (*)(char *, int, CUdevice)>(libcuda, "cuDeviceGetName");
    auto cuDevicePrimaryCtxRetain =
        Load<CUresult (*)(CUcontext *, CUdevice)>(libcuda, "cuDevicePrimaryCtxRetain");
    auto cuDevicePrimaryCtxRelease =
        Load<CUresult (*)(CUdevice)>(libcuda, "cuDevicePrimaryCtxRelease");
    auto cuCtxSetCurrent = Load<CUresult (*)(CUcontext)>(libcuda, "cuCtxSetCurrent");
    auto cuCtxSynchronize = Load<CUresult (*)()>(libcuda, "cuCtxSynchronize");
    auto cuModuleLoadDataEx =
        Load<CUresult (*)(CUmodule *, const void *, unsigned int, CUjit_option *, void **)>(
            libcuda, "cuModuleLoadDataEx");
    auto cuModuleGetFunction =
        Load<CUresult (*)(CUfunction *, CUmodule, const char *)>(libcuda, "cuModuleGetFunction");
    auto cuModuleUnload = Load<CUresult (*)(CUmodule)>(libcuda, "cuModuleUnload");
    auto cuMemAlloc = Load<CUresult (*)(CUdeviceptr *, size_t)>(libcuda, "cuMemAlloc_v2");
    auto cuMemFree = Load<CUresult (*)(CUdeviceptr)>(libcuda, "cuMemFree_v2");
    auto cuMemcpyDtoH = Load<CUresult (*)(void *, CUdeviceptr, size_t)>(libcuda, "cuMemcpyDtoH_v2");
    auto cuStreamCreate = Load<CUresult (*)(CUstream *, unsigned int)>(libcuda, "cuStreamCreate");
    auto cuStreamSynchronize = Load<CUresult (*)(CUstream)>(libcuda, "cuStreamSynchronize");
    auto cuStreamDestroy = Load<CUresult (*)(CUstream)>(libcuda, "cuStreamDestroy_v2");
    auto cuLaunchKernel =
        Load<CUresult (*)(CUfunction, unsigned int, unsigned int, unsigned int,
                          unsigned int, unsigned int, unsigned int, unsigned int,
                          CUstream, void **, void **)>(libcuda, "cuLaunchKernel");

    Check(cuInit(0), "cuInit");
    CUdevice dev = 0;
    Check(cuDeviceGet(&dev, 0), "cuDeviceGet");
    char device_name[128] = {};
    Check(cuDeviceGetName(device_name, sizeof(device_name), dev), "cuDeviceGetName");
    CUcontext ctx = nullptr;
    Check(cuDevicePrimaryCtxRetain(&ctx, dev), "cuDevicePrimaryCtxRetain");
    Check(cuCtxSetCurrent(ctx), "cuCtxSetCurrent");

    CUmodule module = nullptr;
    Check(cuModuleLoadDataEx(&module, kProbePtx, 0, nullptr, nullptr), "cuModuleLoadDataEx");
    CUfunction function = nullptr;
    Check(cuModuleGetFunction(&function, module, "hb_xqueue_probe_kernel"), "cuModuleGetFunction");

    CUstream stream = nullptr;
    if (stream_mode == "explicit") {
        Check(cuStreamCreate(&stream, CU_STREAM_NON_BLOCKING), "cuStreamCreate");
    }

    const uint32_t n = blocks * threads;
    CUdeviceptr out = 0;
    Check(cuMemAlloc(&out, n * sizeof(uint32_t)), "cuMemAlloc");

    void *params[] = {&out, const_cast<uint32_t *>(&n)};
    std::printf("cuda_device=%s\n", device_name);
    std::printf("stream_mode=%s\n", stream_mode.c_str());
    std::printf("stream_handle=%p\n", stream);
    std::printf("kernel=hb_xqueue_probe_kernel\n");
    std::printf("blocks=%u\n", blocks);
    std::printf("threads=%u\n", threads);

    Check(cuLaunchKernel(function, blocks, 1, 1, threads, 1, 1, 0, stream, params, nullptr),
          "cuLaunchKernel");
    if (stream == nullptr) {
        Check(cuCtxSynchronize(), "cuCtxSynchronize");
    } else {
        Check(cuStreamSynchronize(stream), "cuStreamSynchronize");
    }

    std::vector<uint32_t> host(n);
    Check(cuMemcpyDtoH(host.data(), out, host.size() * sizeof(uint32_t)), "cuMemcpyDtoH");
    uint64_t checksum = 0;
    uint32_t mismatches = 0;
    for (uint32_t i = 0; i < n; ++i) {
        checksum += host[i];
        if (host[i] != i) ++mismatches;
    }
    std::printf("checksum=%" PRIu64 "\n", checksum);
    std::printf("mismatches=%u\n", mismatches);

    Check(cuMemFree(out), "cuMemFree");
    if (stream != nullptr) Check(cuStreamDestroy(stream), "cuStreamDestroy");
    Check(cuModuleUnload(module), "cuModuleUnload");
    Check(cuDevicePrimaryCtxRelease(dev), "cuDevicePrimaryCtxRelease");
    return mismatches == 0 ? 0 : 1;
}
