'''
source ~/klippy-env/bin/activate
'''
#region 编码器代码
# #/home/orangepi/printer_data/gcodes/test/data-polar.txt
import gpiod
from gpiod.line import Edge

def edge_type_str(event):
    if event.event_type is event.Type.RISING_EDGE:
        return "Rising"
    if event.event_type is event.Type.FALLING_EDGE:
        return "Falling"
    return "Unknown"

def watch_multiple_line_values(chip_path, line_offsets):
    encoder_count = 0  # 初始化编码器计数

    with gpiod.request_lines(
        chip_path,
        consumer="watch-multiple-line-values",
        config={tuple(line_offsets): gpiod.LineSettings(edge_detection=Edge.RISING)},
    ) as request:
        while True:
            for event in request.read_edge_events():
                if event.line_offset == ch_I:
                    
                    print("Reset encoder count due to ch_I rising edge.")
                    print(encoder_count)
                    encoder_count = 0  # 重置计数
                elif event.line_offset == ch_A:
                    encoder_count += 1           
                    # print(
                    #     "offset: {}  type: {:<7}  event #{}  line event #{}  encoder count: {}".format(
                    #         event.line_offset,
                    #         edge_type_str(event),
                    #         event.global_seqno,
                    #         event.line_seqno,
                    #         encoder_count,
                    #     )
                    # )

if __name__ == "__main__":
    ch_I = 24
    ch_A = 23
    ch_B = 22
    try:
        watch_multiple_line_values("/dev/gpiochip1", [ch_I, ch_A, ch_B])
    except OSError as ex:
        print(ex, "\nCustomise the example configuration to suit your situation")
#endregion 

#region 发送数据对比
# import serial
# import time
# import os

# # 串口和文件路径
# ser = serial.Serial(port='/dev/ttyACM0')
# data_file_path = "/home/orangepi/printer_data/gcodes/test/1.txt"
# output_file_path = "/home/orangepi/printer_data/gcodes/test/received_data.txt"

# # 发送数据并接收响应
# with open(data_file_path, "r", encoding="utf-8-sig") as file, open(output_file_path, "wb") as output_file:
#     while True:  
#         chunk = file.read(512)
#         if not chunk:           
#             break  # 文件已读完
#         bytes_data = chunk.encode('utf-8')
#         ser.write(bytes_data)
#         time.sleep(0.05)

#         # 循环读取串口返回的数据
#         while True:
#             rev = ser.read(ser.in_waiting)
#             if rev:
#                 output_file.write(rev)
#             time.sleep(0.05)
#             if ser.in_waiting == 0:
#                 break  # 如果没有更多数据，则跳出循环

# ser.close()

# # 比较发送和接收的文件内容
# with open(data_file_path, "r", encoding="utf-8-sig") as sent_file, open(output_file_path, "rb") as received_file:
#     sent_content = sent_file.read().encode('utf-8')  # 将发送的文件内容编码为字节
#     received_content = received_file.read()  # 读取接收的文件内容

#     differences = []  # 用于存储差异信息
#     min_len = min(len(sent_content), len(received_content))  # 获取最小长度以进行比较

#     # 比较两个文件的内容字节
#     for i in range(min_len):
#         if sent_content[i] != received_content[i]:
#             differences.append((i, sent_content[i], received_content[i]))

#     # 检查文件长度差异
#     if len(sent_content) != len(received_content):
#         differences.append(("文件长度不同", len(sent_content), len(received_content)))

#     # 输出比较结果
#     if not differences:
#         print("发送和接收的文件内容相同")
#     else:
#         print("发送和接收的文件内容不相同")
#         for diff in differences:
#             if isinstance(diff[0], str):  # 文件长度不同的信息
#                 print(f"{diff[0]}: 发送文件长度 = {diff[1]} 字节, 接收文件长度 = {diff[2]} 字节")
#             else:  # 字节差异的信息
#                 print(f"位置 {diff[0]}: 发送内容 = {diff[1]} (字符: {chr(diff[1])}), 接收内容 = {diff[2]} (字符: {chr(diff[2])})")
#endregion 



