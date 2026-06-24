import sys        # 导入系统模块，用于访问与 Python 解释器相关的变量和函数
import time       # 导入时间模块，用于计算推理耗时和吞吐量
import torch      # 导入 PyTorch 核心库
import torchvision # 导入计算机视觉模型库
import torch_npu  # 导入昇腾 NPU 后端支持库，使 PyTorch 能调用昇腾 NPU
import argparse   # 导入参数解析模块，用于处理命令行输入的运行次数参数

BATCH_SIZE = 32   # 定义每次输入模型的图片张数（批大小）

# 定义推理函数，model 为模型，input 为输入张量
def infer(model, input):
    with torch.no_grad():          # 禁用梯度计算，推理时不需要求导，节省显存和计算资源
        return model(input).cpu()  # 执行模型推理，并将结果从 NPU 搬回 CPU 内存

# 定义性能测试函数，run_cnt 为单轮推理的循环次数
def run(run_cnt):
    # 从 torchvision 加载预训练好的 ResNet152 模型
    model = torchvision.models.resnet152(weights=torchvision.models.ResNet152_Weights.DEFAULT)
    # 将模型切换到评估模式（关闭 Dropout 等层），并移动到 NPU 上
    model.eval().npu()
    # 创建一个模拟的输入张量（大小为 BATCH_SIZE * 3 通道 * 224 * 224），并移动到 NPU
    input = torch.ones(BATCH_SIZE, 3, 224, 224).npu()
    
    # 执行一次推理以预热 NPU 环境（初始化必要的计算上下文）
    print(infer(model, input))
    
    # 进入死循环，进行持续性能压测
    while True:
        start = time.time()       # 记录一轮测试开始的时间戳
        for i in range(run_cnt):  # 循环执行 run_cnt 次推理
            infer(model, input)
        end = time.time()         # 记录一轮测试结束的时间戳
        
        # 计算吞吐量：总图片数 / 总耗时，单位为：图片/秒 (img/s)
        print(f"thpt: {BATCH_SIZE * run_cnt / (end - start):.2f} img/s")

# 主程序入口
if __name__ == "__main__":
    # 创建参数解析器对象，用于描述脚本用途
    argparse = argparse.ArgumentParser(description="ResNet152 inference on Ascend NPU")
    # 添加 -c 或 --run-cnt 参数，设置单轮推理执行次数，默认为 10
    argparse.add_argument("-c", "--run-cnt", type=int, default=10, help="Run count for inference")
    args = argparse.parse_args() # 解析命令行参数
    
    run_cnt = args.run_cnt       # 获取并设置运行次数
    run(run_cnt)                 # 调用 run 函数开始压测