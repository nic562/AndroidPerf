from abc import ABCMeta
import re
import time

from .abstract_adb import AdbInterface
from .log import default as logging


class TrafficInfo:
    """
    mobile: 12345G 移动流量
    wifi: 网关流量
    rx: 接收流量
    tx: 发送流量
    单位：字节
    cost_ms: 指令数据获取所消耗时间，毫秒
    """
    mobile_total: int
    wifi_total: int
    rx_total: int
    tx_total: int

    def __init__(self):
        self.mobile_rx = 0
        self.mobile_tx = 0
        self.wifi_rx = 0
        self.wifi_tx = 0
        self.cost_ms = 0

    def compute_total(self):
        self.mobile_total = self.mobile_rx + self.mobile_tx
        self.wifi_total = self.mobile_rx + self.mobile_tx
        self.rx_total = self.mobile_rx + self.wifi_rx
        self.tx_total = self.mobile_tx + self.wifi_tx
        return self


class TrafficAdb(AdbInterface, metaclass=ABCMeta):
    _net_files = ['tcp', 'tcp6', 'udp', 'udp6']

    def _get_net_flow_raw(self, uid: str, target_net_file: str):
        """
        读取 tcp 或 udp 流量统计
        兼容性不好，某些Android版本中，这些文件已经不存在，或者无权限读取
        :param uid:
        :param target_net_file: 参考 _net_files
        :return:
        """
        # 状态字参考:https://users.cs.northwestern.edu/~agupta/cs340/project2/TCPIP_State_Transition_Diagram.pdf
        # https://guanjunjian.github.io/2017/11/09/study-8-proc-net-tcp-analysis/
        # https://zhuanlan.zhihu.com/p/49981590
        rs = self.run_shell(f'cat /proc/net/{target_net_file} | grep {uid}')
        if rs:
            ll = []
            for r in rs.split('\n'):
                if not r:
                    continue
                m = re.split(r'\s+', r.strip())
                if m and m[7] == uid:
                    ll.append(m)
            return ll

    @staticmethod
    def byte2kb(v: int) -> float:
        return round(v / 1024.0, 2)

    @staticmethod
    def _traffic_parse_line(rs: str):
        # 原始数据的每一行，第2个信息为接收流量，第10个信息为发送流量
        items = rs.split()
        return items[1], items[9]

    def _traffic_parse(self, rs: str, start_ms: int):
        if rs.find('No such') != -1:
            # 进程有可能被销毁
            raise KeyError(f'Bad return: {rs}')
        if rs.find('error') != -1:
            raise ValueError(f'Error return: {rs}')
        end_ms = int(time.time() * 1000)
        info = TrafficInfo()
        info.cost_ms = end_ms - start_ms
        for line in rs.split('\n'):
            if 'wlan0' in line:
                # wifi 流量
                info.wifi_rx, info.wifi_tx = self._traffic_parse_line(line)
            elif 'rmnet0' in line:
                info.mobile_rx, info.mobile_tx = self._traffic_parse_line(line)
        return info.compute_total()

    def get_device_traffic(self) -> TrafficInfo:
        """获取设备整机流量统计
        注意：该数据为设备启动（重启后归0）后开始累计的
        """
        _t = int(time.time() * 1000)
        rs = self.run_shell('cat /proc/net/dev', clean_wrap=True)
        return self._traffic_parse(rs, _t)

    def get_process_traffic(self, pid) -> TrafficInfo:
        """
        获取具体进程的流量统计，结果是从进程创建开始的累计值
        进程文件在进程销毁后就删掉
        """
        _t = int(time.time() * 1000)
        rs = self.run_shell(f'cat /proc/{pid}/net/dev', clean_wrap=True)
        return self._traffic_parse(rs, _t)

    def get_processes_traffic(self, process_id_list: list[int], auto_remove_miss_process=True) -> TrafficInfo:
        """
        每个App可能会有多个进程
        获取目标Apps进程id列表的最新流量汇总，结果是从进程创建开始的累计值
        :param process_id_list: App的进程列表
        :param auto_remove_miss_process: 是否从process_id_list中清理不存在进程ID
        :return: 当前总的目标App流量
        """
        miss_pid_list = []
        total = TrafficInfo()
        for pi in process_id_list:
            try:
                traffic = self.get_process_traffic(pi)
            except KeyError as e:
                if str(e).find('No such') != -1:
                    logging.warning(f'process miss:{pi}')
                    miss_pid_list.append(pi)
                    continue
                raise e
            total.wifi_rx += traffic.wifi_rx
            total.wifi_tx += traffic.wifi_tx
            total.mobile_rx += traffic.mobile_rx
            total.mobile_tx += traffic.mobile_tx
            total.cost_ms += traffic.cost_ms

        if auto_remove_miss_process:
            for xp in miss_pid_list:
                process_id_list.remove(xp)
        return total
